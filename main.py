"""
[BOT] Welcome to the Jungle - Bot de candidature automatique
=========================================================
Utilisation :
    python main.py "https://www.welcometothejungle.com/fr/jobs?query=marketing&..."

Le bot va :
1. Recuperer toutes les offres de la recherche (avec pagination)
2. Pour chaque offre, cliquer sur Apply
3. Si ca ouvre une popup WTTJ -> remplir le formulaire + lettre perso generee par l'IA
4. Si ca redirige ailleurs -> ignorer l'offre
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
    if "glassdoor." in host:
        return "glassdoor"
    if "hellowork.com" in host:
        return "hellowork"
    if "mon-vie-via.businessfrance.fr" in host:
        return "vie"
    return "inconnue"


def est_url_offre_directe(url: str) -> bool:
    """Indique si l'URL semble etre une page d'offre directe (et non une recherche)."""
    try:
        parsed = urlparse(url)
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    if "welcometothejungle.com" in host:
        if "/jobs/" not in path:
            return False
        if "query=" in query:
            return False
        return True
    if "glassdoor." in host:
        return est_url_offre_glassdoor(url)
    if "hellowork.com" in host:
        return est_url_offre_hellowork(url)
    return False


def est_url_offre_glassdoor(url: str) -> bool:
    """Filtre les vraies pages d'offre Glassdoor et exclut les pages de recherche/index."""
    try:
        parsed = urlparse(url)
        path = (parsed.path or "").lower().strip()
    except Exception:
        return False

    host = (parsed.netloc or "").lower()
    if "glassdoor." not in host:
        return False
    if not path or path.endswith("/index.htm"):
        return False
    if "emplois-srch" in path or "-emplois-" in path:
        return False
    if "/job-listing/" in path:
        return True
    if "joblisting.htm" in path:
        return True
    # Format frequent FR: /Job/<slug>-JV_<id>.htm
    if "/job/" in path and "-jv_" in path:
        return True
    return False


def est_url_offre_hellowork(url: str) -> bool:
    """Filtre les vraies pages d'offre Hellowork et exclut les pages de recherche."""
    try:
        parsed = urlparse(url)
        path = (parsed.path or "").lower().strip()
    except Exception:
        return False

    host = (parsed.netloc or "").lower()
    if "hellowork.com" not in host:
        return False
    if "/emploi/recherche" in path or "recherche.html" in path:
        return False
    if "/fr-fr/emplois/" in path or "/fr-fr/offres/" in path:
        return path.endswith(".html")
    return False


def detecter_langue_offre(offre: dict) -> str:
    """Heuristique simple pour choisir fr/en selon l'offre."""
    titre = (offre.get("titre", "") or "").lower()
    texte = f"{titre}\n{offre.get('description', '')}".lower()
    if not texte.strip():
        return "fr"

    tokens_titre = re.findall(r"[a-zA-Z]+", titre)
    mots_en_titre = {
        "marketing", "manager", "growth", "product", "business", "developer",
        "engineer", "analyst", "owner", "lead", "sales", "success",
    }
    mots_fr_titre = {
        "chef", "projet", "charge", "charg?", "responsable", "developpement",
        "d?veloppement", "commercial", "communication", "alternance",
    }
    score_titre_en = sum(1 for t in tokens_titre if t.lower() in mots_en_titre)
    score_titre_fr = sum(1 for t in tokens_titre if t.lower() in mots_fr_titre)
    if score_titre_en >= 2 and score_titre_en > score_titre_fr:
        return "en"

    tokens = re.findall(r"[a-zA-Z]+", texte)
    mots_en = {
        "the", "and", "with", "for", "you", "your", "we", "our", "will",
        "experience", "requirements", "skills", "role", "job", "apply",
    }
    mots_fr = {
        "le", "la", "les", "et", "avec", "pour", "vous", "nous", "notre",
        "experience", "exp?rience", "profil", "poste", "mission", "candidature",
    }
    score_en = sum(1 for t in tokens if t.lower() in mots_en)
    score_fr = sum(1 for t in tokens if t.lower() in mots_fr)
    if score_en > score_fr + 1:
        return "en"
    return "fr"


def extraire_question_utilisable(label_brut: str) -> str:
    """Extrait une question courte et exploitable depuis un bloc de texte potentiellement bruit?."""
    texte = (label_brut or "").strip()
    if not texte:
        return ""

    lignes = [re.sub(r"\s+", " ", l).strip() for l in texte.splitlines()]
    lignes = [l for l in lignes if l]
    if not lignes:
        return ""

    # Priorite a la premiere ligne interrogative exploitable.
    for l in lignes:
        ll = l.lower()
        if len(l) < 5 or len(l) > 220:
            continue
        if "@" in l or ll.startswith("tel") or ll.startswith("phone"):
            continue
        if "http://" in ll or "https://" in ll:
            continue
        if "?" in l:
            return l

    # Fallback: premiere ligne raisonnable.
    for l in lignes:
        ll = l.lower()
        if len(l) < 5 or len(l) > 220:
            continue
        if "@" in l or ll.startswith("tel") or ll.startswith("phone"):
            continue
        return l
    return ""


def detecter_langue_question(question: str, langue_par_defaut: str = "fr") -> str:
    """Detecte rapidement la langue d'une question formulaire (fr/en)."""
    q = (question or "").strip().lower()
    if not q:
        return langue_par_defaut

    marqueurs_en = {
        "are you", "will you", "do you", "can you", "have you", "english",
        "experience", "years", "salary", "office", "work from",
    }
    marqueurs_fr = {
        "etes-vous", "parlez-vous", "avez-vous", "pouvez-vous", "francais",
        "exp?rience", "annees", "ann?es", "salaire", "bureau", "presentiel",
    }

    score_en = sum(1 for m in marqueurs_en if m in q)
    score_fr = sum(1 for m in marqueurs_fr if m in q)
    if score_en > score_fr:
        return "en"
    if score_fr > score_en:
        return "fr"
    return langue_par_defaut


def detecter_type_reponse_question(question: str, tag: str, type_input: str) -> str:
    """Determine le type de reponse attendu pour une question supplementaire."""
    if tag == "select":
        return "choix"
    if type_input == "number":
        return "nombre"

    q = (question or "").strip().lower()
    motifs_oui_non = [
        "are you", "will you", "do you", "can you", "have you",
        "etes-vous", "avez-vous", "pouvez-vous", "parlez-vous",
        "seriez-vous", "es-tu", "as-tu", "peux-tu",
    ]
    if "?" in q and any(m in q for m in motifs_oui_non):
        return "oui_non"
    return "texte"


