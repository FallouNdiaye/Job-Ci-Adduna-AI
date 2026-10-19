# Job Ci Adduna AI — Les opportunités du Sénégal au monde

Application locale React + TypeScript + Vite, API FastAPI et SQLite. Le tableau de bord conserve les thèmes clair/sombre, le suivi de candidature et les brouillons d'e-mail/lettre, et ajoute la collecte de vraies annonces depuis des API publiques et des endpoints de recrutement publics.

## Collecte intégrée
- **Arbeitnow Job Board API** : annonces accessibles via son endpoint public.
- **Remotive API** : offres télétravail recherchées par mots-clés Java, Spring Boot et Angular.
- **Greenhouse** : endpoints publics de tableaux de carrières, activés en renseignant `GREENHOUSE_BOARDS` avec les slugs des entreprises.
- **Lever** : endpoints publics de tableaux de carrières, activés via `LEVER_SITES`.
- Synchronisation automatique au démarrage, puis selon `SYNC_INTERVAL_MINUTES` (60 minutes par défaut), et bouton **Collecter maintenant** dans le dashboard.
- Historique de la dernière synchronisation, état par source, erreurs de sources, nombre d'offres ajoutées/mises à jour.
- Déduplication par URL canonique et identifiant/source lorsqu'il est disponible.
- Champs source, URL d'origine, date de publication lorsqu'elle est fournie, et date de collecte.
- Matching indicatif avec explication du score, compétences détectées et compétences non détectées.

**Important :** disponibilité et champs retournés dépendent des fournisseurs et peuvent changer. Une date absente est affichée comme non fournie plutôt que d'être inventée. La fréquence de synchronisation n'est pas une garantie de publication en temps réel. Les collecteurs n'essaient pas de contourner les authentifications, CAPTCHA ou protections anti-bot. Vérifiez les conditions d'utilisation de chaque source avant usage soutenu.

## Lancer sous Ubuntu

### 1. Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
API : `http://127.0.0.1:8000/api/health`
Swagger : `http://127.0.0.1:8000/docs`

Le backend charge automatiquement le fichier `.env` s'il existe. Les variables d'environnement déjà définies dans le shell restent prioritaires.

### 2. Frontend
Dans un second terminal :
```bash
cd frontend
npm install
npm run dev
```
Ouvrez l'URL Vite affichée, habituellement `http://127.0.0.1:5173`.

### 3. Tester la collecte
La collecte se lance automatiquement au démarrage du backend. Pour lancer manuellement :
```bash
curl -X POST http://127.0.0.1:8000/api/sync/run
```
État et dernière synchronisation :
```bash
curl http://127.0.0.1:8000/api/sync/status
```
Documentation interactive : `http://127.0.0.1:8000/docs`.

### 4. Connecter des tableaux de carrières
Dans le terminal avant de démarrer le backend, par exemple :
```bash
export GREENHOUSE_BOARDS="slug1,slug2"
export LEVER_SITES="slug1,slug2"
```
Remplacez les slugs par les identifiants réellement utilisés par les pages carrière des employeurs. Ces sources sont facultatives; Arbeitnow et Remotive sont configurées par défaut.

### Tests backend
```bash
cd backend
source .venv/bin/activate
pytest -q
```

## Fonctionnement et sécurité
- La base active prévue est `./jobhunter.db` à la racine du projet, selon `JOBHUNTER_DB` dans `backend/.env`. Un ancien fichier `backend/jobhunter.db` peut subsister : ne pas le confondre avec la base active.
- Le statut et les notes de candidature sont conservés lors des mises à jour d'offres existantes.
- Les brouillons de lettre et d'e-mail restent à vérifier. Aucune candidature ou aucun e-mail n'est envoyé automatiquement.
- Le matching est une heuristique explicable basée sur le texte publié; il ne remplace pas une lecture humaine de l'annonce.
- Ne placez jamais de clé privée dans le frontend ou dans une variable `VITE_*`.

## Filtres de pertinence et mobilité

L’interface propose maintenant des filtres par métier (Full Stack / mobile), pays (Sénégal / international), mode de travail (télétravail complet, hybride, sur site) et mobilité internationale. Les annonces sont classées comme « prise en charge de la mobilité mentionnée » uniquement lorsqu’une expression explicite relative à la relocalisation, au visa ou aux frais de déplacement est détectée dans le texte disponible. Cela reste à confirmer auprès du recruteur : une annonce internationale ne garantit pas un visa ou un billet d’avion.

Le brouillon de candidature essaie de reconnaître la langue de l’annonce et prépare le courriel/la lettre en français ou en anglais. Il propose le PDF de CV correspondant. L’envoi n’est pas automatisé : validation humaine obligatoire.

CVs locaux éventuels dans `frontend/public/cv/` (PDF exclus de Git par défaut) :
- `CV_Fallou_Ndiaye_FR.pdf` : version française corrigée fournie dans les fichiers de travail.
- `CV_Fallou_Ndiaye_EN.pdf` : traduction anglaise du CV français corrigé, générée en conservant la structure et le style du document source.

Vérifiez le contenu des CVs avant chaque candidature et mettez à jour les deux versions ensemble.

## Collecteurs complémentaires (optionnels)

