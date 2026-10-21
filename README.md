# Job Ci Adduna AI

**Application locale de veille et de gestion d'opportunités professionnelles, académiques et de mobilité internationale.**

Job Ci Adduna AI regroupe dans une interface en français des offres d'emploi, des opportunités de recherche et de doctorat, des bourses et financements, des profils de recruteurs, des formations et des informations sur les parcours d'immigration. Le projet dispose d'un backend FastAPI, d'une interface React/Vite et d'une base SQLite locale.

> **Important :** l'intégration d'un collecteur ne garantit pas que sa source soit accessible, activée ou fournisse des résultats. Les informations de financement, les échéances, les conditions d'éligibilité et les procédures d'immigration doivent être vérifiées sur les sites officiels.

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Démarrage](#démarrage)
- [API](#api)
- [Collectes et synchronisations](#collectes-et-synchronisations)
- [Tests](#tests)
- [Sécurité et limites](#sécurité-et-limites)
- [Documentation détaillée](#documentation-détaillée)

## Fonctionnalités

### Emplois et candidatures
- Consultation, recherche et filtrage des offres collectées.
- Ciblage des métiers informatiques, notamment Full Stack, backend, développement web et mobile.
- Critères de recherche liés au pays, au mode de travail et à la mobilité lorsque les données disponibles le permettent.
- Score de correspondance heuristique avec le profil.
- Ajout manuel et suppression d'offres.
- Suivi de l'état des candidatures.
- Préparation de brouillons d'e-mails et de lettres de motivation.

**Les brouillons ne sont pas envoyés automatiquement.** La candidature finale reste sous le contrôle de l'utilisateur.

### Doctorats, recherche et financements
- Catalogue distinct des opportunités doctorales et académiques.
- Sources RSS/Atom et collecteurs institutionnels.
- Recherche et filtres par domaine, pays et statut de financement.
- Présentation des éléments disponibles sur le financement et les échéances.
- Répertoire de programmes et de bourses à examiner.
- Statuts de financement : `CONFIRMED_FULL`, `PARTIAL`, `UNCONFIRMED` et `UNKNOWN`.

La présence d'un salaire, d'une bourse ou d'une mention de financement ne suffit pas à prouver qu'un programme couvre tous les frais.

### Formations et appels à candidatures
- Module dédié aux formations et programmes de financement.
- Collecteurs associés à FORCE-N, aux financements 3FPT et à Espoir Jeunes.
- Consultation des sources, des descriptions et des liens officiels disponibles.
- Conservation des informations déjà collectées, notamment les échéances et les éléments de financement.

Les échéances et liens de candidature peuvent être absents si les publications sources ne les fournissent pas ou si leur extraction n'est pas confirmée.

### Recruteurs
- Profils de recruteurs séparés des offres générales.
- Offres associées à un recruteur lorsqu'une annonce individuelle est détectée.
- Sources Hacker News « Who Is Hiring » et sites officiels configurés.
- Synchronisation périodique et gestion des erreurs de sources.

Un profil de recruteur ne signifie pas qu'une offre ouverte a été trouvée.

### Immigration et mobilité internationale
- Catalogue informatif de parcours officiels.
- Voies liées à l'Allemagne, au Canada, à la France, aux Pays-Bas, à l'Union européenne, à l'Irlande et aux États-Unis.
- Green Card fondée sur l'emploi, Diversity Visa (loterie annuelle), H-1B et L-1B.
- Liens vers les autorités officielles et rappels sur les critères à vérifier.
- Accès aux opportunités académiques et financements depuis l'interface de mobilité.

Ce catalogue n'est ni un système de dépôt de demande de visa ni une garantie d'admissibilité. Les dates et critères doivent être vérifiés auprès de l'autorité compétente.

## Architecture

| Composant | Technologie | Répertoire |
|---|---|---|
| API | Python, FastAPI, Pydantic | `backend/app/` |
| Base de données | SQLite | `./jobhunter.db` selon la configuration |
| Interface | React, TypeScript, Vite | `frontend/src/` |
| Collecteurs | HTTP, flux RSS/Atom, API et extraction HTML selon la source | `backend/app/` |
| Tests | pytest | `backend/tests/` |
| Documentation | Markdown | `docs/` |

L'interface utilise `VITE_API_URL` si cette variable est définie. Sinon, elle utilise `http://127.0.0.1:8000/api`.

## Installation

### Prérequis

- Ubuntu/Linux ou environnement compatible.
- Python compatible avec les dépendances du projet.
- Node.js et npm compatibles avec la version de Vite installée.
- Accès réseau pour les sources en ligne.
- Le dépôt et, pour les commandes Python ci-dessous, l'environnement virtuel `backend/.venv/`.

### Backend

Depuis la racine du projet :

```bash
cd "$HOME/Téléchargements/Job Ci Adduna AI"

# Créer l'environnement seulement s'il n'existe pas.
python3 -m venv backend/.venv

backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

Certaines intégrations supplémentaires sont facultatives :

```bash
backend/.venv/bin/python -m pip install -r backend/requirements-collectors.txt
```

Consulter `backend/requirements-ocr.txt` pour les dépendances OCR déclarées. Vérifier les versions et la compatibilité avant toute installation complémentaire.

### Frontend

```bash
cd "$HOME/Téléchargements/Job Ci Adduna AI/frontend"
npm install
```

## Configuration

Le modèle de configuration est `backend/.env.example`. Le backend lit les variables d'environnement et le fichier `.env` selon son code de démarrage.

Paramètres principaux :

| Variable | Rôle |
|---|---|
| `JOBHUNTER_DB` | Chemin de la base SQLite |
| `CORS_ORIGINS` | Origines frontend autorisées |
| `AUTO_SYNC_ENABLED` | Active/désactive la synchronisation générale |
| `SYNC_INTERVAL_MINUTES` | Intervalle de synchronisation des emplois |
| `COLLECTOR_HTTP_TIMEOUT` | Délai maximal des requêtes des collecteurs |
| `GREENHOUSE_BOARDS` | Tableaux Greenhouse configurés |
| `LEVER_SITES` | Sites Lever configurés |
| `DOCTORAL_AUTO_SYNC_ENABLED` | Synchronisation doctorale |
| `DOCTORAL_SYNC_INTERVAL_HOURS` | Intervalle doctoral |
| `JOBSPY_ENABLED` | Active le connecteur JobSpy |
| `HIREHUNT_ENABLED` | Active le connecteur Hirehunt |
| `CRAWL4AI_ENABLED` | Active le connecteur Crawl4AI |
| `SCRAPEGRAPHAI_ENABLED` | Active le connecteur ScrapeGraphAI |
| `SGAI_API_KEY` | Clé secrète du service ScrapeGraphAI |
| `REMOTE_JOBS_API_URL` | URL explicite d'un service Remote Jobs API |
| `VITE_API_URL` | URL de l'API utilisée par le frontend |

Les connecteurs optionnels sont désactivés par défaut dans le modèle d'environnement. Leur activation peut exiger des dépendances, une configuration, une clé ou des crédits.

**Ne jamais versionner `backend/.env`, les clés API, les bases de données ou les informations personnelles.** Ne pas remplacer le chemin de la base active sans sauvegarde et vérification.

## Démarrage

Terminal 1 — backend :

```bash
cd "$HOME/Téléchargements/Job Ci Adduna AI"
PYTHONPATH="$PWD/backend" \
  backend/.venv/bin/python -m uvicorn app.main:app \
  --app-dir "$PWD/backend" --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend :

```bash
cd "$HOME/Téléchargements/Job Ci Adduna AI/frontend"
npm run dev
```

Adresses locales usuelles :

- Interface : `http://127.0.0.1:5173`
- Santé API : `http://127.0.0.1:8000/api/health`
- Documentation interactive : `http://127.0.0.1:8000/docs`

Vérifier le chemin de la base renvoyé par l'endpoint de santé avant toute opération de maintenance. Ne pas supprimer ni recréer la base pour résoudre un problème de démarrage.

## API

Les routes exposées incluent notamment :

| Module | Routes principales |
|---|---|
| Santé et configuration | `GET /api/health`, `GET /api/profile`, `GET /api/sources` |
| Emplois | `GET /api/jobs`, `POST /api/jobs`, `DELETE /api/jobs/{job_id}` |
| Candidatures | `PATCH /api/jobs/{job_id}/application` |
| Brouillons | `POST /api/drafts` |
| Statistiques | `GET /api/stats` |
| Synchronisation générale | `GET /api/sync/status`, `POST /api/sync/run` |
| Doctorats | `GET/POST /api/doctorates`, `PATCH /api/doctorates/{doctorate_id}`, `GET /api/doctorates/sources`, `POST /api/doctorates/sync` |
| Immigration | `GET /api/immigration` |
| Recruteurs | `GET/POST /api/recruiters`, `GET /api/recruiters/{recruiter_id}`, `GET/POST /api/recruiters/offers` |
| Formations | `GET /api/trainings`, `GET /api/trainings/sources`, `POST /api/trainings`, `PATCH /api/trainings/{training_id}` |

La liste exacte doit être vérifiée dans `/docs` pour la version exécutée. Les routes sont présentées avec leurs méthodes connues dans le code et ne constituent pas une garantie de disponibilité si le serveur ne démarre pas.

## Collectes et synchronisations

Le projet sépare les offres d'emploi ordinaires, les opportunités doctorales, les recruteurs et les formations.

Les intervalles configurés dans le code/environnement sont généralement :
- Emplois : 60 minutes, avec une limite minimale de prudence.
- Doctorats : 24 heures.
- Recruteurs : 6 heures.
- Formations : 24 heures.

Les valeurs effectives dépendent de la configuration et du démarrage du backend. Une synchronisation planifiée peut échouer, être bloquée par une source ou se terminer sans nouvelle offre. Consulter les logs et l'état de synchronisation plutôt que d'interpréter un compteur nul comme une preuve d'absence d'offres.

Les collecteurs doivent respecter les politiques d'accès des sources, valider les URL et limiter la taille des réponses et le nombre de pages. Aucun contournement de protection anti-bot n'est prévu.

## Tests

Depuis la racine du dépôt :

```bash
PYTHONPATH="$PWD/backend" \
  backend/.venv/bin/python -m pytest -q
```

Tests ciblés des modules formations :

```bash
PYTHONPATH="$PWD/backend" \
  backend/.venv/bin/python -m pytest -q \
  backend/tests/test_trainings_api.py \
  backend/tests/test_training_collector.py \
  backend/tests/test_espoir_jeunes_collector.py
```

Construction frontend :

```bash
cd "$HOME/Téléchargements/Job Ci Adduna AI/frontend"
npm run build
```

Les résultats de tests historiques ne remplacent pas une nouvelle exécution. Documenter la date, la commande et le résultat réel après chaque vérification.

## Sécurité et limites

- Les sources externes peuvent être indisponibles, modifiées, limitées ou vides.
- Les statuts de financement incertains doivent rester explicitement incertains.
- Les échéances et liens de candidature ne doivent pas être inventés.
- Les procédures de visa et de loterie sont susceptibles de changer.
- Les brouillons de candidature ne sont pas des candidatures envoyées.
- Les synchronisations automatiques doivent rester activées selon les réglages voulus.
- Faire une sauvegarde avant de modifier le code ou la base.
- Ne jamais effacer les données d'offres, de candidatures, de recruteurs, de formations ou de financement pour résoudre un problème documentaire.

## Documentation détaillée

- [État fonctionnel du projet](docs/ETAT_FONCTIONNEL_JOB_CI_ADDUNA_AI.md)
- [Documentation frontend](docs/FRONTEND.md)
- [Documentation backend et API](docs/BACKEND.md)
- [Collecteurs, sources et synchronisations](docs/COLLECTEURS_ET_SYNCHRONISATION.md)
- [Installation, configuration et tests](docs/INSTALLATION_ET_CONFIGURATION.md)
- [Inventaire technique généré](docs/INVENTAIRE_TECHNIQUE_AUTOMATIQUE.md)

## Statut du projet

Le dépôt évolue par intégrations successives. Seuls les tests exécutés sur le commit concerné attestent du résultat correspondant. La présence d'un fichier, d'une route ou d'une configuration n'est pas une preuve que la fonctionnalité fonctionne en production.

## Documentation automatique et commits

Le dépôt fournit un hook Git versionné dans `.githooks/pre-commit`.
Il régénère `docs/INVENTAIRE_TECHNIQUE_AUTOMATIQUE.md` et ajoute
ce fichier à l'index avant chaque commit.

Activation locale, depuis la racine du dépôt :

```bash
git config core.hooksPath .githooks
```

Pour régénérer manuellement l'inventaire :

```bash
python3 scripts/generate_technical_docs.py
```

Le hook actualise l'inventaire technique ; il ne remplace pas la mise à
jour manuelle des descriptions fonctionnelles. Les hooks Git doivent être
activés sur chaque clone. Aucune base de données ni synchronisation
d'offres n'est nécessaire pour générer cette documentation.

## Guide Git et fonctionnalités livrées

- [Guide de contribution Git](docs/GUIDE_CONTRIBUTION_GIT.md) : branche, commit, push et Pull Request.
- [Fonctionnalités livrées](docs/FONCTIONNALITES_LIVREES.md) : résumé généré depuis les commits et les fichiers modifiés.
- [Workflow de documentation GitHub Actions](.github/workflows/documentation-main.yml) : génération après un push sur `main`.

Le workflow régénère `docs/FONCTIONNALITES_LIVREES.md` et crée un commit automatique
uniquement si le document change. Pour autoriser sa publication, vérifier dans
GitHub : Settings → Actions → General → Workflow permissions → Read and write permissions.

Ce rapport est fondé sur les messages de commit et les chemins modifiés. Pour obtenir
une documentation fonctionnelle utile, rédiger des messages explicites et décrire dans
les Pull Requests le besoin, le comportement visible, les tests exécutés et les limites.
La génération de ces documents ne nécessite ni accès à la base de données ni
synchronisation des offres.

## Changelog et documentation automatiques

Le dépôt génère deux documents à partir du code et de l'historique Git :

- `docs/INVENTAIRE_TECHNIQUE_AUTOMATIQUE.md` : inventaire technique détecté dans le dépôt.
- `CHANGELOG.md` : historique des commits regroupé par date et catégorie.

Le hook versionné `.githooks/pre-commit` régénère ces deux documents et les
ajoute à l'index avant chaque commit. Il doit être activé dans chaque clone :

```bash
git config core.hooksPath .githooks
```

Génération manuelle :

```bash
python3 scripts/generate_technical_docs.py
python3 scripts/generate_changelog.py
```

Le changelog reflète l'historique Git disponible au moment où il est généré.
Comme le hook `pre-commit` s'exécute avant la création du nouveau commit,
ce dernier apparaîtra dans le changelog lors de la génération suivante.
Les descriptions fonctionnelles du README restent à maintenir manuellement.

La génération n'ouvre pas la base de données, ne lit pas les valeurs des
fichiers `.env` et ne lance aucune synchronisation d'offres.
