"""
ðŸ¤– Welcome to the Jungle - Bot de candidature automatique
=========================================================
Utilisation :
    python main.py "https://www.welcometothejungle.com/fr/jobs?query=marketing&..."

Le bot va :
1. RÃ©cupÃ©rer toutes les offres de la recherche (avec pagination)
2. Pour chaque offre, cliquer sur Apply
3. Si Ã§a ouvre une popup WTTJ â†’ remplir le formulaire + lettre perso gÃ©nÃ©rÃ©e par Claude
4. Si Ã§a redirige ailleurs â†’ ignorer l'offre
"""

import sys
import time
import re
import os
from datetime import datetime
from urllib.parse import urlparse, unquote, parse_qs, urlencode, urlunparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import config
from cv_reader import lire_cv
from ai_helper import generer_lettre_motivation, repondre_question, generer_message_recruteur
from logger import deja_postule, log_candidature, afficher_stats


def detecter_plateforme(url: str) -> str:
    """Determine la plateforme de recherche depuis l'URL."""
    host = (urlparse(url).netloc or "").lower()
    if "welcometothejungle.com" in host:
        return "wttj"
    if "mon-vie-via.businessfrance.fr" in host:
        return "vie"
    return "inconnue"


def detecter_langue_offre(offre: dict) -> str:
    """Heuristique simple pour choisir fr/en selon l'offre."""
    titre = (offre.get("titre", "") or "").lower()
    texte = f"{titre}\n{offre.get('description', '')}".lower()
    if not texte.strip():
        return "fr"

    tokens_titre = re.findall(r"[a-zA-Z]+", titre)
    mots_en_titre = {
        "manager", "project", "sales", "business", "account", "engineer",
        "developer", "analyst", "officer", "specialist", "assistant",
        "coordinator", "lead", "marketing", "hr",
    }
    mots_fr_titre = {
        "charge", "chargé", "responsable", "ingenieur", "ingénieur",
        "commercial", "developpement", "développement", "assistant",
    }
    score_titre_en = sum(1 for t in tokens_titre if t.lower() in mots_en_titre)
    score_titre_fr = sum(1 for t in tokens_titre if t.lower() in mots_fr_titre)
    if score_titre_en >= 2 and score_titre_en > score_titre_fr:
        return "en"

    marqueurs_en = [
        "job description", "key responsibilities", "required skills", "english",
        "project manager", "business development", "apply", "thank you", "position",
    ]
    marqueurs_fr = [
        "description du poste", "missions", "profil recherche", "competences",
        "poste", "candidature", "francais", "merci", "responsabilites",
    ]
    accents_fr = len(re.findall(r"[éèêàùâîôç]", texte))
    score_en = sum(1 for m in marqueurs_en if m in texte)
    score_fr = sum(1 for m in marqueurs_fr if m in texte) + (1 if accents_fr >= 5 else 0)
    return "en" if score_en > score_fr else "fr"


def page_demande_connexion_ou_compte(target) -> bool:
    """Detecte les pages qui exigent login/inscription."""
    try:
        url = (target.url or "").lower()
    except Exception:
        url = ""

    if any(k in url for k in ["login", "signin", "auth", "register", "inscription", "connexion"]):
        return True

    try:
        body = target.inner_text("body").lower()
    except Exception:
        body = ""

    marqueurs = [
        "se connecter",
        "connexion",
        "inscription",
        "créer un compte",
        "creer un compte",
        "sign in",
        "log in",
        "create account",
        "register",
    ]
    return any(m in body for m in marqueurs)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  SCRAPING DES OFFRES
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def accepter_cookies(page):
    """Accepte la banniÃ¨re de cookies si elle apparaÃ®t."""
    selecteurs_cookies = [
        'button:has-text("Accepter")',
        'button:has-text("Tout accepter")',
        'button:has-text("Accept")',
        'button:has-text("Accept all")',
        'button[id*="accept"]',
        'button[class*="accept"]',
        '#onetrust-accept-btn-handler',
        '[data-testid="cookie-accept"]',
    ]
    for sel in selecteurs_cookies:
        try:
            btn = page.wait_for_selector(sel, timeout=3000, state="visible")
            if btn:
                btn.click()
                print("  ðŸª Cookies acceptÃ©s")
                time.sleep(1)
                return
        except Exception:
            continue


def se_connecter_wttj(page, context):
    """Se connecte a WTTJ avec email + mot de passe (ou mode manuel)."""
    manual_login = getattr(config, "WTTJ_MANUAL_LOGIN", False)

    def est_page_connexion():
        url = page.url.lower()
        return "signin" in url or "login" in url

    def attendre_connexion_manuelle():
        print("  [ACTION] Connecte-toi manuellement dans la fenetre du navigateur.")
        print("  [ACTION] Une fois connecte, reviens ici et appuie sur Entree.")

        try:
            input("  Appuie sur Entree pour continuer... ")
        except EOFError:
            time.sleep(1)

        # Certains flows gardent l'URL /signin meme apres login.
        # On force une navigation vers les jobs pour verifier.
        try:
            page.goto("https://www.welcometothejungle.com/fr/jobs", wait_until="domcontentloaded")
            time.sleep(2)
        except Exception:
            pass

        if est_page_connexion():
            print("  Toujours detecte sur une page de connexion.")
            print("  Si tu es bien connecte, appuie encore sur Entree pour continuer quand meme.")
            try:
                input("  Continuer quand meme... ")
            except EOFError:
                time.sleep(1)
            return

        print("  Connexion manuelle detectee")
        return

    print("Connexion a Welcome to the Jungle...")
    page.goto("https://www.welcometothejungle.com/fr/signin", wait_until="domcontentloaded")
    time.sleep(2)
    accepter_cookies(page)
    time.sleep(1)

    if manual_login:
        attendre_connexion_manuelle()
        return

    if not config.WTTJ_EMAIL or not config.WTTJ_PASSWORD:
        print("WTTJ_EMAIL / WTTJ_PASSWORD manquants dans les variables d'environnement (.env)")
        print("Active WTTJ_MANUAL_LOGIN=true pour te connecter manuellement.")
        sys.exit(1)

    # Email
    for sel in ['input[name="email"]', 'input[type="email"]']:
        try:
            el = page.wait_for_selector(sel, timeout=4000, state="visible")
            if el:
                el.fill(config.WTTJ_EMAIL)
                break
        except Exception:
            continue

    # Mot de passe
    for sel in ['input[name="password"]', 'input[type="password"]']:
        try:
            el = page.wait_for_selector(sel, timeout=4000, state="visible")
            if el:
                el.fill(config.WTTJ_PASSWORD)
                break
        except Exception:
            continue

    # Submit
    for sel in ['button[type="submit"]', 'button:has-text("Se connecter")', 'button:has-text("Connexion")']:
        try:
            btn = page.wait_for_selector(sel, timeout=4000, state="visible")
            if btn:
                btn.click()
                break
        except Exception:
            continue

    time.sleep(3)

    if est_page_connexion():
        print("Connexion auto echouee.")
        print("Tu peux finir la connexion manuellement puis appuyer sur Entree.")
        attendre_connexion_manuelle()
    else:
        print(f"Connecte en tant que {config.WTTJ_EMAIL}")


