# Inventaire technique automatique — Job Ci Adduna AI

> Fichier généré par `scripts/generate_technical_docs.py`.
> Il décrit les éléments détectés dans le dépôt ; il ne certifie pas leur fonctionnement.

- Généré le : 2026-10-21 13:44 UTC
- Branche Git : `main`
- Dernier commit : `dedcf62 feat: add training funding module and expand documentation`
- État Git au moment du relevé : **modifications locales présentes**
- Bases de données : non ouvertes ni inspectées par ce script.
- Fichiers `.env` : jamais lus ; seules les clés du modèle `.env.example` sont listées.

## Structure détectée

- Modules Python actifs dans `backend/app/` : **11**
- Fichiers TypeScript/TSX dans `frontend/src/` : **6**
- Fichiers de tests `test_*.py` : **58**
- Routes déclarées détectées statiquement : **26**

## Modules Python

- `backend/app/__init__.py`
- `backend/app/doctoral.py`
- `backend/app/espoir_jeunes_collector.py`
- `backend/app/immigration.py`
- `backend/app/main.py`
- `backend/app/recruiter_hn.py`
- `backend/app/recruiter_official.py`
- `backend/app/recruiter_sync.py`
- `backend/app/recruiters.py`
- `backend/app/training_collector.py`
- `backend/app/trainings.py`

## Frontend

- `frontend/src/App.tsx`
- `frontend/src/DoctoratesPanel.tsx`
- `frontend/src/ImmigrationPanel.tsx`
- `frontend/src/RecruitersPanel.tsx`
- `frontend/src/TrainingPanel.tsx`
- `frontend/src/main.tsx`

## Routes API déclarées dans le code

| Fichier | Méthode | Chemin déclaré | Fonction |
|---|---|---|---|
| `backend/app/doctoral.py` | `GET` | `` | `list_doctorates` |
| `backend/app/doctoral.py` | `GET` | `/sources` | `list_sources` |
| `backend/app/doctoral.py` | `PATCH` | `/{doctorate_id}` | `update_doctorate` |
| `backend/app/doctoral.py` | `POST` | `` | `create_doctorate` |
| `backend/app/doctoral.py` | `POST` | `/sync` | `sync_doctorates` |
| `backend/app/immigration.py` | `GET` | `` | `list_immigration_routes` |
| `backend/app/main.py` | `DELETE` | `/api/jobs/{job_id}` | `delete_job` |
| `backend/app/main.py` | `GET` | `/api/health` | `health` |
| `backend/app/main.py` | `GET` | `/api/jobs` | `list_jobs` |
| `backend/app/main.py` | `GET` | `/api/profile` | `get_profile` |
| `backend/app/main.py` | `GET` | `/api/sources` | `source_catalog` |
| `backend/app/main.py` | `GET` | `/api/stats` | `stats` |
| `backend/app/main.py` | `GET` | `/api/sync/status` | `sync_status` |
| `backend/app/main.py` | `PATCH` | `/api/jobs/{job_id}/application` | `update_application` |
| `backend/app/main.py` | `POST` | `/api/drafts` | `draft_application` |
| `backend/app/main.py` | `POST` | `/api/jobs` | `create_job` |
| `backend/app/main.py` | `POST` | `/api/sync/run` | `sync_now` |
| `backend/app/recruiters.py` | `GET` | `` | `list_recruiters` |
| `backend/app/recruiters.py` | `GET` | `/offers` | `list_recruiter_offers` |
| `backend/app/recruiters.py` | `GET` | `/{recruiter_id}` | `get_recruiter` |
| `backend/app/recruiters.py` | `POST` | `` | `create_recruiter` |
| `backend/app/recruiters.py` | `POST` | `/offers` | `create_recruiter_offer` |
| `backend/app/trainings.py` | `GET` | `` | `list_trainings` |
| `backend/app/trainings.py` | `GET` | `/sources` | `list_training_sources` |
| `backend/app/trainings.py` | `PATCH` | `/{training_id}` | `update_training` |
| `backend/app/trainings.py` | `POST` | `` | `create_training` |

## Fichiers de tests

