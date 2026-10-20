# Installation, configuration et tests

## 1. Répertoire et environnement

```bash
cd "$HOME/Téléchargements/Job Ci Adduna AI"
```

Backend : `backend/.venv/`
Frontend : `frontend/`
Modèle d'environnement : `backend/.env.example`
Base prévue : `./jobhunter.db` selon `JOBHUNTER_DB`.

## 2. Installer les dépendances

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

Pour les connecteurs facultatifs :

```bash
backend/.venv/bin/python -m pip install -r backend/requirements-collectors.txt
```

Le fichier `backend/requirements-ocr.txt` documente également des dépendances OCR. Les dépendances OCR peuvent déjà être déclarées dans les exigences principales ; vérifier les fichiers actuels avant de réinstaller ou de modifier les versions.

Frontend :

```bash
cd frontend
npm install
npm run build
```

## 3. Configuration

Copier le modèle vers `backend/.env` uniquement si ce fichier n'existe pas déjà. Ne jamais écraser un `.env` existant :

```bash
cd "$HOME/Téléchargements/Job Ci Adduna AI"
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "backend/.env créé à partir du modèle : vérifier les paramètres."
else
  echo "backend/.env existe déjà : aucun remplacement effectué."
fi
```

Ne pas partager les valeurs secrètes du fichier `.env`. Ne jamais placer une clé privée dans une variable frontend `VITE_*`.

### Variables importantes

- Base de données : `JOBHUNTER_DB`.
- Origines autorisées : `CORS_ORIGINS`.
- Synchronisation des emplois : `AUTO_SYNC_ENABLED`, `SYNC_INTERVAL_MINUTES`.
- Timeout des collecteurs : `COLLECTOR_HTTP_TIMEOUT`.
- Doctorats : `DOCTORAL_AUTO_SYNC_ENABLED`, `DOCTORAL_SYNC_INTERVAL_HOURS`, `DOCTORAL_FEEDS`.
- Recruteurs : `RECRUITER_AUTO_SYNC_ENABLED`, `RECRUITER_SYNC_INTERVAL_HOURS`.
- Formations : `TRAINING_AUTO_SYNC_ENABLED`, `TRAINING_SYNC_INTERVAL_HOURS`.
- Greenhouse et Lever : `GREENHOUSE_BOARDS`, `LEVER_SITES`.
- JobSpy, Hirehunt, Crawl4AI, ScrapeGraphAI : variables `*_ENABLED` et paramètres associés.
- Remote Jobs API : `REMOTE_JOBS_API_URL`.
- Frontend : `VITE_API_URL`.

Vérifier les valeurs par défaut et le traitement réel de chaque variable dans le code avant de changer la configuration.

## 4. Lancer les services

Backend, depuis la racine :

```bash
PYTHONPATH="$PWD/backend" \
  backend/.venv/bin/python -m uvicorn app.main:app \
  --app-dir "$PWD/backend" --host 127.0.0.1 --port 8000
```

Frontend, dans un autre terminal :

```bash
cd "$HOME/Téléchargements/Job Ci Adduna AI/frontend"
npm run dev
```

Adresses usuelles :
- Interface : `http://127.0.0.1:5173`
- Santé : `http://127.0.0.1:8000/api/health`
- Swagger : `http://127.0.0.1:8000/docs`

## 5. Tests

Tous les tests backend :

```bash
cd "$HOME/Téléchargements/Job Ci Adduna AI"
PYTHONPATH="$PWD/backend" backend/.venv/bin/python -m pytest -q
```

Formations :

```bash
PYTHONPATH="$PWD/backend" backend/.venv/bin/python -m pytest -q \
  backend/tests/test_trainings_api.py \
  backend/tests/test_training_collector.py \
  backend/tests/test_espoir_jeunes_collector.py
```

Recruteurs :

```bash
PYTHONPATH="$PWD/backend" backend/.venv/bin/python -m pytest -q \
  backend/tests/test_recruiter_official.py \
  backend/tests/test_recruiter_sync.py \
  backend/tests/test_recruiter_hn.py \
  backend/tests/test_recruiters_api.py
```

Immigration :

```bash
PYTHONPATH="$PWD/backend" backend/.venv/bin/python -m pytest -q \
  backend/tests/test_immigration_api.py
```

Frontend :

```bash
cd frontend
npm run build
```

Ne pas annoncer le résultat d'un test avant de disposer de sa sortie complète.

## 6. Sauvegarde et intégrité

Avant une modification de code :

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "backups/maintenance-$STAMP"
```

Avant une modification de la base, identifier son chemin effectif et effectuer une copie cohérente. Ne jamais supprimer la base pour réinitialiser l'application sans décision explicite.

Vérifier les fichiers ignorés par Git :

```bash
git status --short
git check-ignore jobhunter.db backend/.env
```

Les bases, secrets, environnements virtuels, dépendances installées, caches, sauvegardes et données personnelles ne doivent pas être ajoutés au dépôt.

## 7. Documentation technique automatique

Le script d'inventaire peut être lancé depuis la racine :

```bash
python3 scripts/generate_technical_docs.py
```

Il détecte la structure statique du dépôt. Il ne certifie pas le fonctionnement des collecteurs et ne remplace ni les tests ni la documentation fonctionnelle.