def se_connecter_vie(page):
    """Connexion manuelle au portail VIE avant de postuler (confirmation utilisateur obligatoire)."""

    print("Connexion au portail VIE (manuelle)...")
    page.goto("https://mon-vie-via.businessfrance.fr/offres", wait_until="domcontentloaded")
    time.sleep(2)
    accepter_cookies(page)
    time.sleep(1)

    print("  [ACTION] Si besoin, connecte-toi manuellement au site VIE dans le navigateur.")
    print("  [ACTION] Le bot ne fait plus de detection automatique de connexion.")

    while True:
        try:
            rep = input("  Es-tu connecte au portail VIE ? (oui/non): ").strip().lower()
        except EOFError:
            rep = "non"

        if rep in {"oui", "o", "yes", "y"}:
            print("  Connexion VIE confirmee par l'utilisateur")
            return
        if rep in {"non", "n", "no"}:
            try:
                input("  Connecte-toi puis appuie sur Entree pour repondre a nouveau... ")
            except EOFError:
                time.sleep(1)
            continue
        print("  Reponse invalide. Tape 'oui' ou 'non'.")


def extraire_offres_page(page):
    """Extrait les liens des offres sur la page de recherche actuelle."""
    offres = []

    # Attendre que les cartes d'offres chargent
    try:
        page.wait_for_selector('[data-testid="job-card"], article[class*="job"], a[href*="/jobs/"]', timeout=10000)
    except PlaywrightTimeoutError:
        print("  Aucune offre trouvee sur cette page")
        return offres

    # Recuperer tous les liens vers des offres
    liens = page.eval_on_selector_all(
        'a[href*="/fr/companies/"][href*="/jobs/"], a[href*="/jobs/"][href*="welcometothejungle"]',
        """elements => elements.map(el => ({
            href: el.href,
            texte: el.innerText.trim().substring(0, 100)
        }))"""
    )

    # Fallback : chercher tous les liens d'offres
    if not liens:
        liens = page.eval_on_selector_all(
            'a[href*="/fr/companies/"]',
            """elements => elements
                .filter(el => el.href.includes('/jobs/'))
                .map(el => ({href: el.href, texte: el.innerText.trim().substring(0, 100)}))"""
        )

    # Dedupliquer
    vus = set()
    for lien in liens:
        url = lien["href"].split("?")[0]  # Enlever les query params
        if url not in vus and "/jobs/" in url:
            vus.add(url)
            offres.append({"url": url})

    return offres


def extraire_offres_page_vie(page):
    """Extrait les liens d'offres VIE visibles sur la page."""
    offres = []
    liens = []
    for _ in range(6):
        try:
            liens = page.eval_on_selector_all(
                'a[href*="/offres/"]',
                """elements => elements
                    .map(el => el.href)
                    .filter(href => /\\/offres\\/\\d+/.test(href))"""
            )
        except Exception:
            liens = []

        if liens:
            break
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        time.sleep(1.3)

    if not liens:
        print("  Aucune offre VIE visible")
        return offres

    vus = set()
    for href in liens:
        url = href.split("?")[0]
        if url not in vus:
            vus.add(url)
            offres.append({"url": url})
    return offres


def _construire_url_page(url_recherche: str, page_num: int) -> str:
    """Construit l'URL de recherche en forçant le paramètre page."""
    parsed = urlparse(url_recherche)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page"] = [str(page_num)]
    nouvelle_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=nouvelle_query))


def recuperer_toutes_offres(page, url_recherche: str, max_offres=None, max_pages=3) -> list[dict]:
    """Navigue sur toutes les pages de rÃ©sultats et collecte les offres."""
    print(f"\nðŸ” RÃ©cupÃ©ration des offres depuis :\n   {url_recherche}\n")
    toutes_offres = []
    page_num = 1
    urls_vues = set()

    while True:
        if max_pages is not None and page_num > max_pages:
            print(f"  âš‘ï¸  Limite de pages atteinte ({max_pages})")
            break

        url_courante = _construire_url_page(url_recherche, page_num)
        print(f"  ðŸ“„ Page {page_num}...")
        page.goto(url_courante, wait_until="domcontentloaded")
        time.sleep(2)
        
        # Scroll pour charger le contenu lazy
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
        
        offres = extraire_offres_page(page)
        if not offres:
            print("     â†’ aucune offre sur cette page, arrÃªt de la pagination")
            break

        nouvelles = [o for o in offres if o["url"] not in urls_vues]
        toutes_offres.extend(nouvelles)
        urls_vues.update(o["url"] for o in nouvelles)
        print(f"     â†’ {len(nouvelles)} nouvelles offres trouvÃ©es (total : {len(toutes_offres)})")

        if max_offres and len(toutes_offres) >= max_offres:
            toutes_offres = toutes_offres[:max_offres]
            break

        page_num += 1
    
    print(f"\nâœ… Total : {len(toutes_offres)} offres collectÃ©es\n")
    return toutes_offres