- `backend/tests/test_acf_collector.py`
- `backend/tests/test_african_union_collector.py`
- `backend/tests/test_arbeitnow_collector.py`
- `backend/tests/test_campus_france_collector.py`
- `backend/tests/test_cnrs_collector.py`
- `backend/tests/test_country_inference.py`
- `backend/tests/test_crawl4ai_collector.py`
- `backend/tests/test_doctoral_feed_security.py`
- `backend/tests/test_doctoral_save_offer_safety.py`
- `backend/tests/test_drc_collector.py`
- `backend/tests/test_ebrd_collector.py`
- `backend/tests/test_ecowas_collector.py`
- `backend/tests/test_eiffel_scholarship_collector.py`
- `backend/tests/test_emploi_dakar_collector.py`
- `backend/tests/test_emploisenegal_collector.py`
- `backend/tests/test_espoir_jeunes_collector.py`
- `backend/tests/test_euraxess_collector.py`
- `backend/tests/test_expat_dakar_collector.py`
- `backend/tests/test_fao_collector.py`
- `backend/tests/test_giz_collector.py`
- `backend/tests/test_hi_collector.py`
- `backend/tests/test_hirehunt_collector.py`
- `backend/tests/test_icao_collector.py`
- `backend/tests/test_icrc_collector.py`
- `backend/tests/test_ilo_collector.py`
- `backend/tests/test_immigration_api.py`
- `backend/tests/test_iom_collector.py`
- `backend/tests/test_irc_collector.py`
- `backend/tests/test_isdb_collector.py`
- `backend/tests/test_itu_collector.py`
- `backend/tests/test_jobicy_collector.py`
- `backend/tests/test_liggey_collector.py`
- `backend/tests/test_mesri_collector.py`
- `backend/tests/test_msf_collector.py`
- `backend/tests/test_nrc_collector.py`
- `backend/tests/test_recruiter_hn.py`
- `backend/tests/test_recruiter_official.py`
- `backend/tests/test_recruiter_sync.py`
- `backend/tests/test_recruiters_api.py`
- `backend/tests/test_remote_jobs_api_collector.py`
- `backend/tests/test_remotive_collector.py`
- `backend/tests/test_run_collection_safety.py`
- `backend/tests/test_scoring.py`
- `backend/tests/test_scrapegraphai_collector.py`
- `backend/tests/test_senjob_collector.py`
- `backend/tests/test_smartrecruiters_collector.py`
- `backend/tests/test_training_collector.py`
- `backend/tests/test_trainings_api.py`
- `backend/tests/test_un_careers_collector.py`
- `backend/tests/test_un_women_collector.py`
- `backend/tests/test_undp_collector.py`
- `backend/tests/test_unesco_collector.py`
- `backend/tests/test_unfpa_collector.py`
- `backend/tests/test_unicef_collector.py`
- `backend/tests/test_unido_collector.py`
- `backend/tests/test_unops_collector.py`
- `backend/tests/test_wfp_collector.py`
- `backend/tests/test_world_bank_group_collector.py`

## Dépendances backend — requirements.txt

- `fastapi>=0.115,<1.0`
- `uvicorn[standard]>=0.30,<1.0`
- `pydantic>=2.8,<3.0`
- `httpx>=0.27,<1.0`
- `pytest>=8.0,<9.0`
- `python-dotenv>=1.0,<2.0`
- `pypdf>=5.0,<7.0`
- `PyMuPDF==2.0`
- `rapidocr==3.10.0`
- `onnxruntime==1.31.0`

## Dépendances complémentaires — requirements-collectors.txt

- `python-jobspy>=1.1.60`
- `hirehunt>=0.5.0`
- `crawl4ai>=0.7.0`
- `scrapegraph-py>=2.1.0`
- `remote-jobs-api>=1.2.9`

## Dépendances frontend détectées dans package.json

- `@types/node: latest`
- `@types/react: latest`
- `@types/react-dom: latest`
- `@vitejs/plugin-react: latest`
- `lucide-react: ^0.468.0`
- `react: latest`
- `react-dom: latest`
- `typescript: latest`
- `vite: latest`

## Variables présentes dans backend/.env.example

> Noms seulement : aucune valeur de configuration n'est publiée ici.

- `JOBHUNTER_DB`
- `CORS_ORIGINS`
- `AUTO_SYNC_ENABLED`
- `SYNC_INTERVAL_MINUTES`
- `COLLECTOR_HTTP_TIMEOUT`
- `GREENHOUSE_BOARDS`
- `LEVER_SITES`
- `LLM_PROVIDER`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`
- `JOBSPY_ENABLED`
- `JOBSPY_SITES`
- `JOBSPY_SEARCH_TERMS`
- `JOBSPY_LOCATION`
- `JOBSPY_HOURS_OLD`
- `JOBSPY_RESULTS_PER_SOURCE`
- `HIREHUNT_ENABLED`
- `HIREHUNT_SOURCES`
- `HIREHUNT_SEARCH_TERMS`
- `HIREHUNT_LOCATION`
- `HIREHUNT_RESULTS_PER_SOURCE`
- `REMOTE_JOBS_API_URL`
- `CRAWL4AI_ENABLED`
- `CRAWL4AI_SEED_URLS`
- `SCRAPEGRAPHAI_ENABLED`
- `SGAI_API_KEY`
- `SCRAPEGRAPHAI_URLS`
- `DOCTORAL_AUTO_SYNC_ENABLED`
- `DOCTORAL_SYNC_INTERVAL_HOURS`

## Régénération

Depuis la racine du dépôt, exécuter :

```bash
python3 scripts/generate_technical_docs.py
```

## Limites

- Les routes sont détectées par analyse syntaxique statique ; les préfixes ajoutés à l'exécution peuvent ne pas apparaître dans le chemin déclaré.
- La présence d'un fichier ou d'une route ne prouve ni son accessibilité ni son bon fonctionnement.
- Les collecteurs configurés, activés ou fonctionnels ne sont pas déduits uniquement de cet inventaire.
- Ce rapport n'exécute aucun test, serveur, collecteur ou synchronisation.
