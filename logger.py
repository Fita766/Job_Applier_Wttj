"""Logger pour suivre les candidatures envoyees."""
import json
import os
import unicodedata
from datetime import datetime

import config


def charger_log() -> dict:
    if os.path.exists(config.LOG_FILE):
        with open(config.LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "candidatures" not in data:
                data["candidatures"] = []
            if "ignorees" not in data:
                data["ignorees"] = []
            return data
    return {"candidatures": [], "ignorees": []}


def sauvegarder_log(data: dict):
    with open(config.LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def deja_postule(url: str) -> bool:
    data = charger_log()
    urls_postulees = [c.get("url", "") for c in data["candidatures"]]
    # On bloque uniquement les offres deja envoyees.
    # Les offres ignorees/erreur doivent pouvoir etre retentees aux runs suivants.
    return url in urls_postulees


def _normaliser_statut(statut: str) -> str:
    s = (statut or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    if s in {"envoyee", "envoye", "sent"}:
        return "envoyee"
    if s in {"ignoree", "ignore", "ignored"}:
        return "ignoree"
    if s in {"erreur", "error"}:
        return "erreur"
    return "ignoree"


def log_candidature(url: str, titre: str, entreprise: str, statut: str, notes: str = ""):
    """
    statut attendu: "envoyee" | "ignoree" | "erreur"
    Les variantes accentuees sont normalisees automatiquement.
    """
    data = charger_log()
    statut_normalise = _normaliser_statut(statut)

    entree = {
        "url": url,
        "titre": titre,
        "entreprise": entreprise,
        "date": datetime.now().isoformat(),
        "statut": statut_normalise,
        "notes": notes,
    }

    if statut_normalise == "envoyee":
        data["candidatures"].append(entree)
        print(f"  [OK] Candidature envoyee : {titre} @ {entreprise}")
    else:
        data["ignorees"].append(entree)
        print(f"  [INFO] Ignoree ({notes}) : {titre} @ {entreprise}")

    sauvegarder_log(data)


def afficher_stats():
    data = charger_log()
    total_envoyees = len(data["candidatures"])
    total_ignorees = len(data["ignorees"])
    print(f"\n[STATS] {total_envoyees} candidature(s) envoyee(s), {total_ignorees} ignoree(s)")
    if data["candidatures"]:
        print("\n[INFO] Dernieres candidatures :")
        for c in data["candidatures"][-5:]:
            print(f"   - {c.get('titre', '?')} @ {c.get('entreprise', '?')} ({c.get('date', '')[:10]})")