def recuperer_toutes_offres_vie(page, url_recherche: str, max_offres=None, max_pages=3) -> list[dict]:
    """
    Collecte les offres VIE en utilisant le bouton "Voir plus d'offres".
    max_pages correspond au nombre de vagues de chargement.
    """
    print(f"\n[SEARCH] Recuperation des offres VIE depuis :\n   {url_recherche}\n")
    # Le portail VIE peut declencher une redirection d'auth en parallele.
    # On retente proprement si la navigation est interrompue.
    nav_ok = False
    last_err = None
    for tentative in range(1, 6):
        try:
            page.goto(url_recherche, wait_until="domcontentloaded")
            nav_ok = True
            break
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if "interrupted by another navigation" in msg or "net::err_aborted" in msg:
                print(f"  [WARN] Navigation VIE interrompue (tentative {tentative}/5), nouvelle tentative...")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                time.sleep(1.5)
                continue
            raise
    if not nav_ok:
        raise RuntimeError(f"Echec navigation VIE vers la recherche apres 5 tentatives: {last_err}")
    time.sleep(2)
    accepter_cookies(page)
    time.sleep(1)

    toutes_offres = []
    urls_vues = set()
    vague = 1

    while True:
        if max_pages is not None and vague > max_pages:
            print(f"  [STOP] Limite de vagues atteinte ({max_pages})")
            break

        offres = extraire_offres_page_vie(page)
        nouvelles = [o for o in offres if o["url"] not in urls_vues]
        toutes_offres.extend(nouvelles)
        urls_vues.update(o["url"] for o in nouvelles)
        print(f"  [PAGE] Vague {vague}: +{len(nouvelles)} offres (total : {len(toutes_offres)})")

        if max_offres and len(toutes_offres) >= max_offres:
            toutes_offres = toutes_offres[:max_offres]
            break

        bouton_voir_plus = None
        for sel in [
            'button:has-text("VOIR PLUS D\'OFFRES")',
            'a:has-text("VOIR PLUS D\'OFFRES")',
            '.see-more',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    bouton_voir_plus = el
                    break
            except Exception:
                continue

        if not bouton_voir_plus:
            print("  -> plus de bouton 'Voir plus d'offres', fin de collecte")
            break

        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.6)
            bouton_voir_plus.click()
            time.sleep(2)
        except Exception:
            print("  -> impossible de charger plus d'offres, arret")
            break

        vague += 1

    print(f"\n[OK] Total : {len(toutes_offres)} offres VIE collectees\n")
    return toutes_offres


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  SCRAPING DES DETAILS D'UNE OFFRE
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def extraire_details_offre(page, url: str) -> dict:
    """Extrait le titre, l'entreprise et la description complÃ¨te d'une offre."""
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(2)
    accepter_cookies(page)
    time.sleep(1)
    
    offre = {"url": url, "titre": "", "titre_url": "", "entreprise": "", "description": ""}
    offre["titre_url"] = extraire_titre_depuis_url_offre(url)
    
    def _nettoyer_texte(s: str) -> str:
        if not s:
            return ""
        s = re.sub(r"\s+", " ", s).strip()
        # Eviter les contenus css/svg qui remontent parfois
        if "{" in s or "fill-rule" in s or "clip-rule" in s:
            return ""
        return s

    # Titre du poste
    for selector in ['[data-testid="job-title"]', 'h1[class*="title"]', ".job-title", "h1"]:
        el = page.query_selector(selector)
        if el:
            txt = _nettoyer_texte(el.inner_text())
            if txt and len(txt) >= 3:
                offre["titre"] = txt
                break
    
    # Entreprise
    for selector in ['[data-testid="company-name"]', 'a[href*="/companies/"]', '.company-name', '.w_75 h2', 'article h2']:
        el = page.query_selector(selector)
        if el:
            text = _nettoyer_texte(el.inner_text())
            if text and len(text) < 100 and not re.search(r"\([A-Z]{2}\)$", text):
                offre["entreprise"] = text
                break
    
    # Description complÃ¨te
    desc_parts = []
    for selector in [
        '[data-testid="job-description"]',
        '.job-description',
        'section[class*="description"]',
        'div[class*="content"]',
        'article',
        'main'
    ]:
        el = page.query_selector(selector)
        if el:
            desc_parts.append(el.inner_text().strip())
    
    if desc_parts:
        offre["description"] = "\n\n".join(desc_parts)[:5000]  # Limiter la taille
    else:
        # Fallback : prendre tout le texte de la page
        offre["description"] = page.inner_text("body")[:5000]
    
    return offre


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  REMPLISSAGE DU FORMULAIRE
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def remplir_champ(target, selector: str, valeur: str, timeout: int = 3000):
    """Remplit un champ de formulaire si il existe."""
    try:
        el = target.wait_for_selector(selector, timeout=timeout, state="visible")
        if el:
            el.click()
            el.fill(valeur)
            return True
    except Exception:
        pass
    return False


def extraire_titre_depuis_url_offre(url_offre: str) -> str:
    """
    Extrait un intitulé de poste depuis le slug URL.
    Exemple:
    /jobs/b2b-marketing-manager-strategie-sectorielle_begles
    -> "marketing manager strategie sectorielle b2b"
    """
    if not url_offre:
        return ""

    try:
        path = urlparse(url_offre).path
    except Exception:
        path = url_offre

    m = re.search(r"/jobs/([^/?#]+)", path)
    if not m:
        return ""

    slug = unquote(m.group(1)).strip().lower()
    if not slug:
        return ""

    # En general, la partie apres "_" correspond au lieu (ex: _begles)
    if "_" in slug:
        slug = slug.split("_", 1)[0].strip()

    titre = slug.replace("-", " ").replace("_", " ")
    titre = re.sub(r"\s+", " ", titre).strip().lower()

    # Correction simple de coquille frequente
    titre = re.sub(r"\bmaketing\b", "marketing", titre, flags=re.IGNORECASE)

    # Deplacer un prefixe business en suffixe
    m = re.match(r"^(b2b|b2c)\s+(.+)$", titre, flags=re.IGNORECASE)
    if m:
        titre = f"{m.group(2).strip()} {m.group(1).upper()}"

    return titre


def normaliser_poste_actuel(offre: dict) -> str:
    """
    Construit un intitulé propre pour le champ "Poste actuel".
    Exemple: "B2B Marketing Manager - Stratégie Sectorielle" -> "Marketing Manager B2B"
    """
    titre = (offre.get("titre_url") or offre.get("titre") or "").strip()
    if not titre:
        return "Marketing"

    titre = re.sub(r"\s+", " ", titre).strip().lower()
    titre = re.sub(r"\bmaketing\b", "marketing", titre, flags=re.IGNORECASE)
    # Retirer les précisions après séparateur (souvent équipe/verticale/localisation)
    titre = re.split(r"\s[-–|:]\s", titre, maxsplit=1)[0].strip()
    # Retirer une précision finale entre parenthèses
    titre = re.sub(r"\s*\([^)]*\)\s*$", "", titre).strip()

    # Replacer un préfixe business fréquent en suffixe
    m = re.match(r"^(B2B|B2C)\s+(.+)$", titre, flags=re.IGNORECASE)
    if m:
        titre = f"{m.group(2).strip()} {m.group(1).upper()}"

    return titre or "Marketing"


