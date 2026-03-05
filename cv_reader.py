"""
Utilitaire pour lire le CV (PDF ou TXT)
"""
import os

def lire_cv(cv_path: str) -> str:
    """Lit le CV et retourne son contenu en texte brut."""
    if not os.path.exists(cv_path):
        raise FileNotFoundError(
            f"❌ CV introuvable : '{cv_path}'\n"
            f"   Place ton CV dans le dossier du script et mets à jour CV_PATH dans config.py"
        )

    extension = cv_path.lower().split(".")[-1]

    if extension == "pdf":
        try:
            import PyPDF2
            text = []
            with open(cv_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text.append(page.extract_text() or "")
            return "\n".join(text)
        except ImportError:
            raise ImportError("PyPDF2 non installé. Lance : pip install PyPDF2")

    elif extension == "txt":
        with open(cv_path, "r", encoding="utf-8") as f:
            return f.read()

    else:
        raise ValueError(f"Format de CV non supporté : .{extension} (utilise .pdf ou .txt)")
