# AlerteLogement

Script qui surveille les locations de **Frances Immobilier** et envoie un e-mail dès qu'un logement
dont le loyer est **compris entre 300 € et 520 €** (bornes incluses) apparaît. Il tourne 24h/24 via
**GitHub Actions** (dépôt **public**, donc minutes gratuites et illimitées).

## Objectif

- Vérifier régulièrement (toutes les 15 min par défaut) la liste des locations.
- Détecter les **nouvelles** annonces qui sont dans la fourchette de prix et pas marquées « Loué ».
- Envoyer **un seul e-mail par annonce** (jamais deux fois la même), avec : prix, titre/ville, lien direct.
- Ne jamais planter définitivement : une erreur réseau ou de parsing est journalisée, puis on réessaie au cycle suivant.

## Stack

- **Python 3.12** (déjà installé : `C:\Users\NOVASUPTECH\AppData\Local\Programs\Python\Python312\python`)
- `requests` + `beautifulsoup4` pour le scraping (le HTML est rendu côté serveur, pas besoin de navigateur headless)
- `smtplib` (stdlib) pour l'e-mail
- `python-dotenv` pour la config en local (sur GitHub Actions, la config vient des variables d'environnement / Secrets)
- Stockage de l'état : fichier `seen.json` **commité dans le dépôt** par le workflow après chaque exécution
- Exécution planifiée : **GitHub Actions** (cron)

## Structure prévue

```
AlerteLogement/
├── CLAUDE.md
├── requirements.txt              # requests, beautifulsoup4, python-dotenv
├── .env.example                  # modèle de config (commité, sans vraies valeurs)
├── .env                          # config locale avec mots de passe (NE JAMAIS commiter)
├── .gitignore                    # .env, *.log, .venv/, __pycache__/  (PAS seen.json)
├── .github/workflows/alerte.yml  # workflow planifié
├── alerte.py                     # point d'entrée : un cycle (fetch → filtre → mail → sauvegarde)
├── scraper.py                    # récupération + parsing des pages
├── notifier.py                   # envoi de l'e-mail
└── seen.json                     # état persistant (commité par le workflow)
```

⚠️ **Le dépôt est public** : tout ce qui est commité est visible par tous. Aucun mot de passe, adresse
e-mail ou donnée perso dans le code, `.env.example`, les logs ou `seen.json`. Les identifiants vont
uniquement dans les **Secrets** GitHub.

## Ce qu'on sait du site (vérifié le 2026-10-15)

**URL de liste :** `https://www.frances-immobilier.com/fr/annonces/louer-p-r70-5-{N}.html` où `{N}` = numéro de page (1, 2, 3…).

⚠️ **Les paramètres `prixmin`, `prixmax` et `tri` de l'URL sont IGNORÉS par le serveur.** L'URL donnée
par l'utilisateur (avec `#menuSave=...&prixmin=350&prixmax=500`) renvoie des annonces à 650 €, 715 €,
2 474 €… Le filtrage est fait en JS côté navigateur. → **Il faut récupérer toutes les pages et filtrer
le prix nous-mêmes en Python.**

**Pagination :** ~10 annonces par page, environ 3 pages au total. Au-delà de la dernière page, le site ne
renvoie pas une page vide mais une page avec 1 annonce déjà vue. → Arrêter la boucle quand une page
n'apporte **aucun identifiant nouveau** (et mettre une limite de sécurité, ex. 20 pages).

**Structure HTML d'une annonce :**
- Bloc conteneur : `div.liste-bien-container`
- Lien + identifiant unique : `a[href*="detail.htm?cle="]` → ex. `https://www.frances-immobilier.com/fr/detail.htm?cle=341682669&monnaie=2`.
  Le paramètre `cle` est l'**ID unique** à stocker dans `seen.json`.
- Prix : `div.liste-bien-price` → texte du type `Loyer : 650.00 €* CC` ou `Loyer : 2,474.00 €*`.
  Format anglo-saxon : la **virgule est le séparateur de milliers**, le point est la décimale.
  Parsing : extraire `[\d.,]+`, retirer les virgules, `float()`.
- Ville/type : attribut `alt` de l'image (`location Appartement Montpellier`) et le titre dans `div.liste-bien-description`.
- Statut « Loué » : dans le `<script>` du bloc, la ligne `if(JsConfig.Bandeau.Vendu && 'X'=='1')` —
  si `X == '1'`, le bien est loué/vendu → **ignorer**.
- Le JSON-LD (`application/ld+json`) de la page **n'est pas fiable** (même prix pour toutes les offres) : ne pas l'utiliser.

**Encodage :** la page est en Windows-1252. La détection automatique de BeautifulSoup se trompe (cp1250 :
« Philipidčs », « m˛ ») → décoder explicitement `resp.content.decode("cp1252")` avant de parser.

**Types de biens :** la liste mélange appartements, parkings, garages, bureaux et locaux commerciaux
(`.liste-bien-type`). On exclut les types contenant `parking`, `garage`, `box`, `cave`, `bureau`, `local`,
`terrain`, `entrepôt` (`TYPES_EXCLUS` dans `scraper.py`) : un garage à 400 € ne doit pas déclencher d'alerte.

**Politesse :** User-Agent de navigateur réaliste, `timeout=20`, petite pause (1–2 s) entre les pages,
pas plus d'un cycle toutes les 10 minutes.

## Configuration

Lue depuis les variables d'environnement (`os.environ`). En local, `load_dotenv()` les charge depuis `.env` ;
sur GitHub Actions, elles sont injectées par le workflow depuis les **Secrets** du dépôt
(Settings → Secrets and variables → Actions) : `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_TO`.
Les valeurs non sensibles (`PRIX_MIN`, `PRIX_MAX`, `SMTP_HOST`, `SMTP_PORT`) ont des valeurs par défaut dans le code.

```
PRIX_MIN=300
PRIX_MAX=520

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=adresse.expediteur@gmail.com
SMTP_PASSWORD=mot_de_passe_application   # Gmail : "mot de passe d'application", pas le mot de passe normal
MAIL_TO=adresse.destinataire@example.com
```

Ne jamais écrire d'identifiants en dur dans le code ni les afficher dans les logs.

## Comportement attendu

1. **Premier lancement** : remplir `seen.json` avec toutes les annonces actuelles *sans* envoyer de mail
   pour celles hors fourchette ; pour celles déjà dans la fourchette, envoyer **un mail récapitulatif**
   (option `--init-silencieux` pour tout marquer comme vu sans rien envoyer).
2. **Cycles suivants** : pour chaque logement (type non exclu) `PRIX_MIN <= prix <= PRIX_MAX`, non loué, dont la `cle`
   n'est pas dans `seen.json` → l'ajouter à la liste à notifier.
3. S'il y a des nouveautés : **un seul e-mail** les regroupant (objet : `🏠 N nouveau(x) logement(s) à XXX €`),
   corps HTML + texte avec prix, ville, lien cliquable.
4. N'ajouter les `cle` à `seen.json` **qu'après** un envoi réussi (sinon on retentera au prochain cycle).
5. Écriture de `seen.json` atomique (écrire dans un `.tmp` puis `os.replace`).
6. Si le scraping trouve **0 annonce** au total → probablement un changement de structure du site ou un blocage
   des IP GitHub : journaliser un WARNING et envoyer un mail d'alerte technique **au maximum une fois par 24 h**
   (stocker la date du dernier mail d'alerte dans `seen.json`, ex. clé `derniere_alerte_technique`).
7. `alerte.py` exécute **un seul cycle puis s'arrête** (pas de boucle infinie : c'est GitHub Actions qui relance).
   Code de sortie 0 même si le site est injoignable (on ne veut pas un mail d'échec GitHub toutes les 15 min) ;
   code ≠ 0 seulement en cas de vraie erreur de config (secret manquant, SMTP refusé).

Format de `seen.json` :
```json
{ "vues": { "341682669": "2026-10-15T17:46:00Z" }, "derniere_alerte_technique": null }
```
Purger les entrées de plus de 90 jours pour que le fichier ne grossisse pas indéfiniment.

## Fonctionnement 24h/24 : GitHub Actions

Fichier `.github/workflows/alerte.yml` :

```yaml
name: Alerte logement

on:
  schedule:
    - cron: "*/15 * * * *"     # toutes les 15 min (UTC) — GitHub peut retarder de 5 à 30 min
  workflow_dispatch:            # bouton "Run workflow" pour lancer à la main

permissions:
  contents: write               # nécessaire pour commiter seen.json

concurrency:
  group: alerte-logement        # jamais deux exécutions en parallèle (sinon conflit sur seen.json)
  cancel-in-progress: false

jobs:
  verifier:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - run: python alerte.py
        env:
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
          MAIL_TO: ${{ secrets.MAIL_TO }}
      - name: Sauvegarder seen.json
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add seen.json
          git diff --cached --quiet || (git commit -m "maj seen.json" && git push)
```

Points d'attention :
- Le cron est en **UTC** et n'est **pas précis** (retards fréquents aux heures chargées). Acceptable ici.
- GitHub **désactive les workflows planifiés après 60 jours sans activité** sur un dépôt public. Les commits
  de `seen.json` comptent normalement comme activité, mais si GitHub envoie un mail de désactivation, il
  suffit de réactiver le workflow dans l'onglet Actions.
- Le site peut bloquer les IP des serveurs GitHub : vérifier les logs du premier run (nombre d'annonces > 0).
- Ne jamais faire de `print` des secrets. GitHub les masque dans les logs, mais il ne faut pas compter dessus.
- Tous les chemins dans le code sont relatifs à `Path(__file__).parent`.

## Commandes (en local, pour développer et tester)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python alerte.py                 # un cycle réel (mail + mise à jour de seen.json)
.venv\Scripts\python alerte.py --dry-run       # affiche ce qui serait envoyé, sans mail ni écriture de seen.json
.venv\Scripts\python alerte.py --test-mail     # envoie un mail de test pour valider le SMTP
.venv\Scripts\python alerte.py --init-silencieux  # marque tout comme vu sans envoyer de mail
```

Mise en ligne : créer le dépôt public sur GitHub, ajouter les 3 secrets, pousser, puis lancer une première
fois à la main via Actions → « Alerte logement » → *Run workflow*.

## Journalisation

Module `logging` vers la **console uniquement** (stdout) : sur GitHub Actions, les logs sont visibles dans
l'onglet Actions. Pas de fichier de log commité (dépôt public).
À chaque cycle, une ligne INFO : nombre de pages lues, nombre d'annonces, nombre dans la fourchette, nombre de nouvelles.

## Conventions

- Code et commentaires en français, noms de variables en français ou anglais mais cohérents.
- Fonctions courtes et testables : `parse_prix(texte) -> float | None`, `parse_page(html) -> list[Annonce]`,
  `filtrer(annonces, min, max)`, `nouvelles(annonces, seen)`.
- `Annonce` = `dataclass` (`cle`, `prix`, `titre`, `ville`, `url`, `louee`).
- Tester `parse_page` sur un HTML enregistré localement plutôt que de taper le site à chaque test.