def gerer_questions_supplementaires(
    target,
    cv_texte: str,
    offre: dict,
    form_scope: str = "",
    langue: str = "fr",
):
    """DÃ©tecte et rÃ©pond aux questions supplÃ©mentaires du formulaire."""
    base = f"{form_scope} " if form_scope else ""
    questions = target.eval_on_selector_all(
        f'{base}input, {base}textarea, {base}select',
        """elements => elements.map(el => {
            const tag = el.tagName.toLowerCase();
            const type = (el.type || '').toLowerCase();
            const id = el.id || '';
            const name = el.name || '';

            // Champs invisibles / non pertinents
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || el.disabled || el.readOnly) return null;
            if (tag === 'input' && ['hidden', 'file', 'submit', 'button', 'image', 'reset'].includes(type)) return null;

            const key = `${name} ${id}`.toLowerCase();
            const known = [
                'firstname', 'lastname', 'email', 'phone', 'subtitle',
                'cover_letter', 'resume', 'portfolio', 'avatar',
                'media.linkedin', 'media.website', 'media.github', 'consent'
            ];
            if (known.some(k => key.includes(k))) return null;

            let value = '';
            if (tag === 'select') {
                value = el.value || '';
            } else if (tag === 'input' && (type === 'checkbox' || type === 'radio')) {
                value = el.checked ? 'checked' : '';
            } else {
                value = (el.value || '').trim();
            }

            // Label
            let label = '';
            if (id) {
                const lbl = document.querySelector('label[for="' + id + '"]');
                if (lbl) label = (lbl.innerText || '').trim();
            }
            if (!label) {
                const parent = el.closest('[class*="field"], [class*="question"], [class*="form-group"], [data-testid*="block"]');
                if (parent) {
                    const lbl = parent.querySelector('label, legend, [class*="label"]');
                    if (lbl) label = (lbl.innerText || '').trim();
                }
            }

            let options = [];
            if (tag === 'select') {
                options = Array.from(el.options || [])
                    .map(o => ({ value: (o.value || '').trim(), text: (o.text || '').trim() }))
                    .filter(o => o.text);
            }

            return {
                tag,
                type: type || tag,
                name,
                id,
                label,
                placeholder: el.placeholder || '',
                value,
                required: !!el.required,
                options
            };
        }).filter(Boolean)"""
    )

    for q in questions:
        if q["value"]:  # DÃ©jÃ  rempli
            continue

        label = q["label"] or q["placeholder"] or q["name"]
        if not label or len(label) < 3:
            continue

        # Ignorer les champs standards dÃ©jÃ  gÃ©rÃ©s
        champs_standards = [
            "nom", "prenom", "email", "telephone", "phone",
            "name", "surname", "first", "last",
            "cv", "resume", "portfolio", "linkedin", "github", "site", "cover letter", "lettre"
        ]
        if any(std in label.lower() for std in champs_standards):
            continue

        # Ignorer les champs de recherche/filtre hors candidature
        champs_recherche = [
            "que recherchez-vous", "que recherchez vous", "recherchez-vous", "recherchez vous",
            "recherche", "search", "keyword", "mot-cle", "mot clé", "query", "filtre", "filter",
            "localisation", "location", "pays", "metier", "métier"
        ]
        if any(k in label.lower() for k in champs_recherche):
            continue

        print(f"  ðŸ’¬ Question dÃ©tectÃ©e : {label[:80]}")

        type_reponse = "texte"
        if q["tag"] == "select":
            type_reponse = "choix"
        elif q["type"] == "number":
            type_reponse = "nombre"

        question_prompt = label
        if q["tag"] == "select" and q.get("options"):
            opts = ", ".join([o["text"] for o in q["options"] if o.get("text")])
            question_prompt = f"{label}\nChoix possibles: {opts}"

        reponse = repondre_question(
            cv_texte,
            offre,
            question_prompt,
            type_reponse=type_reponse,
            langue=langue,
        )
        print(f"     â†’ RÃ©ponse : {reponse[:100]}...")

        # Remplir le champ
        try:
            selector = None
            if q.get("name"):
                selector = f'{q["tag"]}[name="{q["name"]}"]'
            elif q.get("id"):
                selector = f'{q["tag"]}#{q["id"]}'
            if not selector:
                continue

            el = target.query_selector(selector)
            if not el:
                continue

            if q["tag"] == "select":
                options = q.get("options", [])
                # Essayer de matcher la rÃ©ponse IA Ã  une option existante.
                selected = False
                rep = reponse.strip().lower()
                for opt in options:
                    txt = (opt.get("text") or "").strip().lower()
                    val = (opt.get("value") or "").strip().lower()
                    if rep and (rep == txt or rep == val or rep in txt or txt in rep):
                        el.select_option(value=opt.get("value") or None, label=opt.get("text") or None)
                        selected = True
                        break
                if not selected:
                    for opt in options:
                        if (opt.get("value") or "").strip():
                            el.select_option(value=opt["value"])
                            selected = True
                            break
                if selected:
                    continue

            if q["tag"] == "input" and q["type"] in ("checkbox", "radio"):
                rep = reponse.strip().lower()
                if rep.startswith("oui") or rep.startswith("yes"):
                    try:
                        el.check()
                    except Exception:
                        el.click()
                    continue
                # Si pas de oui explicite, on laisse tel quel.
                continue

            el.click()
            el.fill(reponse)
        except Exception:
            pass


def remplir_formulaire_generique(target, cv_texte: str, offre: dict, cv_path: str, langue: str = "fr"):
    """Remplit un formulaire externe avec des selecteurs larges."""
    champs = [
        (config.PRENOM, ['input[name*="first" i]', 'input[id*="first" i]', 'input[placeholder*="first" i]', 'input[placeholder*="prenom" i]']),
        (config.NOM, ['input[name*="last" i]', 'input[id*="last" i]', 'input[placeholder*="last" i]', 'input[placeholder*="nom" i]']),
        (config.EMAIL, ['input[type="email"]', 'input[name*="email" i]', 'input[placeholder*="mail" i]']),
        (config.TELEPHONE, ['input[type="tel"]', 'input[name*="phone" i]', 'input[placeholder*="phone" i]', 'input[placeholder*="telephone" i]']),
    ]

    if config.LINKEDIN:
        champs.append((config.LINKEDIN, ['input[name*="linkedin" i]', 'input[placeholder*="linkedin" i]']))
    if config.PORTFOLIO:
        champs.append((config.PORTFOLIO, ['input[name*="portfolio" i]', 'input[name*="website" i]', 'input[placeholder*="website" i]']))

    for valeur, selecteurs in champs:
        for sel in selecteurs:
            remplir_champ(target, sel, valeur, timeout=1500)

    # Upload CV
    for sel in [
        'input[type="file"][name*="cv" i]',
        'input[type="file"][name*="resume" i]',
        'input[type="file"][id*="cv" i]',
        'input[type="file"][id*="resume" i]',
        'input[type="file"]',
    ]:
        try:
            el = target.query_selector(sel)
            if el and el.is_visible():
                el.set_input_files(cv_path)
                print("  [CV] Upload CV (formulaire externe)")
                break
        except Exception:
            continue

    # Lettre / message
    lettre = None
    for sel in [
        'textarea[name*="cover" i]',
        'textarea[name*="motivation" i]',
        'textarea[placeholder*="cover" i]',
        'textarea[placeholder*="motivation" i]',
    ]:
        try:
            el = target.query_selector(sel)
            if el and el.is_visible():
                if lettre is None:
                    print("  [IA] Generation de la lettre de motivation...")
                    lettre = generer_lettre_motivation(cv_texte, offre, langue=langue)
                    print(f"  [IA] Lettre generee ({len(lettre)} caracteres)")
                el.click()
                el.fill(lettre)
                print("  [OK] Lettre de motivation remplie")
                break
        except Exception:
            continue

    # Message recruteur (distinct de la lettre)
    message = None
    for sel in [
        'textarea[name="message"]',
        'textarea[name*="message" i]',
        'textarea[placeholder*="message" i]',
    ]:
        try:
            el = target.query_selector(sel)
            if el and el.is_visible():
                if message is None:
                    print("  [IA] Generation du message recruteur...")
                    message = generer_message_recruteur(cv_texte, offre, langue=langue)
                el.click()
                el.fill(message)
                print("  [OK] Message recruteur rempli")
                break
        except Exception:
            continue

    gerer_questions_supplementaires(target, cv_texte, offre, form_scope="", langue=langue)

    # Consentements requis
    try:
        checkboxes = target.query_selector_all('input[type="checkbox"][required], input[type="checkbox"][name*="consent" i]')
        for cb in checkboxes:
            try:
                if not cb.is_checked():
                    cb.check()
            except Exception:
                continue
    except Exception:
        pass


def soumettre_formulaire_generique(target) -> bool:
    """Soumet un formulaire via des selecteurs standards FR/EN."""
    selecteurs_submit = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Postuler")',
        'button:has-text("Envoyer")',
        'button:has-text("Soumettre")',
        'button:has-text("Valider")',
        'button:has-text("Apply")',
        'button:has-text("Submit")',
        'button:has-text("Send")',
        'a:has-text("Apply")',
        'a:has-text("Postuler")',
    ]
    for sel in selecteurs_submit:
        try:
            btn = target.wait_for_selector(sel, timeout=2000, state="visible")
            if btn:
                btn.click()
                print("  [OK] Formulaire soumis")
                time.sleep(3)
                return True
        except Exception:
            continue
    return False


