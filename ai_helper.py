from mistralai import Mistral
import re
import os
import config

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


_mistral_client = None
_openai_client = None
_prompt_lettre_cache = None


def get_mistral_client():
    global _mistral_client
    if _mistral_client is None:
        _mistral_client = Mistral(api_key=config.MISTRAL_API_KEY)
    return _mistral_client


def get_openai_client():
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    if not getattr(config, "OPENAI_API_KEY", "").strip():
        return None
    if OpenAI is None:
        return None
    _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _openai_client


def _call_mistral(prompt: str, max_tokens: int = 1024) -> str:
    """Appel generique a l'API Mistral."""
    response = get_mistral_client().chat.complete(
        model=config.MISTRAL_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


def _call_openai(prompt: str, max_tokens: int = 1024) -> str:
    """Appel generique a l'API OpenAI."""
    client = get_openai_client()
    if client is None:
        raise RuntimeError("OpenAI indisponible (cle absente ou SDK non installe).")

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content or ""
    return content.strip()


def _call_openai_with_mistral_fallback(prompt: str, max_tokens: int) -> str:
    """Essaie OpenAI, puis fallback sur Mistral en cas d'indisponibilite/erreur."""
    try:
        texte = _call_openai(prompt, max_tokens=max_tokens)
        if texte and texte.strip():
            return texte
    except Exception:
        pass
    return _call_mistral(prompt, max_tokens=max_tokens)


def _nettoyer_sortie_ia(texte: str) -> str:
    """Nettoie les artefacts frequents des sorties IA."""
    if not texte:
        return texte

    # Supprime les placeholders du type [Votre adresse], [LinkedIn], etc.
    lignes = []
    for ligne in texte.splitlines():
        if re.search(r"\[[^\]]{2,80}\]", ligne):
            continue
        lignes.append(ligne)
    texte = "\n".join(lignes)

    # Evite les tirets longs dans les phrases (style trop IA)
    texte = texte.replace(" \u2013 ", ", ")
    texte = texte.replace(" \u2014 ", ", ")
    texte = texte.replace("\u2013", ",")
    texte = texte.replace("\u2014", ",")

    # Compactage leger
    texte = re.sub(r"\n{3,}", "\n\n", texte).strip()
    return texte


def _nettoyer_lettre_input_ready(texte: str) -> str:
    """Supprime en-tetes/objets/signatures pour une lettre directement collable en textarea."""
    if not texte:
        return texte

    lignes = [l.strip() for l in texte.splitlines()]
    nettoyees = []
    for i, ligne in enumerate(lignes):
        low = ligne.lower()
        if not ligne:
            nettoyees.append("")
            continue
        if i < 12:
            if "@" in ligne:
                continue
            if re.search(r"\b(tel|téléphone|telephone|phone|mail|email)\b", low):
                continue
            if re.search(r"\b(objet|subject)\b\s*:", low):
                continue
            if "a l'attention" in low or "à l’attention" in low:
                continue
            if re.search(r"\b(paris|lyon|marseille|france)\b.*,?\s+le\s+", low):
                continue
            mots = ligne.split()
            if 2 <= len(mots) <= 3 and all(re.fullmatch(r"[A-Za-zÀ-ÿ']{2,20}", m) for m in mots):
                # Evite les lignes "Vincent Ducastel" en tete
                continue
        nettoyees.append(ligne)

    texte = "\n".join(nettoyees).strip()
    texte = re.sub(r"^(madame,\s*monsieur,?\s*)", "", texte, flags=re.IGNORECASE)
    texte = re.sub(r"^\s*(cordialement|sincerely|best regards)[\s,:\n]*.*$", "", texte, flags=re.IGNORECASE | re.DOTALL)
    texte = re.sub(r"\n{3,}", "\n\n", texte).strip()
    return texte


def _nettoyer_reponse_question(texte: str, type_reponse: str, langue: str) -> str:
    """Verrouille le format des reponses pour eviter les derives de type lettre."""
    texte = (texte or "").strip()
    if not texte:
        return texte

    lignes = []
    for l in texte.splitlines():
        ll = l.strip()
        if not ll:
            continue
        low = ll.lower()
        if "@" in ll:
            continue
        if re.search(r"\b(tel|téléphone|telephone|phone|mail|email|cordialement|sincerely|best regards|objet)\b", low):
            continue
        if "a l'attention" in low or "à l’attention" in low:
            continue
        lignes.append(ll)
    texte = " ".join(lignes).strip()

    if type_reponse == "oui_non":
        lower = texte.lower()
        yes = ["yes", "oui", "absolutely", "certainly"]
        no = ["no", "non"]
        is_yes = any(re.search(rf"\b{w}\b", lower) for w in yes)
        is_no = any(re.search(rf"\b{w}\b", lower) for w in no)
        if is_yes and not is_no:
            return "Yes." if langue.startswith("en") else "Oui."
        if is_no and not is_yes:
            return "No." if langue.startswith("en") else "Non."
        return "Yes." if langue.startswith("en") else "Oui."

    # Evite les textes trop longs dans les champs question
    if len(texte) > 320:
        texte = texte[:320].rsplit(" ", 1)[0].strip() + "..."
    return texte


def _titre_tokens_significatifs(titre: str) -> list[str]:
    raw = re.findall(r"[A-Za-z0-9]+", (titre or "").lower())
    stop = {"h", "f", "hf", "de", "du", "des", "the", "of", "and", "cdi", "cdd", "job"}
    return [t for t in raw if len(t) > 2 and t not in stop]


def _lettre_bien_ciblee(texte: str, offre: dict) -> bool:
    low = (texte or "").lower()
    entreprise = (offre.get("entreprise") or "").strip()
    titre = (offre.get("titre") or "").strip()

    if entreprise and entreprise.lower() not in {"non precisee", "unknown"}:
        if entreprise.lower() not in low:
            return False

    if titre and titre.lower() != "non precise":
        tokens = _titre_tokens_significatifs(titre)
        if tokens:
            hits = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", low))
            # Au moins 2 tokens (ou 1 si titre tres court)
            seuil = 1 if len(tokens) <= 2 else 2
            if hits < seuil:
                return False

    # Evite un ciblage explicite vers une autre entreprise.
    m = re.search(r"\b(rejoindre|integrer|intégrer|join)\s+([A-Za-z0-9&' .-]{2,80})", texte, flags=re.IGNORECASE)
    if m and entreprise:
        cible = m.group(2).strip().lower()
        if entreprise.lower() not in cible:
            return False
    return True


def _langue_offre_depuis_contenu(offre: dict, langue_hint: str = "fr") -> str:
    """Detecte la langue attendue (fr/en) depuis le contenu de l'offre."""
    hint = (langue_hint or "fr").strip().lower()
    titre = (offre.get("titre") or "").lower()
    desc = (offre.get("description") or "").lower()
    texte = f"{titre}\n{desc}"
    if not texte.strip():
        return "en" if hint.startswith("en") else "fr"

    marqueurs_en = [
        "job description", "key responsibilities", "you will", "we are looking",
        "quality", "automation", "engineer", "performance", "pipeline", "microservice",
        "product owners", "ci/cd", "framework", "stakeholders", "temporary work agencies",
    ]
    marqueurs_fr = [
        "description du poste", "vos missions", "vous jouerez", "nous recherchons",
        "qualite", "qualité", "automatisation", "ingénieur", "ingenieur", "équipe", "équipe",
        "candidature", "poste", "entreprise",
    ]
    score_en = sum(1 for m in marqueurs_en if m in texte)
    score_fr = sum(1 for m in marqueurs_fr if m in texte)
    accents_fr = len(re.findall(r"[éèêàùâîôç]", texte))
    if accents_fr >= 8:
        score_fr += 2

    if score_en > score_fr:
        return "en"
    if score_fr > score_en:
        return "fr"
    return "en" if hint.startswith("en") else "fr"


def _texte_ressemble_anglais(texte: str) -> bool:
    t = (texte or "").lower()
    marqueurs = [" the ", " and ", " with ", " for ", " you ", " your ", " role ", " team "]
    return sum(1 for m in marqueurs if m in f" {t} ") >= 2


def _charger_template_prompt_lettre() -> str:
    """Charge le template de prompt lettre depuis prompts/lettre_motivation_prompt.txt."""
    global _prompt_lettre_cache
    if _prompt_lettre_cache is not None:
        return _prompt_lettre_cache

    chemin = os.path.join(os.path.dirname(__file__), "prompts", "lettre_motivation_prompt.txt")
    with open(chemin, "r", encoding="utf-8") as f:
        _prompt_lettre_cache = f.read().strip()
    return _prompt_lettre_cache


def generer_lettre_motivation(cv_texte: str, offre: dict, langue: str = "fr") -> str:
    """Genere une lettre de motivation via OpenAI (fallback Mistral)."""
    cv_context_hints = getattr(config, "CV_CONTEXT_HINTS", "")
    langue = _langue_offre_depuis_contenu(offre, langue_hint=langue)
    est_anglais = langue.startswith("en")
    langue_prompt = "anglais" if est_anglais else "francais"
    salutation_fin = "dynamic closing line in English without flattery" if est_anglais else "conclusion dynamique sans flatterie"
    longueur = "250 and 350 words" if est_anglais else "250 et 350 mots"
    ton = (
        "audacious, modern, confident and results-oriented tone in English"
        if est_anglais
        else "ton audacieux, moderne, confiant et oriente resultats"
    )

    prompt_template = _charger_template_prompt_lettre()
    prompt = prompt_template.format(
        cv_texte=cv_texte,
        offre_titre=offre.get("titre", "Non precise"),
        offre_entreprise=offre.get("entreprise", "Non precisee"),
        offre_description=offre.get("description", "Non disponible"),
        prenom=config.PRENOM,
        nom=config.NOM,
        disponibilite=config.DISPONIBILITE,
        type_contrat=config.TYPE_CONTRAT,
        cv_context_line=f"- Contexte CV a prioriser : {cv_context_hints}" if cv_context_hints else "",
        ton=ton,
        longueur=longueur,
        salutation_fin=salutation_fin,
        langue_prompt=langue_prompt,
    )

    texte = _nettoyer_sortie_ia(_call_openai_with_mistral_fallback(prompt, max_tokens=900))
    texte = _nettoyer_lettre_input_ready(texte)
    langue_ok = _texte_ressemble_anglais(texte) if est_anglais else (not _texte_ressemble_anglais(texte))
    if _lettre_bien_ciblee(texte, offre) and langue_ok:
        return texte

    # Retry guide si le premier jet est hors-cible.
    prompt_retry = f"""{prompt}

IMPORTANT: Le brouillon precedent etait hors-cible.
- Entreprise cible obligatoire: {offre.get('entreprise', 'Non precisee')}
- Poste cible obligatoire: {offre.get('titre', 'Non precise')}
- Interdiction absolue de cibler une autre entreprise (ex: AXA, Helpline, TSN, etc.) comme employeur final.

Regenere une nouvelle version strictement ciblee sur cette offre."""
    texte2 = _nettoyer_sortie_ia(_call_openai_with_mistral_fallback(prompt_retry, max_tokens=900))
    texte2 = _nettoyer_lettre_input_ready(texte2)
    langue_ok_2 = _texte_ressemble_anglais(texte2) if est_anglais else (not _texte_ressemble_anglais(texte2))
    if _lettre_bien_ciblee(texte2, offre) and langue_ok_2:
        return texte2

    # Dernier garde-fou pour garantir le ciblage minimal.
    if est_anglais:
        prefix = (
            f"I am applying for the {offre.get('titre', 'role')} role at "
            f"{offre.get('entreprise', 'your company')}."
        )
    else:
        entreprise_cible = offre.get("entreprise", "l'entreprise cible")
        prefix = (
            f"Je candidate au poste {offre.get('titre', 'vise')} chez "
            f"{entreprise_cible}."
        )
    texte2 = re.sub(r"\s+", " ", texte2).strip()
    if not texte2:
        return prefix
    if prefix.lower() in texte2.lower():
        return texte2
    return f"{prefix}\n\n{texte2}"


def repondre_question(
    cv_texte: str,
    offre: dict,
    question: str,
    type_reponse: str = "texte",
    langue: str = "fr",
) -> str:
    """Repond a une question supplementaire du formulaire de candidature."""
    cv_context_hints = getattr(config, "CV_CONTEXT_HINTS", "")
    langue = (langue or "fr").strip().lower()
    langue_prompt = "anglais" if langue.startswith("en") else "francais"

    consigne_type = "- Si type_reponse = texte: repondre en 1 a 3 phrases courtes (max 60 mots)."
    if type_reponse == "nombre":
        consigne_type = "- Si type_reponse = nombre: renvoyer seulement un nombre ou une fourchette courte."
    elif type_reponse == "choix":
        consigne_type = "- Si type_reponse = choix: renvoyer seulement un choix parmi les options proposees."
    elif type_reponse == "oui_non":
        consigne_type = (
            "- Si type_reponse = oui_non: repondre par 'Yes'/'No' (ou 'Oui'/'Non' selon la langue) "
            "et ajouter au plus une phrase de justification tres courte."
        )

    prompt = f"""Tu es le candidat {config.PRENOM} {config.NOM} qui postule pour un poste.

Voici ton CV :
<cv>
{cv_texte}
</cv>

Offre ciblee :
- Poste : {offre.get('titre', 'Non precise')}
- Entreprise : {offre.get('entreprise', 'Non precisee')}
{f"- Contexte CV a prioriser : {cv_context_hints}" if cv_context_hints else ""}

Question du recruteur :
\"{question}\"

Contraintes :
- Reponse concise, naturelle, credibe, coherente avec le CV
- Repond uniquement a la question posee, sans introduction
- Interdit de rediger une lettre de motivation, en-tete, signature, date ou coordonnees
- Pas de placeholders entre crochets
- Pas de tirets longs
- {consigne_type}
- Repondre uniquement en {langue_prompt}

Type de reponse attendu : {type_reponse}

Produis uniquement la reponse brute, sans introduction ni explication."""

    texte = _nettoyer_sortie_ia(_call_mistral(prompt, max_tokens=260))
    return _nettoyer_reponse_question(texte, type_reponse=type_reponse, langue=langue)


def generer_message_recruteur(cv_texte: str, offre: dict, langue: str = "fr") -> str:
    """Genere un message recruteur via OpenAI (fallback Mistral)."""
    cv_context_hints = getattr(config, "CV_CONTEXT_HINTS", "")
    langue = _langue_offre_depuis_contenu(offre, langue_hint=langue)
    est_anglais = langue.startswith("en")

    consignes_langue = (
        "Write only in English, 70 to 120 words."
        if est_anglais
        else "Ecris uniquement en francais, 70 a 120 mots."
    )

    prompt = f"""Tu es le candidat {config.PRENOM} {config.NOM}. Tu rediges un message court au recruteur.

Voici ton CV :
<cv>
{cv_texte}
</cv>

Voici l'offre :
<offre>
Poste : {offre.get('titre', 'Non precise')}
Entreprise : {offre.get('entreprise', 'Non precisee')}
Description :
{offre.get('description', 'Non disponible')}
</offre>

Informations utiles :
- Disponibilite : {config.DISPONIBILITE}
- Type de contrat recherche : {config.TYPE_CONTRAT}
{f"- Contexte CV a prioriser : {cv_context_hints}" if cv_context_hints else ""}

Contraintes strictes :
- Ce texte est un message d'accompagnement, pas une lettre de motivation complete
- Ton audacieux, professionnel, naturel et direct
- Mentionner l'interet pour le poste + 1 a 2 points forts relies a l'offre
- Finir par une phrase d'ouverture pour echanger
- Pas de placeholders entre crochets
- Pas de tirets longs
- Parler strictement a la premiere personne du singulier ("je", "mon", "mes")
- Ne jamais utiliser une formule du type "votre profil"
- Ne jamais mentionner Talaryo
- {consignes_langue}

Produis uniquement le message final, sans en-tete ni signature."""

    return _nettoyer_sortie_ia(_call_openai_with_mistral_fallback(prompt, max_tokens=320))