def choisir_langue_reponse_question(question: str, langue_offre: str = "fr") -> str:
    """
    Regle metier:
    - Si l'offre est en anglais, toutes les reponses sont en anglais.
    - Sinon, une question en anglais doit etre repondue en anglais.
    """
    base = (langue_offre or "fr").strip().lower()
    if base.startswith("en"):
        return "en"
    return detecter_langue_question(question, langue_par_defaut="fr")


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
        "cr?er un compte",
        "creer un compte",
        "sign in",
        "log in",
        "create account",
        "register",
    ]
    return any(m in body for m in marqueurs)


def _navigation_interrompue(err: Exception) -> bool:
    msg = str(err).lower()
    return "interrupted by another navigation" in msg or "net::err_aborted" in msg


# ?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]
#  SCRAPING DES OFFRES
# ?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]

def accepter_cookies(page):
    """Accepte la banni??re de cookies si elle appara??t."""
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
                print("  [INFO] Cookies acceptes")
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

    print("  [ACTION] Connecte-toi manuellement au site VIE dans le navigateur.")
    print("  [ACTION] Une fois connecte, reviens ici et appuie sur Entree.")

    try:
        input("  Appuie sur Entree pour continuer... ")
    except EOFError:
        time.sleep(1)
    
    print("  Connexion VIE confirmee")


def se_connecter_glassdoor(page):
    """Connexion manuelle a Glassdoor avant collecte/postulation."""
    print("Connexion a Glassdoor (manuelle)...")
    page.goto("https://www.glassdoor.fr/index.htm", wait_until="domcontentloaded")
    time.sleep(2)
    accepter_cookies(page)
    time.sleep(1)

    print("  [ACTION] Connecte-toi manuellement a Glassdoor dans le navigateur.")
    try:
        input("  Quand c'est bon, appuie simplement sur Entree pour continuer... ")
    except EOFError:
        time.sleep(1)
    print("  Connexion Glassdoor confirmee par l'utilisateur")


def se_connecter_hellowork(page):
    """Connexion manuelle a Hellowork avant collecte/postulation."""
    print("Connexion a Hellowork (manuelle)...")
    page.goto("https://www.hellowork.com/fr-fr/emploi/recherche.html", wait_until="domcontentloaded")
    time.sleep(2)
    accepter_cookies(page)
    time.sleep(1)

    print("  [ACTION] Connecte-toi manuellement a Hellowork dans le navigateur.")
    try:
        input("  Quand c'est bon, appuie simplement sur Entree pour continuer... ")
    except EOFError:
        time.sleep(1)
    print("  Connexion Hellowork confirmee par l'utilisateur")


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


def extraire_offres_page_glassdoor(page):
    """Extrait les URLs d'offres Glassdoor visibles."""
    offres = []
    liens = []
    for _ in range(4):
        try:
            liens = page.eval_on_selector_all(
                'a[href*="/job-listing/"], a[href*="/Job/"], a[href*="/Emploi/"]',
                """elements => elements
                    .map(el => el.href)
                    .filter(Boolean)"""
            )
        except Exception:
            liens = []
        if liens:
            break
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        time.sleep(1)

    vus = set()
    for href in liens:
        url = (href or "").split("?")[0].strip()
        if not url:
            continue
        if not est_url_offre_glassdoor(url):
            continue
        if url in vus:
            continue
        vus.add(url)
        offres.append({"url": url})
    return offres


def extraire_offres_page_hellowork(page):
    """Extrait les URLs d'offres Hellowork visibles."""
    offres = []
    liens = []
    for _ in range(4):
        try:
            liens = page.eval_on_selector_all(
                'a[href*="/fr-fr/emplois/"], a[href*="/fr-fr/offres/"]',
                """elements => elements.map(el => el.href).filter(Boolean)"""
            )
        except Exception:
            liens = []
        if liens:
            break
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        time.sleep(1)

    vus = set()
    for href in liens:
        url = (href or "").split("?")[0].strip()
        if not est_url_offre_hellowork(url):
            continue
        if url in vus:
            continue
        vus.add(url)
        offres.append({"url": url})
    return offres


def activer_filtre_easy_apply_glassdoor(page):
    """Tente d'activer le filtre Easy Apply / Candidature facile."""
    selecteurs = [
        'button:has-text("Candidature facile")',
        'button:has-text("Easy Apply")',
        'label:has-text("Candidature facile")',
        'label:has-text("Easy Apply")',
        '[data-test*="easy-apply"]',
    ]
    for sel in selecteurs:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(1.5)
                print("  [OK] Filtre Easy Apply active")
                return True
        except Exception:
            continue
    print("  [WARN] Filtre Easy Apply introuvable, poursuite sans confirmation explicite")
    return False


def extraire_cartes_glassdoor(page) -> list[dict]:
    """
    Extrait les cartes Glassdoor visibles (sans d?pendre d'URL d'offre).
    Retourne des entr?es avec id pseudo-stable + titre/entreprise.
    """
    cartes = page.evaluate(
        """() => {
            const nodes = Array.from(document.querySelectorAll('li, article, div'));
            const out = [];
            const seen = new Set();
            const bad = ['sponsorise', 'sponsored', 'emplois', 'jobs', 'rechercher'];

            function clean(s){ return (s || '').replace(/\\s+/g, ' ').trim(); }
            function isBadLine(s){
                const l = s.toLowerCase();
                if (!l) return true;
                if (bad.some(b => l === b)) return true;
                if (l.includes('candidature facile') || l.includes('easy apply')) return true;
                if (/^\\d+[jk]?\\s??/.test(l) || /\\b(k?|?)\\b/.test(l)) return true;
                if (l.length < 3) return true;
                return false;
            }

            for (const el of nodes) {
                const txt = clean(el.innerText);
                if (!txt) continue;
                const low = txt.toLowerCase();
                if (!(low.includes('candidature facile') || low.includes('easy apply'))) continue;
                const rect = el.getBoundingClientRect();
                if (rect.width < 180 || rect.height < 70) continue;

                const lines = txt.split('\\n').map(clean).filter(Boolean);
                const useful = lines.filter(l => !isBadLine(l));
                if (useful.length < 2) continue;
                const entreprise = useful[0];
                const titre = useful[1];
                const key = `${entreprise}||${titre}`.toLowerCase();
                if (seen.has(key)) continue;
                seen.add(key);

                out.push({ entreprise, titre, key });
            }
            return out;
        }"""
    ) or []

    offres = []
    for c in cartes:
        entreprise = (c.get("entreprise") or "").strip()
        titre = (c.get("titre") or "").strip()
        if not entreprise or not titre:
            continue
        pseudo_url = f"glassdoor://{_slug_fichier(entreprise)}::{_slug_fichier(titre)}"
        offres.append({"url": pseudo_url, "entreprise": entreprise, "titre": titre, "source": "card"})
    return offres