def formulaire_candidature_detecte(target) -> bool:
    """Heuristique: verifie qu'on est sur une vraie page de candidature."""
    selecteurs_indices = [
        'input[type="file"]',
        'input[type="email"]',
        'input[type="tel"]',
        'textarea[name*="message" i]',
        'textarea[name*="cover" i]',
        'textarea[name*="motivation" i]',
        'form:has(button[type="submit"])',
        'form:has(input[type="submit"])',
    ]
    for sel in selecteurs_indices:
        try:
            el = target.query_selector(sel)
            if el and el.is_visible():
                return True
        except Exception:
            continue

    try:
        body = target.inner_text("body").lower()
    except Exception:
        body = ""

    mots = [
        "postuler", "apply", "application", "candidature",
        "cv", "resume", "cover letter", "lettre de motivation",
    ]
    return any(m in body for m in mots)


def attendre_nouvelle_page(context, pages_connues: set, timeout_ms: int = 7000):
    """Attend l'ouverture d'une nouvelle page et renvoie la plus recente."""
    fin = time.time() + (timeout_ms / 1000.0)
    while time.time() < fin:
        try:
            pages = context.pages
        except Exception:
            pages = []
        nouvelles = [p for p in pages if p not in pages_connues]
        if nouvelles:
            return nouvelles[-1]
        time.sleep(0.2)
    return None


def _slug_fichier(s: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (s or "").strip()).strip("_")
    return (s[:max_len] or "offre").lower()


