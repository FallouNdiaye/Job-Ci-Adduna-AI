# Documentation backend — Job Ci Adduna AI

## 1. Architecture

Le backend est construit avec Python, FastAPI, Pydantic et SQLite. Les routes API sont préfixées par `/api` selon le routeur auquel elles appartiennent. Les collecteurs normalisent les données externes avant de les intégrer aux modules correspondants.

Répertoires importants :
- `backend/app/` : API, logique métier, collecteurs et synchronisations.
- `backend/tests/` : tests unitaires, API et collecteurs.
- `backend/requirements.txt` : dépendances principales.
- `backend/requirements-collectors.txt` : connecteurs optionnels.
- `backend/requirements-ocr.txt` : dépendances OCR déclarées.
- `backend/.env.example` : modèle de configuration, sans secrets personnels.

## 2. Modules backend

| Module | Rôle |
|---|---|
| `main.py` | API principale, stockage des emplois, collecteurs et scheduler général |
| `doctoral.py` | Catalogue doctoral, sources académiques, financement et synchronisation |
| `immigration.py` | Catalogue local en lecture seule des voies de mobilité et d'immigration |
| `recruiters.py` | API des profils et offres de recruteurs |
| `recruiter_hn.py` | Collecte Hacker News « Who Is Hiring » |
| `recruiter_official.py` | Collecte prudente de pages officielles de recruteurs |
| `recruiter_sync.py` | Coordination de la synchronisation des recruteurs |
| `training_collector.py` | Collecteurs de formations et de financement |
| `espoir_jeunes_collector.py` | Collecteur associé à Espoir Jeunes |
| `trainings.py` | API et persistance du catalogue de formations |

La liste est susceptible d'évoluer. Se référer au code du dépôt pour les noms et responsabilités exacts de la version locale.

## 3. Routes API connues

### Santé, profil et emplois
- `GET /api/health`
- `GET /api/profile`
- `GET /api/sources`
- `GET /api/jobs`
- `POST /api/jobs`
- `DELETE /api/jobs/{job_id}`
- `PATCH /api/jobs/{job_id}/application`
- `POST /api/drafts`
- `GET /api/stats`
- `GET /api/sync/status`
- `POST /api/sync/run`

### Doctorats et recherche
- `GET /api/doctorates`
- `GET /api/doctorates/sources`
- `POST /api/doctorates`
- `PATCH /api/doctorates/{doctorate_id}`
- `POST /api/doctorates/sync`

### Immigration
- `GET /api/immigration`

Cette route renvoie un catalogue défini dans le code et ne lance pas de collecte réseau ni de modification SQLite.

### Recruteurs
- `GET /api/recruiters`
- `GET /api/recruiters/offers`
- `GET /api/recruiters/{recruiter_id}`
- `POST /api/recruiters`
- `POST /api/recruiters/offers`

### Formations
- `GET /api/trainings`
- `GET /api/trainings/sources`
- `POST /api/trainings`
- `PATCH /api/trainings/{training_id}`

Vérifier la liste effective dans `http://127.0.0.1:8000/docs`. Les méthodes et préfixes peuvent être affectés par les routeurs montés dans l'application.

## 4. Base de données

Le chemin prévu dans la configuration courante est :

```text
./jobhunter.db
```

Il est défini par `JOBHUNTER_DB=./jobhunter.db` dans l'environnement backend. Un ancien fichier `backend/jobhunter.db` a été observé lors des travaux : ne pas le confondre avec la base active.

Avant toute opération sur la base :
1. Vérifier la valeur effective de `JOBHUNTER_DB` et la réponse de `/api/health`.
2. Arrêter toute opération destructive envisagée et réaliser une sauvegarde horodatée.
3. Préserver les offres, candidatures, financements, échéances, recruteurs et formations existants.

Les bases SQLite, les fichiers `.env` et les sauvegardes ne doivent pas être ajoutés au dépôt Git.

## 5. Synchronisations

Les schedulers sont distincts :
- emplois : `AUTO_SYNC_ENABLED`, `SYNC_INTERVAL_MINUTES` ;
- doctorats : `DOCTORAL_AUTO_SYNC_ENABLED`, `DOCTORAL_SYNC_INTERVAL_HOURS` ;
- recruteurs : `RECRUITER_AUTO_SYNC_ENABLED`, `RECRUITER_SYNC_INTERVAL_HOURS` ;
- formations : `TRAINING_AUTO_SYNC_ENABLED`, `TRAINING_SYNC_INTERVAL_HOURS`.

Valeurs usuelles documentées : 60 minutes pour les emplois, 24 heures pour les doctorats, 6 heures pour les recruteurs et 24 heures pour les formations. La configuration réellement chargée doit être vérifiée avant d'affirmer qu'un scheduler est actif.

Les synchronisations automatiques font partie du comportement attendu du projet et ne doivent pas être désactivées par un changement documentaire. Une collecte manuelle peut effectuer des requêtes réseau et doit être explicitement voulue.

## 6. Qualité et protection des données

Le projet comprend notamment :
- normalisation des données d'offres ;
- nettoyage de descriptions contenant du HTML ;
- déduplication d'offres ;
- contrôles de taille et d'hôtes dans plusieurs collecteurs ;
- classification des statuts de financement ;
- logique de préservation de champs déjà renseignés lors des mises à jour.

La couverture exacte varie selon le collecteur. Ne pas prétendre que toutes les sources ont les mêmes garanties.

## 7. Tests

Depuis la racine :

```bash
PYTHONPATH="$PWD/backend" \
  backend/.venv/bin/python -m pytest -q
```

Tests des formations :

```bash
PYTHONPATH="$PWD/backend" \
  backend/.venv/bin/python -m pytest -q \
  backend/tests/test_trainings_api.py \
  backend/tests/test_training_collector.py \
  backend/tests/test_espoir_jeunes_collector.py
```

Tests ciblés supplémentaires :

```bash
PYTHONPATH="$PWD/backend" \
  backend/.venv/bin/python -m pytest -q \
  backend/tests/test_immigration_api.py \
  backend/tests/test_recruiter_official.py \
  backend/tests/test_recruiter_sync.py \
  backend/tests/test_recruiter_hn.py \
  backend/tests/test_recruiters_api.py
```

Ne pas annoncer un nombre de tests réussis sans disposer de la sortie pytest correspondante.
