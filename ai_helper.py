from mistralai import Mistral
import re
import config


_client = None


def get_client():
    global _client
    if _client is None:
        _client = Mistral(api_key=config.MISTRAL_API_KEY)
    return _client


def _call_mistral(prompt: str, max_tokens: int = 1024) -> str:
    """Appel generique a l'API Mistral."""
    response = get_client().chat.complete(
        model=config.MISTRAL_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


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
    texte = texte.replace(" – ", ", ")
    texte = texte.replace(" — ", ", ")
    texte = texte.replace("–", ",")
    texte = texte.replace("—", ",")

    # Compactage leger
    texte = re.sub(r"\n{3,}", "\n\n", texte).strip()
    return texte


def generer_lettre_motivation(cv_texte: str, offre: dict, langue: str = "fr") -> str:
    """Genere une lettre de motivation personnalisee basee sur le CV et l'offre."""
    cv_context_hints = getattr(config, "CV_CONTEXT_HINTS", "")
    langue = (langue or "fr").strip().lower()
    est_anglais = langue.startswith("en")
    langue_prompt = "anglais" if est_anglais else "francais"
    salutation_fin = "simple professional closing line in English" if est_anglais else "formule de politesse simple"
    longueur = "180 and 280 words" if est_anglais else "180 et 280 mots"
    ton = "professional and natural tone in English" if est_anglais else "ton professionnel et naturel"

    prompt = f"""Tu es un expert en recrutement et redaction de lettres de motivation.

Voici le CV du candidat :
<cv>
{cv_texte}
</cv>

Voici l'offre d'emploi :
<offre>
Poste : {offre.get('titre', 'Non precise')}
Entreprise : {offre.get('entreprise', 'Non precisee')}
Description complete :
{offre.get('description', 'Non disponible')}
</offre>

Informations sur le candidat :
- Prenom : {config.PRENOM}
- Nom : {config.NOM}
- Disponible : {config.DISPONIBILITE}
- Type de contrat recherche : {config.TYPE_CONTRAT}
{f"- Contexte CV a prioriser : {cv_context_hints}" if cv_context_hints else ""}

Redige une lettre de motivation ultra personnalisee qui :
1. Mentionne des elements specifiques de l'offre
2. Fait des liens explicites entre l'experience du candidat et le poste
3. Utilise un {ton}
4. Fait entre {longueur}
5. Commence directement par le corps de la lettre (pas d'objet, pas d'en-tete)
6. Se termine par une {salutation_fin}
7. N'utilise jamais de placeholders entre crochets (ex: [adresse], [email], [telephone], [LinkedIn])
8. N'utilise pas les caracteres "–" ou "—" dans les phrases
9. Ecris la lettre uniquement en {langue_prompt}

Ne produis que le texte final de la lettre, rien d'autre."""

    return _nettoyer_sortie_ia(_call_mistral(prompt, max_tokens=900))


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
- Pas de placeholders entre crochets
- Pas de caracteres "–" ou "—"
- Si type_reponse = nombre: renvoyer seulement un nombre ou une fourchette courte
- Si type_reponse = choix: renvoyer seulement un choix parmi les options proposees
- Repondre uniquement en {langue_prompt}

Type de reponse attendu : {type_reponse}

Produis uniquement la reponse brute, sans introduction ni explication."""

    return _nettoyer_sortie_ia(_call_mistral(prompt, max_tokens=260))


def generer_message_recruteur(cv_texte: str, offre: dict, langue: str = "fr") -> str:
    """Genere un message court a l'attention du recruteur (distinct de la lettre)."""
    cv_context_hints = getattr(config, "CV_CONTEXT_HINTS", "")
    langue = (langue or "fr").strip().lower()
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
- Ton professionnel, naturel, direct
- Mentionner l'interet pour le poste + 1 a 2 points forts relies a l'offre
- Finir par une phrase d'ouverture pour echanger
- Pas de placeholders entre crochets
- Pas de caracteres "–" ou "—"
- {consignes_langue}

Produis uniquement le message final, sans en-tete ni signature."""

    return _nettoyer_sortie_ia(_call_mistral(prompt, max_tokens=320))