def _selectionner_carte_glassdoor(page, offre: dict) -> bool:
    """Selectionne une carte Glassdoor par titre/entreprise dans la liste gauche."""
    titre = (offre.get("titre") or "").strip()
    entreprise = (offre.get("entreprise") or "").strip()
    if not titre:
        return False

    try:
        ok = page.evaluate(
            """(data) => {
                const nodes = Array.from(document.querySelectorAll('li, article, div'));
                const titre = (data.titre || '').toLowerCase().trim();
                const entreprise = (data.entreprise || '').toLowerCase().trim();
                function clean(s){ return (s || '').replace(/\\s+/g, ' ').trim().toLowerCase(); }
                for (const el of nodes) {
                    const txt = clean(el.innerText);
                    if (!txt) continue;
                    if (!(txt.includes('candidature facile') || txt.includes('easy apply'))) continue;
                    if (!txt.includes(titre)) continue;
                    if (entreprise && !txt.includes(entreprise)) continue;
                    el.click();
                    return true;
                }
                return false;
            }""",
            {"titre": titre, "entreprise": entreprise},
        )
        return bool(ok)
    except Exception:
        return False


def _url_est_smartapply(url: str) -> bool:
    return "smartapply.indeed.com" in (url or "").lower()


def _construire_url_page(url_recherche: str, page_num: int) -> str:
    """Construit l'URL de recherche en for?ant le param?tre page."""
    parsed = urlparse(url_recherche)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page"] = [str(page_num)]
    nouvelle_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=nouvelle_query))


def recuperer_toutes_offres(page, url_recherche: str, max_offres=None, max_pages=3) -> list[dict]:
    """Navigue sur toutes les pages de resultats et collecte les offres."""
    print(f"\n[SEARCH] Recuperation des offres depuis :\n   {url_recherche}\n")
    toutes_offres = []
    page_num = 1
    urls_vues = set()

    while True:
        if max_pages is not None and page_num > max_pages:
            print(f"  [STOP] Limite de pages atteinte ({max_pages})")
            break

        url_courante = _construire_url_page(url_recherche, page_num)
        print(f"  [LOG] Page {page_num}...")
        page.goto(url_courante, wait_until="domcontentloaded")
        time.sleep(2)
        
        # Scroll pour charger le contenu lazy
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
        
        offres = extraire_offres_page(page)
        if not offres:
            print("     [STUFF] aucune offre sur cette page, arret de la pagination")
            break

        nouvelles = [o for o in offres if o["url"] not in urls_vues]
        toutes_offres.extend(nouvelles)
        urls_vues.update(o["url"] for o in nouvelles)
        print(f"     [STUFF] {len(nouvelles)} nouvelles offres trouvees (total : {len(toutes_offres)})")

        if max_offres and len(toutes_offres) >= max_offres:
            toutes_offres = toutes_offres[:max_offres]
            break

        page_num += 1
    
    print(f"\n[OK] Total : {len(toutes_offres)} offres collectees\n")
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


