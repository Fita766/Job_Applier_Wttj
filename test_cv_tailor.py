import os
import sys
from cv_tailor import adapter_cv_pptx

def test_dynamic_cv():
    print("--- Test de la generation dynamique de CV ---")
    
    # Tentative de recuperer le path via argument CLI
    if len(sys.argv) > 1:
        pptx_path = sys.argv[1].strip().strip('"').strip("'")
    else:
        pptx_path = input("Chemin de ton fichier PPTX (ex: C:\\Users\\...\\CV.pptx) : ").strip().strip('"').strip("'")
    
    if not pptx_path or not os.path.exists(pptx_path):
        print(f"[ERROR] Fichier introuvable : {pptx_path}")
        return

    # Tentative de lire l'offre depuis offre_test.txt
    if os.path.exists("offre_test.txt"):
        with open("offre_test.txt", "r", encoding="utf-8") as f:
            job_description = f.read().strip()
        if "Colle ici la description" in job_description or not job_description:
            print("\n?? ??  'offre_test.txt' est vide ou contient encore le texte par defaut.")
            job_description = ""
        else:
            print(f"\n??"? Description lue depuis 'offre_test.txt' ({len(job_description)} caracteres)")
    else:
        print("\nEntre la description de l'offre (ou colle-la).")
        print("Appuie sur Ctrl+Z (Windows) puis Entree pour terminer la saisie :\n")
        try:
            job_description = sys.stdin.read()
        except EOFError:
            job_description = ""
        
    if not job_description.strip():
        print("[FAST] Description vide, utilisation d'une offre fictive...")
        offre_test = {
            "entreprise": "Entreprise de Test",
            "titre": "Chef de Projet Digital",
            "description": "Exemple d'offre..."
        }
    else:
        # On demande a l'IA d'extraire le titre et l'entreprise du texte brut
        print("  ??"  Analyse de l'offre pour extraire l'entreprise et le titre...")
        from ai_helper import _call_openai_with_mistral_fallback
        prompt_extract = f"""
        Extrait le nom de l'entreprise et l'intitule du poste de cette offre d'emploi.
        Renvoie SEULEMENT un JSON de ce format : {{"entreprise": "...", "titre": "..."}}
        
        Texte :
        {job_description[:1000]}
        """
        try:
            res = _call_openai_with_mistral_fallback(prompt_extract, max_tokens=100)
            res = res.strip()
            if "```" in res: res = res.split("```")[1].split("```")[0].strip()
            if res.startswith("json"): res = res[4:].strip()
            import json
            info = json.loads(res)
            offre_test = {
                "entreprise": info.get("entreprise", "Inconnue"),
                "titre": info.get("titre", "Inconnu"),
                "description": job_description
            }
            print(f"  ?????  Entreprise d??tect??e : {offre_test['entreprise']}")
            print(f"  ?????  Poste d??tect?? : {offre_test['titre']}")
        except Exception:
            offre_test = {
                "entreprise": "Entreprise Test",
                "titre": "Poste Test",
                "description": job_description
            }

    print("\n[START] Lancement de l'adaptation...")
    try:
        pdf_genere = adapter_cv_pptx(pptx_path, offre_test, dossier_sortie="test_cv_outputs")
        
        if pdf_genere and os.path.exists(pdf_genere):
            print(f"\n[OK] SUCCES !")
            print(f"   Le CV uploade sera : {pdf_genere}")
            print(f"   L'archive est dans le dossier 'test_cv_outputs'")
        else:
            print("\n[ERROR] La generation a echoue (verifie tes cles API et si PowerPoint est ouvert).")
            
    except Exception as e:
        print(f"\n[ERROR] Une erreur est survenue : {e}")

if __name__ == "__main__":
    test_dynamic_cv()