def creer_fichier_temp_lettre(lettre: str, offre: dict) -> str:
    """
    Cree un fichier .txt lisible pour la lettre dans un dossier local.
    Le fichier est conserve pour verification manuelle.
    """
    dossier = os.path.join(os.getcwd(), "lettres_motivation_generees")
    os.makedirs(dossier, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    entreprise = _slug_fichier(offre.get("entreprise", "entreprise"))
    titre = _slug_fichier(offre.get("titre", "poste"))
    filename = f"lettre_motivation_{entreprise}_{titre}_{ts}.txt"
    path = os.path.join(dossier, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write((lettre or "").strip() + "\n")
    return path


def detecter_formulaire_inline_vie(page, timeout_ms: int = 8000) -> bool:
    """Detection robuste du formulaire inline VIE."""
    fin = time.time() + (timeout_ms / 1000.0)
    while time.time() < fin:
        try:
            if page.query_selector('form:has(input#motivation), form:has(input#cv-input), form:has(textarea[name="message"])'):
                return True
        except Exception:
            pass
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        time.sleep(0.8)
    return False


def remplir_formulaire_vie_inline(page, cv_texte: str, offre: dict, cv_path: str, langue: str = "fr") -> tuple[bool, str]:
    """
    Remplit le formulaire inline VIE:
    - ne touche pas nom/prenom/email (souvent pre-remplis)
    - upload CV
    - genere une lettre, cree un fichier temporaire, upload ce fichier
    - remplit message recruteur separe
    """
    form = None
    for sel in [
        'form:has(input#motivation)',
        'form:has(input#cv-input)',
        'form:has(textarea[name="message"])',
    ]:
        try:
            form = page.wait_for_selector(sel, timeout=4000, state="visible")
            if form:
                break
        except Exception:
            continue

    if not form:
        return False, ""

    # CV obligatoire
    try:
        cv_input = page.query_selector('input#cv-input, input[type="file"]#cv-input')
        if cv_input:
            cv_input.set_input_files(cv_path)
            print("  [CV] Upload CV (formulaire inline VIE)")
    except Exception:
        pass

    lettre_path = ""
    try:
        print("  [IA] Generation de la lettre de motivation (fichier)...")
        lettre = generer_lettre_motivation(cv_texte, offre, langue=langue)
        lettre_path = creer_fichier_temp_lettre(lettre, offre)
        motivation_input = page.query_selector('input#motivation, input[type="file"]#motivation')
        if motivation_input:
            motivation_input.set_input_files(lettre_path)
            print(f"  [OK] Fichier lettre de motivation upload: {lettre_path}")
        else:
            print("  [WARN] Champ fichier lettre (#motivation) introuvable")
    except Exception as e:
        print(f"  [WARN] Echec generation/upload lettre: {e}")

    # Message recruteur (obligatoire)
    message_rempli = False
    try:
        message = generer_message_recruteur(cv_texte, offre, langue=langue)
        for sel in ['textarea[name="message"]', 'textarea[placeholder*="message" i]']:
            ta = page.query_selector(sel)
            if ta and ta.is_visible():
                ta.click()
                ta.fill(message)
                message_rempli = True
                print("  [OK] Message recruteur rempli")
                break
    except Exception as e:
        print(f"  [WARN] Echec message recruteur: {e}")

    return message_rempli, lettre_path


def postuler_offre_vie(page, offre: dict, cv_texte: str, cv_path: str, langue: str = "fr") -> bool:
    """
    Mode VIE: on continue la candidature meme en sortie du domaine d'origine,
    sauf si une connexion/inscription est demandee.
    """
    url = offre["url"]
    titre = offre.get("titre", "Inconnu")
    entreprise = offre.get("entreprise", "Inconnue")
    print(f"\n[JOB] Traitement VIE : {titre} @ {entreprise}")
    print(f"   URL : {url}")

    bouton_apply = None
    for sel in [
        'a.btn.btn_bleu_vert:has-text("Postuler")',
        'a:has-text("POSTULER")',
        'button:has-text("POSTULER")',
        'a:has-text("Apply")',
        'button:has-text("Apply")',
    ]:
        try:
            el = page.wait_for_selector(sel, timeout=4000, state="visible")
            if el:
                bouton_apply = el
                break
        except Exception:
            continue

    if not bouton_apply:
        print("  [WARN] Bouton POSTULER introuvable")
        log_candidature(url, titre, entreprise, "ignoree", "bouton postuler introuvable")
        return False

    url_avant = page.url
    pages_avant_apply = set(page.context.pages)
    page_externe = None
    try:
        bouton_apply.click(force=True)
    except Exception:
        try:
            bouton_apply.click()
        except Exception:
            pass
    time.sleep(2)
    page_externe = attendre_nouvelle_page(page.context, pages_avant_apply, timeout_ms=9000)

    cible = page
    if page_externe is not None:
        try:
            page_externe.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        cible = page_externe
        print(f"  [INFO] Redirection detectee vers : {cible.url[:90]}")
    elif page.url != url_avant:
        print(f"  [INFO] Navigation apres clic : {page.url[:90]}")
    else:
        # Cas inline VIE: le clic peut seulement scroller vers la section formulaire.
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)
            page.wait_for_selector(
                'form:has(input#motivation), form:has(textarea[name="message"])',
                timeout=3500,
                state="visible",
            )
        except Exception:
            pass

    if page_demande_connexion_ou_compte(cible):
        print("  [SKIP] Connexion/inscription requise, offre ignoree")
        log_candidature(url, titre, entreprise, "ignoree", "connexion/compte requis")
        try:
            if page_externe is not None:
                page_externe.close()
        except Exception:
            pass
        return False

    lettre_temp_path = ""
    url_avant_submit = ""
    soumis = False
    max_sauts_tabs = 3
    for etape in range(max_sauts_tabs):
        if page_demande_connexion_ou_compte(cible):
            print("  [SKIP] Connexion/inscription requise sur la page cible, offre ignoree")
            log_candidature(url, titre, entreprise, "ignoree", "connexion/compte requis")
            return False

        inline_vie = detecter_formulaire_inline_vie(page, timeout_ms=9000) if cible == page else False
        if inline_vie and cible == page:
            print("  [INFO] Formulaire inline VIE detecte (section 'VOUS ETES INTERESSE ? POSTULEZ !').")
            _, lettre_temp_path = remplir_formulaire_vie_inline(
                page, cv_texte, offre, cv_path, langue=langue
            )
        else:
            if page_externe is not None and not formulaire_candidature_detecte(cible):
                print("  [INFO] Onglet externe detecte, tentative de progression vers le formulaire...")
            remplir_formulaire_generique(cible, cv_texte, offre, cv_path, langue=langue)

        try:
            url_avant_submit = cible.url
        except Exception:
            url_avant_submit = ""

        pages_connues_submit = set(page.context.pages)
        soumis = soumettre_formulaire_generique(cible)
        if not soumis:
            break

        # Certains ATS ouvrent encore une nouvelle tab apres "Apply/Submit".
        nouvelle = attendre_nouvelle_page(page.context, pages_connues_submit, timeout_ms=6000)
        if nouvelle is None:
            break

        try:
            nouvelle.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        cible = nouvelle
        page_externe = nouvelle
        try:
            print(f"  [INFO] Nouvelle tab apres soumission, poursuite sur : {cible.url[:90]}")
        except Exception:
            print("  [INFO] Nouvelle tab apres soumission detectee, poursuite dessus")
        # On boucle pour remplir/soumettre sur cette nouvelle tab.
        continue

    if lettre_temp_path:
        print(f"  [INFO] Fichier lettre conserve pour verification: {lettre_temp_path}")

    if not soumis:
        print("  [WARN] Soumission impossible sur cette page")
        log_candidature(url, titre, entreprise, "ignoree", "soumission non detectee")
        return False

    confirmation = False
    try:
        cible.wait_for_selector(
            ':has-text("Votre candidature a été envoyée"), '
            ':has-text("candidature a ete envoyee"), '
            ':has-text("application submitted"), '
            ':has-text("thank you"), :has-text("merci"), '
            '[class*="success"]',
            timeout=7000
        )
        confirmation = True
        print("  [OK] Confirmation detectee")
    except Exception:
        print("  [INFO] Pas de confirmation visible")

    # Mode strict pour onglet externe: pas de confirmation => pas d'"envoyee"
    if page_externe is not None and not confirmation:
        url_apres_submit = ""
        try:
            url_apres_submit = cible.url
        except Exception:
            pass
        if url_apres_submit and url_avant_submit and url_apres_submit != url_avant_submit:
            print("  [INFO] URL externe modifiee apres submit, mais sans confirmation explicite")
        print("  [SKIP] Soumission externe non confirmee, candidature non comptee")
        log_candidature(url, titre, entreprise, "ignoree", "soumission externe non confirmee")
        return False

    log_candidature(url, titre, entreprise, "envoyee")
    return True


def postuler_offre(page, offre: dict, cv_texte: str, cv_path: str, langue: str = "fr") -> bool:
    """
    Tente de postuler Ã  une offre.
    Retourne True si candidature envoyÃ©e, False sinon.
    """
    url = offre["url"]
    titre = offre.get("titre", "Inconnu")
    entreprise = offre.get("entreprise", "Inconnue")
    
    print(f"\nðŸ“‹ Traitement : {titre} @ {entreprise}")
    print(f"   URL : {url}")
    
    # â”€â”€ 1. Trouver et cliquer sur le bouton Apply â”€â”€
    bouton_apply = None
    selecteurs_apply = [
        'button:has-text("Postuler")',
        'button:has-text("Apply")',
        'a:has-text("Postuler")',
        'a:has-text("Apply")',
        '[data-testid="apply-button"]',
        'button[class*="apply"]',
        '[aria-label*="postuler" i]',
        '[aria-label*="apply" i]',
    ]
    
    for sel in selecteurs_apply:
        try:
            el = page.wait_for_selector(sel, timeout=3000, state="visible")
            if el:
                bouton_apply = el
                break
        except Exception:
            continue
    
    if not bouton_apply:
        print("  âš ï¸  Bouton Apply introuvable")
        log_candidature(url, titre, entreprise, "ignoree", "bouton apply introuvable")
        return False
    
    # â”€â”€ 2. Cliquer sur Apply et dÃ©tecter ce qui se passe â”€â”€
    url_avant = page.url
    
    # On Ã©coute si un nouvel onglet s'ouvre (= redirection externe)
    nouvelle_page_externe = None
    def on_new_page(p):
        nonlocal nouvelle_page_externe
        nouvelle_page_externe = p
    page.context.once("page", on_new_page)
    
    try:
        bouton_apply.click()
    except Exception:
        pass
    time.sleep(3)  # Laisser le temps Ã  la popup ou redirection de s'ouvrir
    
    # Cas 1 : un nouvel onglet s'est ouvert â†’ redirection externe
    if nouvelle_page_externe is not None:
        try:
            nouvelle_page_externe.close()
        except Exception:
            pass
        print(f"  â†—ï¸  Redirection externe (nouvel onglet) â†’ ignorÃ©")
        log_candidature(url, titre, entreprise, "ignoree", "redirection externe")
        return False
    
    # Cas 2 : on a Ã©tÃ© redirigÃ© sur une autre page dans le mÃªme onglet
    if page.url != url_avant and "welcometothejungle" not in page.url:
        print(f"  â†—ï¸  Redirection externe ({page.url[:60]}) â†’ ignorÃ©")
        log_candidature(url, titre, entreprise, "ignoree", "redirection externe")
        page.go_back()
        time.sleep(2)
        return False
    
    # â”€â”€ 3. VÃ©rifier que la popup WTTJ s'est ouverte â”€â”€
    popup_selectors = [
        '[data-testid="apply-form-modal"]',
        'form:has([data-testid="apply-form-submit"])',
    ]
    
    popup = None
    for sel in popup_selectors:
        try:
            popup = page.wait_for_selector(sel, timeout=4000, state="visible")
            if popup:
                break
        except Exception:
            continue
    
    if not popup:
        print("  âš ï¸  Aucune popup dÃ©tectÃ©e aprÃ¨s clic Apply â†’ ignorÃ©")
        log_candidature(url, titre, entreprise, "ignoree", "popup non dÃ©tectÃ©e")
        return False
    
    print("  âœ… Popup WTTJ dÃ©tectÃ©e !")
    time.sleep(1)

    # Le formulaire est parfois dans un iframe, mais toujours dans apply-form-modal.
    form_target = page
    form_scope = '[data-testid="apply-form-modal"]'
    try:
        for fr in page.frames:
            if fr == page.main_frame:
                continue
            has_modal = fr.query_selector(form_scope)
            if has_modal:
                form_target = fr
                print("  ðŸ§© Formulaire detecte dans un iframe")
                break
    except Exception:
        pass
    
    # â”€â”€ 4. Remplir le formulaire â”€â”€
    
    # PrÃ©nom
    for sel in [
        f'{form_scope} [data-testid="apply-form-field-firstname"]',
        f'{form_scope} input[name="firstname"]',
        f'{form_scope} input[name*="first" i]',
        f'{form_scope} input[placeholder*="prenom" i]',
        f'{form_scope} input[id*="first" i]'
    ]:
        if remplir_champ(form_target, sel, config.PRENOM):
            break
    
    # Nom
    for sel in [
        f'{form_scope} [data-testid="apply-form-field-lastname"]',
        f'{form_scope} input[name="lastname"]',
        f'{form_scope} input[name*="last" i]',
        f'{form_scope} input[placeholder*="nom" i]',
        f'{form_scope} input[id*="last" i]'
    ]:
        if remplir_champ(form_target, sel, config.NOM):
            break
    
    # Email
    for sel in [
        f'{form_scope} input[type="email"]:not([disabled])',
        f'{form_scope} input[name*="email" i]:not([disabled])',
        f'{form_scope} input[placeholder*="email" i]:not([disabled])'
    ]:
        if remplir_champ(form_target, sel, config.EMAIL):
            break
    
    # TÃ©lÃ©phone
    for sel in [
        f'{form_scope} [data-testid="apply-form-field-phone"]',
        f'{form_scope} input[name="phone"]',
        f'{form_scope} input[type="tel"]',
        f'{form_scope} input[name*="phone" i]',
        f'{form_scope} input[placeholder*="telephone" i]'
    ]:
        if remplir_champ(form_target, sel, config.TELEPHONE):
            break

    # Poste actuel (required sur certaines offres)
    poste_actuel_force = (getattr(config, "POSTE_ACTUEL_FORCE", "") or "").strip()
    poste_actuel = poste_actuel_force or normaliser_poste_actuel(offre)
    for sel in [
        f'{form_scope} [data-testid="apply-form-field-subtitle"]',
        f'{form_scope} input[name="subtitle"]'
    ]:
        if remplir_champ(form_target, sel, poste_actuel):
            break
    
    # LinkedIn
    if config.LINKEDIN:
        for sel in [
            f'{form_scope} [data-testid="apply-form-field-media[linkedin]"]',
            f'{form_scope} input[name*="linkedin" i]',
            f'{form_scope} input[placeholder*="linkedin" i]'
        ]:
            remplir_champ(form_target, sel, config.LINKEDIN)
    
    # Portfolio / Site web
    if config.PORTFOLIO:
        for sel in [
            f'{form_scope} [data-testid="apply-form-field-media[website]"]',
            f'{form_scope} input[name*="portfolio" i]',
            f'{form_scope} input[name*="website" i]',
            f'{form_scope} input[placeholder*="site" i]'
        ]:
            remplir_champ(form_target, sel, config.PORTFOLIO)
    
    # â”€â”€ 5. Upload du CV â”€â”€
    cv_upload = None
    for sel in [
        f'{form_scope} [data-testid="apply-form-field-resume"]',
        f'{form_scope} input[name="resume"]',
        f'{form_scope} #resume'
    ]:
        cv_upload = form_target.query_selector(sel)
        if cv_upload:
            break
    if cv_upload:
        cv_upload.set_input_files(cv_path)
        print("  ðŸ“Ž CV uploadÃ©")
        time.sleep(1)
    
    # â”€â”€ 6. Lettre de motivation â”€â”€
    print("  âœï¸  GÃ©nÃ©ration de la lettre de motivation...")
    lettre = generer_lettre_motivation(cv_texte, offre, langue=langue)
    print(f"  ðŸ“ Lettre gÃ©nÃ©rÃ©e ({len(lettre)} caractÃ¨res)")
    
    # Chercher le champ de lettre de motivation
    champs_lettre = [
        f'{form_scope} [data-testid="apply-form-field-cover_letter"]',
        f'{form_scope} textarea[name*="cover" i]',
        f'{form_scope} textarea[name*="lettre" i]',
        f'{form_scope} textarea[name*="motivation" i]',
        f'{form_scope} textarea[placeholder*="lettre" i]',
        f'{form_scope} textarea[placeholder*="motivation" i]',
        f'{form_scope} textarea[placeholder*="message" i]',
        f'{form_scope} textarea',
    ]
    
    lettre_remplie = False
    for sel in champs_lettre:
        try:
            el = form_target.query_selector(sel)
            if el and el.is_visible():
                el.click()
                el.fill(lettre)
                lettre_remplie = True
                print("  âœ‰ï¸  Lettre de motivation remplie")
                break
        except Exception:
            continue
    
    if not lettre_remplie:
        print("  âš ï¸  Champ lettre de motivation non trouvÃ©")
    
    # â”€â”€ 7. Questions supplÃ©mentaires â”€â”€
    time.sleep(1)
    gerer_questions_supplementaires(form_target, cv_texte, offre, form_scope=form_scope, langue=langue)

    # Consentement RGPD requis
    try:
        consent = form_target.query_selector(f'{form_scope} [data-testid="apply-form-consent"]')
        if consent and not consent.is_checked():
            consent.check()
            print("  âœ… Consentement coche")
    except Exception:
        pass
    
    # â”€â”€ 8. Soumettre â”€â”€
    time.sleep(1)
    boutons_submit = [
        f'{form_scope} [data-testid="apply-form-submit"]',
        f'{form_scope} button[type="submit"]',
        f'{form_scope} button:has-text("J’envoie ma candidature")',
        f'{form_scope} button:has-text("J\'envoie ma candidature")',
        f'{form_scope} button:has-text("Envoyer")',
        f'{form_scope} button:has-text("Soumettre")',
        f'{form_scope} button:has-text("Confirmer")',
        f'{form_scope} button:has-text("Valider")',
        f'{form_scope} button:has-text("Send")',
        f'{form_scope} button:has-text("Submit")',
    ]
    
    soumis = False
    for sel in boutons_submit:
        try:
            btn = form_target.wait_for_selector(sel, timeout=3000, state="visible")
            if btn:
                btn.click()
                soumis = True
                print("  ðŸš€ Formulaire soumis !")
                time.sleep(3)
                break
        except Exception:
            continue
    
    if not soumis:
        print("  âš ï¸  Bouton de soumission non trouvÃ© - candidature non envoyÃ©e")
        log_candidature(url, titre, entreprise, "erreur", "bouton submit non trouvÃ©")
        return False
    
    # â”€â”€ 9. VÃ©rifier la confirmation â”€â”€
    try:
        page.wait_for_selector(
            ':has-text("Votre candidature a été envoyée"), '
            ':has-text("candidature a ete envoyee"), '
            ':has-text("merci"), :has-text("thank you"), '
            ':has-text("envoyée"), :has-text("envoyee"), '
            '[class*="success"]',
            timeout=7000
        )
        print("  🎉 Confirmation de candidature recue !")
    except Exception:
        print("  ℹ️  Pas de confirmation visible (peut etre normal)")
    
    log_candidature(url, titre, entreprise, "envoyee")
    return True


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  POINT D'ENTRÃ‰E PRINCIPAL
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bot de candidature automatique - WTTJ / VIE")
    parser.add_argument("url", help="URL de recherche (WTTJ ou VIE)")
    parser.add_argument(
        "--max", type=int, default=None,
        help="Nombre max d'offres Ã  traiter (ex: --max 5). Surcharge MAX_OFFRES depuis .env"
    )
    parser.add_argument(
        "--max-pages", type=int, default=None,
        help="Nombre max de pages Ã  scraper (ex: --max-pages 3). Surcharge MAX_PAGES depuis .env"
    )
    args = parser.parse_args()

    url_recherche = args.url
    plateforme = detecter_plateforme(url_recherche)
    if plateforme == "inconnue":
        print("\n❌ Plateforme non supportée.")
        print("   URL attendue: welcometothejungle.com ou mon-vie-via.businessfrance.fr")
        sys.exit(1)

    # Priorite : argument CLI > variables chargees depuis .env
    max_offres = args.max if args.max is not None else config.MAX_OFFRES
    max_pages = args.max_pages if args.max_pages is not None else getattr(config, "MAX_PAGES", 3)
    source_max_offres = "CLI (--max)" if args.max is not None else ".env"
    source_max_pages = "CLI (--max-pages)" if args.max_pages is not None else ".env"
    
    # VÃ©rification du CV
    print("ðŸ“„ Lecture du CV...")
    try:
        cv_texte = lire_cv(config.CV_PATH)
        cv_path_abs = os.path.abspath(config.CV_PATH)
        print(f"   âœ… CV lu : {len(cv_texte)} caractÃ¨res")
    except (FileNotFoundError, ImportError, ValueError) as e:
        print(f"\nâŒ Erreur CV : {e}")
        sys.exit(1)
    
    # VÃ©rification de la clÃ© API Mistral
    if not config.MISTRAL_API_KEY or "XXXXX" in config.MISTRAL_API_KEY:
        print("\nâŒ ClÃ© API Mistral non configurÃ©e !")
        print("   Ajoute MISTRAL_API_KEY dans ton fichier .env.")
        print("   Obtiens-la sur https://console.mistral.ai/")
        sys.exit(1)
    
    if plateforme == "wttj":
        manual_login = getattr(config, "WTTJ_MANUAL_LOGIN", False)
        if not manual_login and (not config.WTTJ_EMAIL or not config.WTTJ_PASSWORD):
            print("\nWTTJ_EMAIL / WTTJ_PASSWORD manquants dans .env")
            print("Active WTTJ_MANUAL_LOGIN=true pour te connecter manuellement.")
            sys.exit(1)

    print(f"\nðŸ¤– DÃ©marrage du bot ({plateforme.upper()})")
    print(f"   Candidat    : {config.PRENOM} {config.NOM} ({config.EMAIL})")
    print(f"   ModÃ¨le IA   : {config.MISTRAL_MODEL}")
    print(f"   Max offres  : {max_offres or 'toutes'} (source: {source_max_offres})")
    print(f"   Max pages   : {max_pages or 'toutes'} (source: {source_max_pages})")
    print(f"   Navigateur  : {'visible' if config.SHOW_BROWSER else 'headless (invisible)'}")

    if plateforme == "vie" and not config.SHOW_BROWSER:
        print("\n❌ Pour VIE, SHOW_BROWSER doit etre True (connexion manuelle requise).")
        sys.exit(1)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not config.SHOW_BROWSER,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        
        page = context.new_page()
        
        # Masquer qu'on est un bot
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
        """)
        
        try:
            if plateforme == "wttj":
                # â”€â”€ Login â”€â”€
                se_connecter_wttj(page, context)
            elif getattr(config, "VIE_MANUAL_LOGIN", True):
                se_connecter_vie(page)

            # â”€â”€ Ã‰tape 1 : Collecter les offres â”€â”€
            # IMPORTANT: on ne limite pas ici par max_offres, sinon les offres ignorees
            # consomment le stock collecte et on n'atteint pas l'objectif d'envois.
            if plateforme == "wttj":
                offres = recuperer_toutes_offres(page, url_recherche, max_offres=None, max_pages=max_pages)
            else:
                offres = recuperer_toutes_offres_vie(page, url_recherche, max_offres=None, max_pages=max_pages)
            
            if not offres:
                print("âŒ Aucune offre trouvÃ©e. VÃ©rifie l'URL de recherche.")
                sys.exit(1)
            
            # â”€â”€ Ã‰tape 2 : Traiter chaque offre â”€â”€
            candidatures_envoyees = 0
            deja_vues_run = set()
            objectif = max_offres

            for i, offre_base in enumerate(offres, 1):
                if objectif is not None and candidatures_envoyees >= objectif:
                    print("\n✅ Quota atteint pour ce run, arret du traitement.")
                    break

                url = offre_base["url"]
                objectif_label = objectif if objectif is not None else "infini"
                print(f"\n[{candidatures_envoyees}/{objectif_label}] {'â”€' * 50}")
                
                if url in deja_vues_run:
                    print("  ⏭️  Doublon detecte dans ce run, on passe")
                    continue
                deja_vues_run.add(url)

                # DÃ©jÃ  postulÃ© ?
                if deja_postule(url):
                    print(f"  â­ï¸  DÃ©jÃ  traitÃ©, on passe")
                    continue
                
                try:
                    # RÃ©cupÃ©rer les dÃ©tails de l'offre
                    offre = extraire_details_offre(page, url)
                    langue_offre = detecter_langue_offre(offre)
                    offre["langue"] = langue_offre
                    print(f"  [LANG] Langue detectee: {'anglais' if langue_offre == 'en' else 'francais'}")
                    
                    # Postuler
                    if plateforme == "wttj":
                        succes = postuler_offre(page, offre, cv_texte, cv_path_abs, langue=langue_offre)
                    else:
                        succes = postuler_offre_vie(page, offre, cv_texte, cv_path_abs, langue=langue_offre)
                    
                    if succes:
                        candidatures_envoyees += 1
                        print(f"  ✅ Progression: {candidatures_envoyees}/{objectif_label}")
                    
                    # DÃ©lai entre candidatures
                    if i < len(offres):
                        print(f"  â³ Attente {config.DELAI_ENTRE_CANDIDATURES}s...")
                        time.sleep(config.DELAI_ENTRE_CANDIDATURES)
                
                except Exception as e:
                    print(f"  âŒ Erreur inattendue : {e}")
                    log_candidature(url, offre_base.get("titre", "?"), "?", "erreur", str(e))
                    # Revenir Ã  un Ã©tat propre
                    try:
                        page.goto("about:blank")
                        time.sleep(1)
                    except Exception:
                        pass
            
            print(f"\n{'â•' * 60}")
            print(f"ðŸ Bot terminÃ© ! {candidatures_envoyees} candidature(s) envoyÃ©e(s) ce run.")
            afficher_stats()
        
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()