def recuperer_toutes_offres_glassdoor(page, url_recherche: str, max_offres=None, max_pages=3) -> list[dict]:
    """
    Collecte les offres Glassdoor via scroll infini + bouton "Voir plus d'offres d'emplois".
    Le filtre Easy Apply est active en debut de flux.
    """
    print(f"\n[SEARCH] Recuperation des offres Glassdoor depuis :\n   {url_recherche}\n")
    nav_ok = False
    last_err = None
    for tentative in range(1, 9):
        try:
            page.goto(url_recherche, wait_until="domcontentloaded")
            nav_ok = True
            break
        except Exception as e:
            last_err = e
            if _navigation_interrompue(e):
                print(f"  [WARN] Navigation Glassdoor interrompue (tentative {tentative}/8), nouvelle tentative...")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=12000)
                except Exception:
                    pass
                time.sleep(1.2)
                continue
            raise
    if not nav_ok:
        raise RuntimeError(f"Echec navigation Glassdoor vers la recherche apres 8 tentatives: {last_err}")
    time.sleep(2)
    accepter_cookies(page)
    time.sleep(1)
    activer_filtre_easy_apply_glassdoor(page)

    toutes_offres = []
    urls_vues = set()
    vague = 1

    while True:
        if max_pages is not None and vague > max_pages:
            print(f"  [STOP] Limite de vagues atteinte ({max_pages})")
            break

        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        time.sleep(1.2)

        offres = extraire_cartes_glassdoor(page)
        if not offres:
            print("  [WARN] Aucune carte exploitable detectee sur cette vague (mode card-only)")
        nouvelles = [o for o in offres if o["url"] not in urls_vues]
        toutes_offres.extend(nouvelles)
        urls_vues.update(o["url"] for o in nouvelles)
        print(f"  [PAGE] Vague {vague}: +{len(nouvelles)} offres (total : {len(toutes_offres)})")

        if max_offres and len(toutes_offres) >= max_offres:
            toutes_offres = toutes_offres[:max_offres]
            break

        bouton_plus = None
        for sel in [
            'button:has-text("Voir plus d\'offres d\'emplois")',
            'button:has-text("Show more jobs")',
            'button:has-text("Voir plus")',
            'button:has-text("Show more")',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    bouton_plus = el
                    break
            except Exception:
                continue

        if not bouton_plus:
            # si aucune nouvelle offre et pas de bouton, on termine
            if not nouvelles:
                print("  -> plus de bouton 'voir plus' et aucune nouvelle offre")
                break
            vague += 1
            continue

        try:
            bouton_plus.click()
            time.sleep(2)
        except Exception:
            print("  -> impossible de charger plus d'offres, arret")
            break

        vague += 1

    print(f"\n[OK] Total : {len(toutes_offres)} offres Glassdoor collectees\n")
    return toutes_offres


def recuperer_toutes_offres_hellowork(page, url_recherche: str, max_offres=None, max_pages=3) -> list[dict]:
    """Collecte les offres Hellowork depuis la recherche (pagination simple)."""
    print(f"\n[SEARCH] Recuperation des offres Hellowork depuis :\n   {url_recherche}\n")
    page.goto(url_recherche, wait_until="domcontentloaded")
    time.sleep(2)
    accepter_cookies(page)
    time.sleep(1)

    toutes_offres = []
    urls_vues = set()
    page_num = 1

    while True:
        if max_pages is not None and page_num > max_pages:
            print(f"  [STOP] Limite de pages atteinte ({max_pages})")
            break

        offres = extraire_offres_page_hellowork(page)
        nouvelles = [o for o in offres if o["url"] not in urls_vues]
        toutes_offres.extend(nouvelles)
        urls_vues.update(o["url"] for o in nouvelles)
        print(f"  [PAGE] Page {page_num}: +{len(nouvelles)} offres (total : {len(toutes_offres)})")

        if max_offres and len(toutes_offres) >= max_offres:
            toutes_offres = toutes_offres[:max_offres]
            break

        bouton_suivant = None
        for sel in [
            f'button[name="p"][value="{page_num + 1}"]',
            'button[name="p"]:has(svg use[href*="#right"])',
            'a[rel="next"]',
            'button:has-text("Suivant")',
            'a:has-text("Suivant")',
            'button:has-text("Page suivante")',
            'a:has-text("Page suivante")',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    bouton_suivant = el
                    break
            except Exception:
                continue

        if not bouton_suivant:
            print("  -> plus de page suivante, fin de collecte")
            break

        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        time.sleep(0.6)
        try:
            bouton_suivant.click()
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass # Les turbo-frames ne declenchent pas toujours domcontentloaded
        except Exception as e:
            print(f"  -> erreur lors du clic sur page suivante: {e}")
            break
        time.sleep(2.5) # Laisser le temps au contenu turbo de se mettre a jour
        page_num += 1

    print(f"\n[OK] Total : {len(toutes_offres)} offres Hellowork collectees\n")
    return toutes_offres


# ?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]
#  SCRAPING DES DETAILS D'UNE OFFRE
# ?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]

def extraire_details_offre(page, url: str) -> dict:
    """Extrait le titre, l'entreprise et la description compl??te d'une offre."""
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
    for selector in [
        '[data-testid="job-title"]',
        '[data-test="job-title"]',
        'h1[class*="title"]',
        ".job-title",
        "h1",
    ]:
        el = page.query_selector(selector)
        if el:
            txt = _nettoyer_texte(el.inner_text())
            if txt and len(txt) >= 3:
                offre["titre"] = txt
                break
    
    # Entreprise
    for selector in [
        '[data-testid="company-name"]',
        '[data-test="employer-name"]',
        'a[href*="/companies/"]',
        'a[href*="/Overview/"]',
        '.company-name',
        '.w_75 h2',
        'article h2',
    ]:
        el = page.query_selector(selector)
        if el:
            text = _nettoyer_texte(el.inner_text())
            if text and len(text) < 100 and not re.search(r"\([A-Z]{2}\)$", text):
                offre["entreprise"] = text
                break
    
    # Description compl??te
    desc_parts = []
    for selector in [
        '[data-testid="job-description"]',
        '[data-test="jobDescriptionContent"]',
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


# ?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]
#  REMPLISSAGE DU FORMULAIRE
# ?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]?"[STUFF]

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
    Extrait un intitul? de poste depuis le slug URL.
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
    Construit un intitul? propre pour le champ "Poste actuel".
    Exemple: "B2B Marketing Manager - Strat?gie Sectorielle" -> "Marketing Manager B2B"
    """
    titre = (offre.get("titre_url") or offre.get("titre") or "").strip()
    if not titre:
        return "Marketing"

    titre = re.sub(r"\s+", " ", titre).strip().lower()
    titre = re.sub(r"\bmaketing\b", "marketing", titre, flags=re.IGNORECASE)
    # Retirer les pr?cisions apr?s s?parateur (souvent ?quipe/verticale/localisation)
    titre = re.split(r"\s[--|:]\s", titre, maxsplit=1)[0].strip()
    # Retirer une pr?cision finale entre parenth?ses
    titre = re.sub(r"\s*\([^)]*\)\s*$", "", titre).strip()

    # Retirer les marqueurs de population/type de contrat souvent ajout?s au titre
    # Exemples: h/f, f/h, cdi, cdd, stage, alternance...
    titre = re.sub(r"\b[hf]\s*[/\-]\s*[hf]\b", " ", titre, flags=re.IGNORECASE)
    titre = re.sub(r"\bh\s+f\b|\bf\s+h\b", " ", titre, flags=re.IGNORECASE)
    titre = re.sub(
        r"\b(cdi|cdd|stage|alternance|freelance|interim|temps plein|temps partiel|full time|part time)\b",
        " ",
        titre,
        flags=re.IGNORECASE,
    )
    titre = re.sub(r"\s+", " ", titre).strip()

    # Replacer un pr?fixe business fr?quent en suffixe
    m = re.match(r"^(B2B|B2C)\s+(.+)$", titre, flags=re.IGNORECASE)
    if m:
        titre = f"{m.group(2).strip()} {m.group(1).upper()}"

    if not titre:
        return "Marketing"

    mots_maj = {"b2b", "b2c", "crm", "seo", "sea", "ui", "ux", "qa", "it"}
    titre = " ".join(
        mot.upper() if mot.lower() in mots_maj else mot.capitalize()
        for mot in titre.split()
    )
    return titre


def gerer_questions_supplementaires(
    target,
    cv_texte: str,
    offre: dict,
    form_scope: str = "",
    langue: str = "fr",
):
    """D??tecte et r??pond aux questions suppl??mentaires du formulaire."""
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
        if q["value"]:  # D??j?  rempli
            continue

        label = extraire_question_utilisable(q["label"] or q["placeholder"] or q["name"])
        if not label or len(label) < 3:
            continue

        # Ignorer les champs standards d??j?  g??r??s
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
            "recherche", "search", "keyword", "mot-cle", "mot cl?", "query", "filtre", "filter",
            "localisation", "location", "pays", "metier", "m?tier"
        ]
        if any(k in label.lower() for k in champs_recherche):
            continue

        print(f"  [STUFF] Question detectee : {label[:80]}")

        type_reponse = detecter_type_reponse_question(label, q["tag"], q["type"])
        langue_question = choisir_langue_reponse_question(label, langue_offre=langue)

        question_prompt = label
        if q["tag"] == "select" and q.get("options"):
            opts = ", ".join([o["text"] for o in q["options"] if o.get("text")])
            question_prompt = f"{label}\nChoix possibles: {opts}"

        reponse = repondre_question(
            cv_texte,
            offre,
            question_prompt,
            type_reponse=type_reponse,
            langue=langue_question,
        )
        print(f"     [STUFF] Reponse : {reponse[:100]}...")

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
                # Essayer de matcher la r??ponse IA ?  une option existante.
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
            ':has-text("Votre candidature a ?t? envoy?e"), '
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


def remplir_infos_contact_sans_cv(target):
    """Remplit les champs de contact usuels sans toucher aux uploads CV."""
    champs = [
        (config.PRENOM, ['input[name*="first" i]', 'input[id*="first" i]']),
        (config.NOM, ['input[name*="last" i]', 'input[id*="last" i]']),
        (config.EMAIL, ['input[type="email"]', 'input[name*="email" i]']),
        (config.TELEPHONE, ['input[type="tel"]', 'input[name*="phone" i]', 'input[placeholder*="telephone" i]']),
    ]
    for valeur, selecteurs in champs:
        if not valeur:
            continue
        for sel in selecteurs:
            remplir_champ(target, sel, valeur, timeout=1200)


def cliquer_bouton_smartapply(target) -> str:
    """
    Clique un bouton SmartApply:
    - renvoie 'submit' pour envoi final
    - renvoie 'next' pour etape intermediaire
    - renvoie '' si rien de pertinent
    """
    submit_selecteurs = [
        'button:has-text("Envoyer")',
        'button:has-text("Soumettre")',
        'button:has-text("Submit")',
        'button:has-text("Send application")',
        'button:has-text("Submit application")',
        'button[type="submit"]',
    ]
    for sel in submit_selecteurs:
        try:
            btn = target.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                return "submit"
        except Exception:
            continue

    next_selecteurs = [
        'button:has-text("Suivant")',
        'button:has-text("Continuer")',
        'button:has-text("Next")',
        'button:has-text("Continue")',
        'button:has-text("Review")',
        'button:has-text("Verifier")',
    ]
    for sel in next_selecteurs:
        try:
            btn = target.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                return "next"
        except Exception:
            continue
    return ""


def postuler_offre_glassdoor(page, offre: dict, cv_texte: str, langue: str = "fr") -> bool:
    """Postule a une offre Glassdoor via Easy Apply -> SmartApply."""
    url = offre["url"]
    titre = offre.get("titre", "Inconnu")
    entreprise = offre.get("entreprise", "Inconnue")
    print(f"\n[JOB] Traitement Glassdoor : {titre} @ {entreprise}")
    print(f"   URL : {url}")

    if not str(url).startswith("glassdoor://"):
        print("  [SKIP] Offre ignoree: mode Glassdoor card-only (aucune navigation URL directe)")
        log_candidature(url, titre, entreprise, "ignoree", "url directe interdite en mode card-only")
        return False

    ok_card = _selectionner_carte_glassdoor(page, offre)
    if not ok_card:
        print("  [SKIP] Carte Glassdoor introuvable dans la liste")
        log_candidature(url, titre, entreprise, "ignoree", "carte introuvable")
        return False
    time.sleep(1.2)

    easy_apply = None
    for sel in [
        'button:has-text("Candidature facile")',
        'button:has-text("Easy Apply")',
        'a:has-text("Candidature facile")',
        'a:has-text("Easy Apply")',
        '[data-test*="easyApply"]',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                easy_apply = el
                break
        except Exception:
            continue

    if not easy_apply:
        print("  [SKIP] Bouton Easy Apply introuvable")
        log_candidature(url, titre, entreprise, "ignoree", "easy apply introuvable")
        return False

    pages_avant = set(page.context.pages)
    try:
        easy_apply.click()
    except Exception:
        try:
            easy_apply.click(force=True)
        except Exception:
            pass
    time.sleep(2)

    cible = attendre_nouvelle_page(page.context, pages_avant, timeout_ms=12000)
    if cible is None:
        if "smartapply.indeed.com" in (page.url or "").lower():
            cible = page
        else:
            print("  [SKIP] Redirection SmartApply non detectee")
            log_candidature(url, titre, entreprise, "ignoree", "smartapply non detecte")
            return False

    # La tab peut commencer en about:blank avant de basculer vers SmartApply.
    final_url = ""
    for _ in range(20):
        try:
            cible.wait_for_load_state("domcontentloaded", timeout=1500)
        except Exception:
            pass
        final_url = (cible.url or "")
        if _url_est_smartapply(final_url):
            break
        if final_url and final_url.lower() != "about:blank":
            # peut encore rediriger ensuite, on attend un peu
            time.sleep(0.8)
        else:
            time.sleep(0.8)

    if not _url_est_smartapply(final_url):
        print(f"  [SKIP] URL cible non supportee: {final_url[:90]}")
        log_candidature(url, titre, entreprise, "ignoree", "ats non supporte")
        return False

    # SmartApply: pas d'upload CV (deja present), mais questions dynamiques possibles.
    confirme = False
    for _ in range(8):
        remplir_infos_contact_sans_cv(cible)
        gerer_questions_supplementaires(cible, cv_texte, offre, form_scope="", langue=langue)

        action = cliquer_bouton_smartapply(cible)
        if not action:
            break
        time.sleep(2)

        try:
            cible.wait_for_selector(
                ':has-text("application submitted"), :has-text("thank you"), :has-text("candidature a ete envoyee"), [class*="success"]',
                timeout=2500,
            )
            confirme = True
            break
        except Exception:
            continue

    if not confirme:
        print("  [SKIP] Soumission SmartApply non confirmee")
        log_candidature(url, titre, entreprise, "ignoree", "soumission smartapply non confirmee")
        return False

    print("  [OK] Candidature Glassdoor envoyee (confirmation detectee)")
    log_candidature(url, titre, entreprise, "envoyee")
    return True


def postuler_offre_hellowork(page, offre: dict, cv_texte: str, langue: str = "fr", skip_letter: bool = False) -> bool:
    """Postule a une offre Hellowork via le formulaire interne."""
    url = offre["url"]
    titre = offre.get("titre", "Inconnu")
    entreprise = offre.get("entreprise", "Inconnue")
    print(f"\n[JOB] Traitement Hellowork : {titre} @ {entreprise}")
    print(f"   URL : {url}")

    page.goto(url, wait_until="domcontentloaded")
    time.sleep(2)
    accepter_cookies(page)

    # Faire de?filer ou cliquer sur "Postuler" pour charger le formulaire lazy (turbo-frame)
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        btn_postuler_scroll = page.query_selector('a[href="#postuler"], #mobile-sticky-button')
        if btn_postuler_scroll and btn_postuler_scroll.is_visible():
            btn_postuler_scroll.click()
            time.sleep(2)
        else:
            # Essayer de trouver juste un bouton postuler qui ne soumet pas de formulaire
            for sel in ['button.tw-btn-primary-candidacy-l', 'a.tw-btn-primary-candidacy-l']:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(2)
                    break

        # Attendre que le formulaire se charge ou apparaisse
        page.wait_for_selector('form#offer-detail-main-step-form, #Answer_MotivationLetter_Funnel', timeout=4000)
    except Exception:
        pass

    bouton_externe = None
    for sel in [
        'a:has-text("Postuler sur le site du recruteur")',
        'button:has-text("Postuler sur le site du recruteur")',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                bouton_externe = el
                break
        except Exception:
            continue

    if bouton_externe:
        print("  [SKIP] Candidature externe (site du recruteur)")
        log_candidature(url, titre, entreprise, "ignoree", "site recruteur externe")
        return False

    if skip_letter:
        print("  [INFO] Option --skip-letter activee. On tente de postuler sans message.")
    else:
        lettre = generer_lettre_motivation(cv_texte, offre, langue=langue)

        bouton_message = None
        for sel in [
            '[data-cy="motivationFieldButton"]',
            'label:has-text("Personnaliser mon message au recruteur")',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    bouton_message = el
                    break
            except Exception:
                continue
        if bouton_message:
            try:
                bouton_message.click()
                time.sleep(0.6)
            except Exception:
                pass

        zone_message = None
        for sel in [
            '#Answer_MotivationLetter_Funnel',
            'textarea[name="MotivationLetter"]',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    zone_message = el
                    break
            except Exception:
                continue

        if not zone_message:
            # Si on ne trouve pas la zone apress avoir clique, c'est peut-etre deja rempli ou optionnel.
            pass
        else:
            try:
                zone_message.fill(lettre[:3000])
            except Exception:
                print("  [WARN] Impossible de remplir le message recruteur (continuons)")

    bouton_postuler = None
    for sel in [
        'button[data-cy="submitButton"]',
        'button[type="submit"]:has-text("Postuler")',
        'button:has-text("Postuler")',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                bouton_postuler = el
                break
        except Exception:
            continue

    if not bouton_postuler:
        print("  [SKIP] Bouton Postuler introuvable")
        log_candidature(url, titre, entreprise, "ignoree", "bouton postuler introuvable")
        return False

    try:
        bouton_postuler.click()
        time.sleep(2.5)
    except Exception:
        print("  [SKIP] Echec clic sur Postuler")
        log_candidature(url, titre, entreprise, "ignoree", "clic postuler echoue")
        return False

    try:
        page.wait_for_selector(
            ':has-text("candidature"), :has-text("envoyee"), :has-text("envoy?e"), :has-text("merci"), [class*="success"]',
            timeout=5000,
        )
    except Exception:
        pass

    print("  [OK] Candidature Hellowork soumise")
    log_candidature(url, titre, entreprise, "envoyee")
    return True


def postuler_offre(page, offre: dict, cv_texte: str, cv_path: str, langue: str = "fr", skip_letter: bool = False) -> bool:
    """
    Tente de postuler ?  une offre.
    Retourne True si candidature envoy??e, False sinon.
    """
    url = offre["url"]
    titre = offre.get("titre", "Inconnu")
    entreprise = offre.get("entreprise", "Inconnue")
    
    print(f"\n[STUFF] Traitement : {titre} @ {entreprise}")
    print(f"   URL : {url}")
    
    # ?"[STUFF] 1. Trouver et cliquer sur le bouton Apply ?"[STUFF]
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
        print("  [INFO] [INFO]?  Bouton Apply introuvable")
        log_candidature(url, titre, entreprise, "ignoree", "bouton apply introuvable")
        return False
    
    # ?"[STUFF] 2. Cliquer sur Apply et d??tecter ce qui se passe ?"[STUFF]
    url_avant = page.url
    
    # On ??coute si un nouvel onglet s'ouvre (= redirection externe)
    nouvelle_page_externe = None
    def on_new_page(p):
        nonlocal nouvelle_page_externe
        nouvelle_page_externe = p
    page.context.once("page", on_new_page)
    
    try:
        bouton_apply.click()
    except Exception:
        pass
    time.sleep(3)  # Laisser le temps ?  la popup ou redirection de s'ouvrir
    
    # Cas 1 : un nouvel onglet s'est ouvert [STUFF] redirection externe
    if nouvelle_page_externe is not None:
        try:
            nouvelle_page_externe.close()
        except Exception:
            pass
        print(f"  [INFO]-[INFO]?  Redirection externe (nouvel onglet) [STUFF] ignor[INFO]")
        log_candidature(url, titre, entreprise, "ignoree", "redirection externe")
        return False
    
    # Cas 2 : on a ??t?? redirig?? sur une autre page dans le m??me onglet
    if page.url != url_avant and "welcometothejungle" not in page.url:
        print(f"  [INFO]-[INFO]?  Redirection externe ({page.url[:60]}) [STUFF] ignor[INFO]")
        log_candidature(url, titre, entreprise, "ignoree", "redirection externe")
        page.go_back()
        time.sleep(2)
        return False
    
    # ?"[STUFF] 3. V??rifier que la popup WTTJ s'est ouverte ?"[STUFF]
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
        print("  [INFO] [INFO]?  Aucune popup detectee apres clic Apply [STUFF] ignor[INFO]")
        log_candidature(url, titre, entreprise, "ignoree", "popup non detectee")
        return False
    
    print("  [OK] Popup WTTJ detectee !")
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
                print("  [FORM] Formulaire detecte dans un iframe")
                break
    except Exception:
        pass
    
    # ?"[STUFF] 4. Remplir le formulaire ?"[STUFF]
    
    # Pr??nom
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
    
    # T??l??phone
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
    
    # ?"[STUFF] 5. Upload du CV ?"[STUFF]
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
        print("  [STUFF] CV upload[INFO]")
        time.sleep(1)
    
    # ?"[STUFF] 6. Lettre de motivation ?"[STUFF]
    print("  [INFO][INFO][INFO]  G[INFO]n[INFO]ration de la lettre de motivation...")
    lettre = generer_lettre_motivation(cv_texte, offre, langue=langue)
    print(f"  [STUFF] Lettre g[INFO]n[INFO]r[INFO]e ({len(lettre)} caract[INFO]res)")
    
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
                print("  [INFO][INFO][INFO]  Lettre de motivation remplie")
                break
        except Exception:
            continue
    
    if not lettre_remplie:
        print("  [INFO] [INFO]?  Champ lettre de motivation non trouv[INFO]")
    
    # ?"[STUFF] 7. Questions suppl??mentaires ?"[STUFF]
    time.sleep(1)
    gerer_questions_supplementaires(form_target, cv_texte, offre, form_scope=form_scope, langue=langue)

    # Consentement RGPD requis
    try:
        consent = form_target.query_selector(f'{form_scope} [data-testid="apply-form-consent"]')
        if consent and not consent.is_checked():
            consent.check()
            print("  [OK] Consentement coche")
    except Exception:
        pass
    
    # ?"[STUFF] 8. Soumettre ?"[STUFF]
    time.sleep(1)
    boutons_submit = [
        f'{form_scope} [data-testid="apply-form-submit"]',
        f'{form_scope} button[type="submit"]',
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
                print("  [START] Formulaire soumis !")
                time.sleep(3)
                break
        except Exception:
            continue
    
    if not soumis:
        print("  [INFO] [INFO]?  Bouton de soumission non trouv[INFO] - candidature non envoy[INFO]e")
        log_candidature(url, titre, entreprise, "erreur", "bouton submit non trouv??")
        return False
    
    # ?"[STUFF] 9. V??rifier la confirmation ?"[STUFF]
    try:
        page.wait_for_selector(
            ':has-text("Votre candidature a ?t? envoy?e"), '
            ':has-text("candidature a ete envoyee"), '
            ':has-text("merci"), :has-text("thank you"), '
            ':has-text("envoy?e"), :has-text("envoyee"), '
            '[class*="success"]',
            timeout=7000
        )
        print("  ? Confirmation de candidature recue !")
    except Exception:
        print("  [INFO]  Pas de confirmation visible (peut etre normal)")
    
    log_candidature(url, titre, entreprise, "envoyee")
    return True


# --------------------------------------------------
#  POINT D'ENTREE PRINCIPAL
# --------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bot de candidature automatique - WTTJ / Glassdoor / Hellowork / VIE")
    parser.add_argument("url_pos", nargs="?", help="URL de recherche (positionnel)")
    parser.add_argument("-u", "--url", help="URL de recherche (alternative au positionnel)")
    parser.add_argument(
        "--max", type=int, default=None,
        help="Nombre max d'offres a traiter (ex: --max 5). Surcharge MAX_OFFRES depuis .env"
    )
    parser.add_argument(
        "--max-pages", type=int, default=None,
        help="Nombre max de pages ?  scraper (ex: --max-pages 3). Surcharge MAX_PAGES depuis .env"
    )
    parser.add_argument(
        "--cv-mode", type=str, default=None,
        choices=["direct", "pptx", "html"],
        help="Mode de CV: direct (PDF tel quel), pptx (modifie template) ou html."
    )
    parser.add_argument(
        "--llm", type=str, default=None,
        choices=["mistral", "openai"],
        help="LLM primaire a utiliser (Mistral ou OpenAI)."
    )
    parser.add_argument(
        "--test-letter", action="store_true",
        help="Mode test : genere uniquement la lettre pour une offre directe."
    )
    parser.add_argument(
        "--skip-letter", action="store_true",
        help="Ne pas generer de lettre si elle n'est pas obligatoire (ex: Hellowork)."
    )
    args = parser.parse_args()

    url_recherche = args.url or args.url_pos
    if not url_recherche:
        parser.print_help()
        print("\n[ERROR] L'URL de recherche est requise (soit en positionnel, soit via --url)")
        sys.exit(1)

    plateforme = detecter_plateforme(url_recherche)
    if plateforme == "inconnue":
        print("\n[ERROR] Plateforme non supportee.")
        print("   URL attendue: welcometothejungle.com, glassdoor.*, hellowork.com ou mon-vie-via.businessfrance.fr")
        sys.exit(1)

    if args.test_letter and not est_url_offre_directe(url_recherche):
        print("\n[ERROR] --test-letter attend une URL d'offre directe (pas une page de recherche).")
        print("   Exemple: https://www.welcometothejungle.com/fr/companies/.../jobs/...")
        sys.exit(1)

    # Priorite : argument CLI > variables chargees depuis .env
    max_offres = args.max if args.max is not None else config.MAX_OFFRES
    max_pages = args.max_pages if args.max_pages is not None else getattr(config, "MAX_PAGES", 3)
    source_max_offres = "CLI (--max)" if args.max is not None else ".env"
    source_max_pages = "CLI (--max-pages)" if args.max_pages is not None else ".env"
    
    # Verification du CV
    print("[INFO] Lecture du CV...")
    try:
        cv_texte = lire_cv(config.CV_PATH)
        cv_path_abs = os.path.abspath(config.CV_PATH)
        print(f"   [OK] CV lu : {len(cv_texte)} caracteres")
    except (FileNotFoundError, ImportError, ValueError) as e:
        print(f"\n[ERROR] Erreur CV : {e}")
        sys.exit(1)

    # --- Gestion du Mode de CV et Mod?le IA ---
    cv_mode = args.cv_mode if args.cv_mode else getattr(config, "CV_MODE", "direct")
    llm_choice = args.llm if args.llm else getattr(config, "PRIMARY_LLM", "mistral")
    
    pptx_path = None
    if cv_mode == "pptx":
        pptx_path = config.CV_PATH_PPTX
        if not os.path.exists(pptx_path):
            print(f"  [WARN] Template PPTX introuvable : {pptx_path}. Fallback mode direct.")
            cv_mode = "direct"
            pptx_path = None
        else:
            try:
                import comtypes.client
                import pptx
            except ImportError:
                print("  [WARN] Modules python-pptx/comtypes manquants. Fallback mode direct.")
                cv_mode = "direct"
                pptx_path = None
    
    # V??rification de la cl?? API Mistral
    if not config.MISTRAL_API_KEY or "XXXXX" in config.MISTRAL_API_KEY:
        print("\n[INFO]? Cl[INFO] API Mistral non configur[INFO]e !")
        print("   Ajoute MISTRAL_API_KEY dans ton fichier .env.")
        print("   Obtiens-la sur https://console.mistral.ai/")
        sys.exit(1)
    
    if plateforme == "wttj" and not args.test_letter:
        manual_login = getattr(config, "WTTJ_MANUAL_LOGIN", False)
        if not manual_login and (not config.WTTJ_EMAIL or not config.WTTJ_PASSWORD):
            print("\nWTTJ_EMAIL / WTTJ_PASSWORD manquants dans .env")
            print("Active WTTJ_MANUAL_LOGIN=true pour te connecter manuellement.")
            sys.exit(1)

    print(f"\n[INFO] - Demarrage du bot ({plateforme.upper()})")
    print(f"   Candidat    : {config.PRENOM} {config.NOM} ({config.EMAIL})")
    print(f"   Modele IA   : {llm_choice.upper()} (Logic: {config.MISTRAL_MODEL if llm_choice=='mistral' else config.OPENAI_MODEL})")
    print(f"   Mode CV     : {cv_mode.upper()}")
    print(f"   Max offres  : {max_offres or 'toutes'} (source: {source_max_offres})")
    print(f"   Max pages   : {max_pages or 'toutes'} (source: {source_max_pages})")
    print(f"   Navigateur  : {'visible' if config.SHOW_BROWSER else 'headless (invisible)'}")

    if plateforme in {"vie", "glassdoor", "hellowork"} and not config.SHOW_BROWSER:
        print(f"\n[ERROR] Pour {plateforme.upper()}, SHOW_BROWSER doit etre True (connexion manuelle requise).")
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
            if args.test_letter:
                print("\n[TEST] Mode generation lettre uniquement")
                offre = extraire_details_offre(page, url_recherche)
                langue_offre = detecter_langue_offre(offre)
                offre["langue"] = langue_offre
                print(f"  [JOB] {offre.get('titre', '?')} @ {offre.get('entreprise', '?')}")
                print(f"  [LANG] {'anglais' if langue_offre == 'en' else 'francais'}")

                lettre = generer_lettre_motivation(cv_texte, offre, langue=langue_offre)
                lettre_path = creer_fichier_temp_lettre(lettre, offre)
                print(f"\n[OK] Lettre generee ({len(lettre)} caracteres)")
                print(f"[OK] Fichier: {lettre_path}\n")
                print(lettre)
                return

            if plateforme == "wttj":
                # ?"[STUFF] Login ?"[STUFF]
                se_connecter_wttj(page, context)
            elif plateforme == "vie" and getattr(config, "VIE_MANUAL_LOGIN", True):
                se_connecter_vie(page)
            elif plateforme == "glassdoor":
                se_connecter_glassdoor(page)
            elif plateforme == "hellowork":
                se_connecter_hellowork(page)

            # ?"[STUFF] ??tape 1 : Collecter les offres ?"[STUFF]
            # IMPORTANT: on ne limite pas ici par max_offres, sinon les offres ignorees
            # consomment le stock collecte et on n'atteint pas l'objectif d'envois.
            if plateforme == "wttj":
                offres = recuperer_toutes_offres(page, url_recherche, max_offres=None, max_pages=max_pages)
            elif plateforme == "glassdoor":
                offres = recuperer_toutes_offres_glassdoor(page, url_recherche, max_offres=None, max_pages=max_pages)
            elif plateforme == "hellowork":
                offres = recuperer_toutes_offres_hellowork(page, url_recherche, max_offres=None, max_pages=max_pages)
            else:
                offres = recuperer_toutes_offres_vie(page, url_recherche, max_offres=None, max_pages=max_pages)
            
            if not offres:
                print("[INFO]? Aucune offre trouv[INFO]e. V[INFO]rifie l'URL de recherche.")
                sys.exit(1)
            
            # ?"[STUFF] ??tape 2 : Traiter chaque offre ?"[STUFF]
            candidatures_envoyees = 0
            deja_vues_run = set()
            objectif = max_offres

            for i, offre_base in enumerate(offres, 1):
                if objectif is not None and candidatures_envoyees >= objectif:
                    print("\n[OK] Quota atteint pour ce run, arret du traitement.")
                    break

                url = offre_base["url"]
                objectif_label = objectif if objectif is not None else "infini"
                print(f"\n[{candidatures_envoyees}/{objectif_label}] {'-' * 50}")
                
                if url in deja_vues_run:
                    print("  [INFO]  Doublon detecte dans ce run, on passe")
                    continue
                deja_vues_run.add(url)

                # Deja postule ?
                if deja_postule(url):
                    print(f"  [INFO] Deja traite, on passe")
                    continue
                
                try:
                    # Recuperer les details de l'offre
                    if plateforme == "glassdoor":
                        # Sur Glassdoor, on postule carte par carte sans naviguer sur chaque URL
                        # pour eviter de casser le contexte de recherche.
                        offre = dict(offre_base)
                        offre.setdefault("description", "")
                        offre.setdefault("titre_url", extraire_titre_depuis_url_offre(url))
                    else:
                        offre = extraire_details_offre(page, url)
                    langue_offre = detecter_langue_offre(offre)
                    offre["langue"] = langue_offre
                    print(f"  [LANG] Langue detectee: {'anglais' if langue_offre == 'en' else 'francais'}")
                    
                    cv_path_a_utiliser = cv_path_abs
                    if cv_mode == "pptx" and pptx_path:
                        try:
                            from cv_tailor import adapter_cv_pptx
                            # adapter_cv_pptx s'occupe de generer le PDF et renvoie son chemin absolu
                            nouveau_cv = adapter_cv_pptx(pptx_path, offre, dossier_sortie="cv_genere")
                            if nouveau_cv and os.path.exists(nouveau_cv):
                                cv_path_a_utiliser = nouveau_cv
                        except Exception as ex:
                            print(f"  [WARN] Erreur generation CV PPTX : {ex}")
                    elif cv_mode == "html":
                        try:
                            from html_tailor import adapter_cv_html
                            # adapter_cv_html s'occupe de generer le HTML, de le convertir en PDF et renvoie le chemin du PDF
                            nouveau_cv = adapter_cv_html("cv_template.html", offre, dossier_sortie="cv_genere")
                            if nouveau_cv and os.path.exists(nouveau_cv):
                                cv_path_a_utiliser = nouveau_cv
                        except Exception as ex:
                            print(f"  [WARN] Erreur generation CV HTML : {ex}")
                    
                    # Postuler
                    if plateforme == "wttj":
                        succes = postuler_offre(page, offre, cv_texte, cv_path_a_utiliser, langue=langue_offre, skip_letter=args.skip_letter)
                    elif plateforme == "glassdoor":
                        succes = postuler_offre_glassdoor(page, offre, cv_texte, langue=langue_offre)
                    elif plateforme == "hellowork":
                        succes = postuler_offre_hellowork(page, offre, cv_texte, langue=langue_offre, skip_letter=args.skip_letter)
                    else:
                        succes = postuler_offre_vie(page, offre, cv_texte, cv_path_a_utiliser, langue=langue_offre)
                    
                    if succes:
                        candidatures_envoyees += 1
                        print(f"  [OK] Progression: {candidatures_envoyees}/{objectif_label}")
                    
                    # D??lai entre candidatures
                    if i < len(offres):
                        print(f"  [INFO]? Attente {config.DELAI_ENTRE_CANDIDATURES}s...")
                        time.sleep(config.DELAI_ENTRE_CANDIDATURES)
                
                except Exception as e:
                    print(f"  [INFO]? Erreur inattendue : {e}")
                    log_candidature(url, offre_base.get("titre", "?"), "?", "erreur", str(e))
                    # Revenir ?  un ??tat propre
                    try:
                        page.goto("about:blank")
                        time.sleep(1)
                    except Exception:
                        pass
            
            print(f"\n{'*' * 60}")
            print(f"[INFO] Bot termine ! {candidatures_envoyees} candidature(s) envoyee(s) ce run.")
            afficher_stats()
        
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()



