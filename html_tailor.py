import os
import json
import re
import config

# Helper pour lire les experiences depuis user_data
def _load_exp(index):
    path = os.path.join("user_data", f"exp{index}.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return f"Experience {index} non configuree dans user_data/exp{index}.txt"

def generate_html_experience(offre, exp_index, context_text):
    from ai_helper import _call_ia
    
    if exp_index in [1, 2]:
        bullets = 5
        subtitle_req = "INCLUS OBLIGATOIREMENT un sous-titre de resume avec la balise <div class=\"exp-subtitle\">➔ ...</div>"
    else:
        bullets = 3
        subtitle_req = "NE METS PAS de div exp-subtitle. Juste la liste ul."
        
    prompt = f"""
Tu es un expert en optimisation de CV pour les systemes ATS et le recrutement digital.
Reformule mon experience n°{exp_index} pour l'offre : {offre.get('titre')} chez {offre.get('entreprise')}.

OFFRE :
{offre.get('description', '')[:1000]}

MON EXPERIENCE :
{context_text}

CONTRAINTES :
- HTML UNIQUEMENT.
- {subtitle_req}
- Liste <ul class="exp-bullets"> avec EXACTEMENT {bullets} balises <li>.
- Mets en <strong> les mots-cles de l'offre.
"""
    try:
        html = _call_ia(prompt, max_tokens=1000)
        # Nettoyage markdown si present
        html = re.sub(r"```html|```", "", html).strip()
        return html
    except Exception as e:
        print(f"  [AI ERROR] Exp {exp_index}: {e}")
        return ""

def adapter_cv_html(html_template_path, offre, dossier_sortie="test_cv_outputs"):
    import datetime
    os.makedirs(dossier_sortie, exist_ok=True)
    
    print("  [INFO] Lecture du Template HTML...")
    with open(html_template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
        
    for i in range(1, 4):
        print(f"  [IA] Generation de l'Experience {i}...")
        exp_text = _load_exp(i)
        html_exp = generate_html_experience(offre, i, exp_text)
        
        # Injection
        placeholder_bullets = f'{{{{EXP{i}_BULLETS}}}}'
        placeholder_subtitle = f'<div class="exp-subtitle">➔ {{{{EXP{i}_SUBTITLE}}}}</div>'
        
        html_content = html_content.replace(placeholder_subtitle, '')
        html_content = html_content.replace(f'<ul class="exp-bullets">\n                        {placeholder_bullets}\n                    </ul>', html_exp)
        # Fallback pour remplacement direct sans le wrapping ul si l'IA a deja mis le ul
        html_content = html_content.replace(placeholder_bullets, html_exp)

    # Sanitarisation des infos perso via config
    html_content = html_content.replace('{{PRENOM}}', config.PRENOM)
    html_content = html_content.replace('{{NOM}}', config.NOM)
    html_content = html_content.replace('{{TELEPHONE}}', config.TELEPHONE)
    html_content = html_content.replace('{{EMAIL}}', config.EMAIL)
    
    titre_propre = "".join([c if c.isalnum() else "_" for c in offre.get('titre', 'Poste')])
    entreprise_propre = "".join([c if c.isalnum() else "_" for c in offre.get('entreprise', 'Ent')])
    
    annee = datetime.datetime.now().year
    filename = f"{config.PRENOM}_{config.NOM.upper()}_{entreprise_propre[:15]}_{annee}.html"
    
    output_path_html = os.path.join(dossier_sortie, filename)
    with open(output_path_html, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    # Conversion HTML -> PDF via Playwright
    output_path_pdf = output_path_html.replace(".html", ".pdf")
    print(f"  [PDF] Conversion HTML en PDF...")
    
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            # On utilise l'URL absolue du fichier local
            abs_html_path = os.path.abspath(output_path_html)
            page.goto(f"file:///{abs_html_path}")
            # Attendre un peu que les polices chargent si besoin
            page.wait_for_timeout(1000)
            page.pdf(path=output_path_pdf, format="A4", print_background=True)
            browser.close()
        
        # On definit le nom du CV pour l'upload (nom fixe attendu par le bot pour simplifier)
        annee = datetime.datetime.now().year
        nom_cv_upload = f"{config.PRENOM} {config.NOM.upper()} {annee}.pdf"
        import shutil
        shutil.copy2(output_path_pdf, os.path.abspath(nom_cv_upload))
        
        print(f"  [OK] CV PDF genere : {output_path_pdf}")
        return os.path.abspath(nom_cv_upload)
    except Exception as e:
        print(f"  [ERROR] Echec conversion PDF: {e}")
        return output_path_html # Fallback sur le HTML (peu probable que ca marche pour l'upload)
