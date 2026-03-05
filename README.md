<div align="center">
  <h1>🌴 WTTJ Bot - Auto Job Applier 🤖</h1>
  <p>
    <strong>Automatisez vos candidatures sur Welcome to the Jungle et le portail VIE grâce à l'IA</strong>
  </p>
  
  <p>
    <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white" alt="Playwright" />
    <img src="https://img.shields.io/badge/Mistral_AI-F47C20?style=for-the-badge&logo=mistral&logoColor=white" alt="Mistral AI" />
  </p>
</div>

<hr/>

Ce bot **Python** automatise l'envoi de candidatures sur **Welcome to the Jungle** et le portail **Mon VIE**. Fini les tâches répétitives : le bot navigue sur les offres, analyse les descriptions, extrait votre CV et génère des **lettres de motivation ultra-personnalisées** avec l'aide de **Mistral AI**.

## ✨ Fonctionnalités

- 🚀 **Automatisation complète :** Recherche, pagination, navigation et remplissage des formulaires automatiques via Playwright.
- 🧠 **IA Intégrée (Mistral) :** Génération de lettres de motivation qualitatives et réponses aux questions personnalisées en fonction du poste et de votre profil.
- 📄 **Analyse de CV :** Support automatique de l'extraction de texte sur les CV au format PDF (via `PyPDF2`) ou Texte.
- 🕵️ **Multi-Plateformes :** Suivi intelligent des balises URL, compatible pour les annonces *Welcome to the Jungle* et le portail *Mon VIE*.
- 🛡️ **Anti-Doublons :** Suivi d'historique local dans `candidatures.json` (via `logger.py`) pour ne pas postuler aux mêmes annonces deux fois.
- ⚡ **Configuration rapide :** Setup souple entièrement reposant sur un fichier de variables d'environnement (`.env`).

---

## 💡 Le point fort : L'API Mistral est GRATUITE ! 💰

Contrairement à de nombreuses autres intégrations qui facturent avec OpenAI (ChatGPT) ou Anthropic (Claude), **l'API de Mistral AI vous permet de démarrer avec des crédits gratuits**. 

### Comment obtenir votre clé gratuite :
1. Rendez-vous sur la plateforme [Console Mistral AI 🔗](https://console.mistral.ai/).
2. Créez un compte ou connectez-vous avec vos identifiants.
3. Allez dans le volet de gauche, rubrique **API keys**.
4. Vous bénéficierez d'un "Free Tier" ou pourrez générer des clés avec la version d'essai sans ajouter de moyen de paiement (soumis à un *rate limit* généreux plus que suffisant pour vos premières vagues de candidatures massives).
5. Copiez votre clé d'API (commençant par `key_...`) et ajoutez-la à votre fichier `.env`.

---

## 🛠️ Installation & Pré-requis

1. **Cloner le repository :**
```bash
git clone https://github.com/VOTRE_PSEUDO/wttj_bot.git
cd wttj_bot
```

2. **Installer les dépendances (Python 3.8+ requis) :**
```bash
pip install -r requirements.txt
```

3. **Installer les navigateurs pour Playwright :**
```bash
playwright install chromium
```

---

## ⚙️ Configuration (.env)

1. **Créer le fichier de configuration** à la racine en vous basant sur l'exemple :
*(Windows)*
```cmd
copy .env.example .env
```
*(Mac/Linux)*
```bash
cp .env.example .env
```

2. **Remplir vos informations personnelles** dans le `.env` créé :
```env
# API Mistral (Clé gratuite !)
MISTRAL_API_KEY=votre_cle_api_mistral

# Informations du candidat
PRENOM=Jean
NOM=Dupont
EMAIL=jean.dupont@email.com
TELEPHONE=0601020304
CV_PATH=./votre_dossier/CV_Jean_Dupont.pdf

# Optionnel : Connexion automatique WTTJ
WTTJ_MANUAL_LOGIN=false
WTTJ_EMAIL=jean.dupont@email.com
WTTJ_PASSWORD=VotreMotDePasseSecret
```

---

## 🚀 Utilisation

Lancez le script main avec l'URL pointant vers les résultats de votre recherche Welcome to the Jungle. 

```bash
python main.py "URL_DE_RECHERCHE"
```

**Exemple d'utilisation :**
```bash
python main.py "https://www.welcometothejungle.com/fr/jobs?query=marketing&page=1"
```

### Options CLI :

Vous pouvez affiner l'exécution avec les arguments suivants :
- `--max <int>` : Limite le nombre total de dépôts de candidatures générées.
- `--max-pages <int>` : Limite le nombre de pages (ou de vagues de chargements "Voir plus") parcourues parmi les résultats.

**Exemple avec paramètres :**
```bash
python main.py "https://www.welcometothejungle.com/fr/jobs?query=data" --max 10 --max-pages 2
```

---

## 📂 Structure du Projet

```text
├── main.py                 # 🚀 Orchestrateur principal & logique de navigation (Playwright)
├── ai_helper.py            # 🧠 Appels d'API Mistral (lettres de motivation, questions personnalisées)
├── cv_reader.py            # 📄 Module d'extraction texte (parsing des PDF et TXT)
├── logger.py               # 📝 Système de tracking (gère candidatures.json)
├── config.py               # ⚙️ Chargement sécurisé des variables
├── requirements.txt        # 📦 Liste des dépendances pip
└── .env                    # 🔒 Variables privées de l'utilisateur (ignoré par Git)
```

---

## ⚠️ Avertissement, CGUs & Sécurité

**Sécurité de votre clé :**
Votre fichier `.env` est automatiquement ignoré par `.gitignore`. **Ne publiez jamais votre fichier contenant vos mots de passe ou votre API Key sur GitHub**. Si une clé Mistral fuite, révoquez-la immédiatement depuis la section Billing.

**Disclaimer de responsabilité :**
Ce projet `wttj_bot` a pour vocation l'éducation au web-scraping respectueux et l'automatisation pour productivité personnelle. Gardez à l'esprit que l'utilisation de tels bots contourne les conditions d'utilisation classiques (CGU) des plateformes cibles. Utilisez-le avec retenue, un volume excessif conduira sûrement à une restriction de votre compte. L'auteur de ce repository ne saurait être tenu responsable des répercussions liées à son utilisation.

<br>
<div align="center">
  <i>Développé pour rendre la recherche d'emploi moins pénible pour tout le monde 🧗</i>
</div>