import os
from dotenv import load_dotenv


load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_nullable_int(name: str, default: int | None) -> int | None:
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = value.strip().lower()
    if cleaned in {"", "none", "null"}:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return default


# API Mistral
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-large-latest")

# API OpenAI (utilisee pour lettre + message recruteur, avec fallback Mistral)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Identifiants Welcome to the Jungle
WTTJ_EMAIL = os.getenv("WTTJ_EMAIL", "")
WTTJ_PASSWORD = os.getenv("WTTJ_PASSWORD", "")
WTTJ_MANUAL_LOGIN = _env_bool("WTTJ_MANUAL_LOGIN", True)
VIE_MANUAL_LOGIN = _env_bool("VIE_MANUAL_LOGIN", True)

# Infos personnelles
PRENOM = os.getenv("PRENOM", "")
NOM = os.getenv("NOM", "")
EMAIL = os.getenv("EMAIL", "")
TELEPHONE = os.getenv("TELEPHONE", "")
LINKEDIN = os.getenv("LINKEDIN", "")
PORTFOLIO = os.getenv("PORTFOLIO", "")

# Candidature
DISPONIBILITE = os.getenv(
    "DISPONIBILITE",
    "Disponible immediatement pour tout entretien, aux horaires qui vous conviennent.",
)
TYPE_CONTRAT = os.getenv("TYPE_CONTRAT", "CDI")
CV_CONTEXT_HINTS = os.getenv("CV_CONTEXT_HINTS", "")
CV_PATH = os.getenv("CV_PATH", "cv.pdf")
CV_PATH_PPTX = os.getenv("CV_PATH_PPTX", "template.pptx")
CV_MODE = os.getenv("CV_MODE", "direct")  # direct, pptx, html
PRIMARY_LLM = os.getenv("PRIMARY_LLM", "mistral")  # mistral, openai

# Paramètres du bot
MAX_PAGES = _env_int("MAX_PAGES", 15)
MAX_OFFRES = _env_nullable_int("MAX_OFFRES", 100)
POSTE_ACTUEL_FORCE = os.getenv("POSTE_ACTUEL_FORCE", "")
DELAI_ENTRE_CANDIDATURES = _env_int("DELAI_ENTRE_CANDIDATURES", 10)
SHOW_BROWSER = _env_bool("SHOW_BROWSER", True)
LOG_FILE = os.getenv("LOG_FILE", "candidatures.json")

# Paramètres du Générateur CV Dynamique
import json
def _env_dict(name: str):
    val = os.getenv(name, "{}")
    try:
        return json.loads(val)
    except:
        return {}

CV_BULLET_LIMITS = _env_dict("CV_BULLET_LIMITS")
