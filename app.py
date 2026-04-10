import os
import sys
import json
import subprocess
import threading
import queue
import time
from datetime import datetime

# Auto-install Flask si manquant
try:
    from flask import Flask, render_template, jsonify, Response, request
except ImportError:
    print("Installation de Flask en cours...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
    from flask import Flask, render_template, jsonify, Response, request

app = Flask(__name__)
log_queue = queue.Queue(maxsize=1000)
bot_process = None

def get_timestamp():
    return datetime.now().strftime("%H:%M:%S")

def stream_logs(proc):
    global bot_process
    # En mode texte (text=True), readline() renvoie directement une string
    for line in iter(proc.stdout.readline, ''):
        stripped = line.rstrip()
        if stripped:
            log_queue.put(f"[{get_timestamp()}] {stripped}")
    
    proc.stdout.close()
    proc.wait()
    log_queue.put(f"[{get_timestamp()}] [SYSTEM] Le bot a termine son execution (Code: {proc.returncode})")
    bot_process = None

@app.route('/')
def index():
    # Renders the UI
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    global bot_process
    is_running = bot_process is not None and bot_process.poll() is None
    return jsonify({"isRunning": is_running})

@app.route('/api/candidatures')
def get_candidatures():
    try:
        data = []
        if os.path.exists('candidatures.json'):
            with open('candidatures.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
        
        # S'assurer que chaque element a les bonnes cles
        formatted_data = [] # List
        if isinstance(data, dict):
            # candidatures.json de WTTJ bot est souvent un objet "entreprise": {details}
            for company, details in data.items():
                if isinstance(details, dict):
                    formatted_data.append({
                        "entreprise": company,
                        "poste": details.get("poste", details.get("titre", "N/A")),
                        "statut": details.get("statut", details.get("status", "pending")),
                        "date": details.get("date", "Aujourd'hui"),
                        "url": details.get("url", details.get("link", "#"))
                    })
                elif isinstance(details, list):
                    # Cas ou ce serait un array de dicos
                    for d in details:
                        if isinstance(d, dict):
                            d["entreprise"] = d.get("entreprise", company) # fallback
                            formatted_data.append(d)
        elif isinstance(data, list):
            formatted_data = data
            
        # Reverse sort par defaut
        return jsonify({"success": True, "candidatures": formatted_data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "candidatures": []}), 500

@app.route('/api/start-bot', methods=['POST'])
def start_bot():
    global bot_process
    if bot_process is not None and bot_process.poll() is None:
        return jsonify({"status": "error", "message": "Le bot est d?j? en cours d'ex?cution."}), 400
    
    try:
        data = request.json or {}
        search_url = data.get('url', '')
        cv_mode = data.get('cv_mode', 'direct')
        llm_choice = data.get('llm', 'mistral')
        max_offres = data.get('max_offres')
        max_pages = data.get('max_pages')
        skip_letter = data.get('skip_letter', False)
        
        # Lancer le bot via subprocess en flushant stdout/stderr
        # PYTHONUNBUFFERED=1 pour s'assurer que les prints apparaissent en temps reel
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        
        log_queue.put(f"[{get_timestamp()}] [SYSTEM] D?marrage du Workflow (Mode: {cv_mode.upper()}, LLM: {llm_choice.upper()})...")
        
        # On met les options AVANT l'argument positionnel URL pour eviter les ambiguites argparse
        cmd = [sys.executable, 'main.py', '--cv-mode', cv_mode, '--llm', llm_choice]
        
        if skip_letter:
            cmd.append('--skip-letter')
        if max_offres:
            cmd.extend(['--max', str(max_offres)])
        if max_pages:
            cmd.extend(['--max-pages', str(max_pages)])
            
        if search_url:
            cmd.extend(['--url', search_url])
        else:
            log_queue.put(f"[{get_timestamp()}] [ERROR] URL de recherche manquante !")
            return jsonify({"status": "error", "message": "URL de recherche manquante."}), 400
            
        # stdin=subprocess.PIPE permet d'envoyer des commandes au bot (ex: presser Entree)
        bot_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env
        )
        
        # Streamer la sortie via un thread dedie
        thread = threading.Thread(target=stream_logs, args=(bot_process,))
        thread.daemon = True
        thread.start()
        
        return jsonify({"status": "started", "message": "Bot d?marr? avec succ?s."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/stream-logs')
def sse_logs():
    def generate():
        while True:
            try:
                # get timeout for SSE heartbeats
                line = log_queue.get(timeout=2.0)
                # Escape for SSE
                yield f"data: {line}\n\n"
            except queue.Empty:
                yield ": heartbeat\n\n" # standard SSE comment for keep alive
            except Exception as e:
                print("SSE Erreur:", e)
                break
    
    return Response(generate(), mimetype='text/event-stream', headers={"Cache-Control": "no-cache"})

@app.route('/resume', methods=['POST'])
def resume_bot():
    """Envoie un signal 'Entree' au bot pour valider une action manuelle."""
    global bot_process
    if bot_process and bot_process.poll() is None:
        try:
            # On envoie un simple saut de ligne pour simuler la touche Entree
            bot_process.stdin.write('\n')
            bot_process.stdin.flush()
            log_queue.put(f"[{get_timestamp()}] [SYSTEM] Signal de reprise envoye au bot.")
            return jsonify({"status": "success", "message": "Signal envoye."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    return jsonify({"status": "error", "message": "Aucun bot en cours d'execution."})


if __name__ == '__main__':
    print("=======================================")
    print("Universal Job Applier AI v2.2.1")
    print("Dashboard : Demarrage local...")
    print("Ouvre http://127.0.0.1:5000 dans ton navigateur !")
    print("=======================================")
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)