Les connecteurs optionnels sont **désactivés par défaut** afin d'éviter de déclencher des collectes coûteuses ou non configurées. Le dashboard garde les diagnostics de chaque source et indique lorsqu'une intégration n'est pas configurée.

### Installer les dépendances complémentaires

```bash
cd backend
source .venv/bin/activate
pip install -r requirements-collectors.txt
```

Redémarrez ensuite le backend après avoir configuré `backend/.env`.

- **JobSpy (`python-jobspy`)** : intégration optionnelle de `scrape_jobs()` avec mots-clés, localisation et `hours_old` (720 h = 30 jours). Configurez `JOBSPY_ENABLED=true`, `JOBSPY_SITES`, `JOBSPY_SEARCH_TERMS`, `JOBSPY_LOCATION` et `JOBSPY_HOURS_OLD`. Commencez avec un seul site et un faible nombre de résultats. Ce connecteur n'est pas lancé tant qu'il n'est pas activé.
- **Hirehunt** : intégration optionnelle avec sources configurables et stratégie de retry/rate policy. Configurez `HIREHUNT_ENABLED=true`, `HIREHUNT_SOURCES`, `HIREHUNT_SEARCH_TERMS` et `HIREHUNT_LOCATION`. La couverture varie selon les sources disponibles et leur pays.
- **Remote Jobs API** : le package agrège Remotive, RemoteOK, We Work Remotely, Jobicy et Hacker News en un schéma commun. Pour le lancer localement après installation des dépendances optionnelles, exécutez `remote-jobs-api --serve --port 8321`, puis renseignez `REMOTE_JOBS_API_URL=http://127.0.0.1:8321/v1/jobs?skills=Java,Spring%20Boot,Angular,Flutter&limit=100`. JobHunter consomme alors cet endpoint local; le service peut aussi être lancé indépendamment.
- **Crawl4AI** : crawl de pages carrière publiques dont les URL sont explicitement listées dans `CRAWL4AI_SEED_URLS`. Cette intégration extrait les annonces exposées en JSON-LD `JobPosting`; elle ne garantit pas l'extraction de toutes les pages ni des sites qui ne publient pas ce format.
- **ScrapeGraphAI** : extraction structurée assistée par LLM sur les URL listées dans `SCRAPEGRAPHAI_URLS`. Configurez `SCRAPEGRAPHAI_ENABLED=true`, `LLM_API_KEY` et `LLM_MODEL`. L'appel à un modèle peut entraîner des coûts selon le fournisseur configuré.
- **Jobicy API** : ajoutée comme source publique complémentaire pour des annonces remote récentes.

### À propos du nom « jobdrop »

Je n'ai pas pu vérifier un package Python public appelé exactement `jobdrop` qui corresponde à la signature `scrape_jobs(..., hours_old=...)` décrite. L'API de ce type que j'ai pu identifier est celle de **JobSpy** (`python-jobspy`). L'intégration du projet est donc nommée JobSpy et non « jobdrop » pour éviter de prétendre utiliser un package non vérifié.

### Accès, conformité et qualité des données

Ces intégrations ne signifient pas « toutes les annonces partout ». Certaines sources exigent un compte, une clé ou une autorisation; d'autres limitent la fréquence, la couverture géographique ou la réutilisation. N'activez que les sources dont les conditions permettent votre usage, ne contournez pas les connexions, CAPTCHA, protections anti-bot ou restrictions d'accès. Le paramètre de fraîcheur est appliqué par la source quand elle le prend en charge, sinon il est limité par les données disponibles. Les résultats restent soumis à normalisation, déduplication et vérification humaine.

Pour consulter les connecteurs et leur configuration actuelle : `GET http://127.0.0.1:8000/api/sources`.


### ScrapeGraphAI Cloud (optionnel)

Le connecteur utilise le SDK officiel `scrapegraph-py` et la variable `SGAI_API_KEY`. Pour l'utiliser, configurez la clé uniquement dans `backend/.env`, activez `SCRAPEGRAPHAI_ENABLED=true` et renseignez `SCRAPEGRAPHAI_URLS` avec des URL publiques. Ne placez jamais de clé API dans le code, le README ou un dépôt Git. Si une clé est exposée, révoquez-la chez le fournisseur et remplacez-la. Le connecteur ne découvre pas automatiquement toutes les plateformes d'emploi; les extractions IA doivent être vérifiées avant toute candidature.


## Configuration ScrapeGraphAI et sources d'emploi

La configuration réelle de ScrapeGraphAI dépend de l'environnement local. Gardez `backend/.env` hors du dépôt Git et ne partagez jamais ses secrets. Vérifiez la validité et les autorisations de toute clé API dans le tableau de bord du fournisseur.

Les URLs configurées couvrent des sources sénégalaises (Senjob, SeneJobs, service public/Tabax Sénégal) et internationales/remote (Remotive, We Work Remotely, Remote OK, Jobicy). Les connecteurs API publics déjà intégrés restent les plus fiables pour les sources qui les proposent; l'extraction IA dépend de la disponibilité, de la structure des pages et des conditions d'accès de chaque site. Les sources ne garantissent pas que chaque page racine contienne des offres exploitables.

Pour lancer :

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-collectors.txt
uvicorn app.main:app --reload
```

`backend/.env` est local et ne doit pas être commité. L'application utilise une collecte périodique et doit respecter les conditions d'utilisation, les règles d'accès et les limites de chaque source.
