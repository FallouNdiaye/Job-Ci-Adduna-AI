# Job Ci Adduna AI — État fonctionnel du backend et du frontend

**Document de référence — état reconstitué à partir des travaux et diagnostics réalisés jusqu'au 19 octobre 2026.**

> **Important sur la précision de cet inventaire :** ce document distingue les fonctionnalités présentes, les collecteurs effectivement testés, les connecteurs conditionnels et les points dont le dernier résultat est incomplet. « Intégré » ne signifie pas que la source fournit toujours des offres, que son accès réseau est toujours disponible, ni que chaque connecteur est activé dans l'environnement courant. Les volumes de la base évoluent avec les synchronisations.

## 1. Présentation du projet

JobHunter AI est une application locale de recherche et de suivi d'opportunités professionnelles et académiques. Elle comprend une API Python/FastAPI, une interface React/Vite en français et une base SQLite. Le projet est exécuté sur Ubuntu.

**Répertoire de travail connu :**

```text
~/Téléchargements/JobHunter-AI-Derniere-Version-Preconfiguree
```

**Architecture et commandes usuelles :**

- Backend : `backend/`, environnement Python `backend/.venv/`.
- Frontend : application React/Vite.
- Base active prévue : `./jobhunter.db` à la racine du projet, configurée par `JOBHUNTER_DB=./jobhunter.db` dans `backend/.env`.
- Backend local : `http://127.0.0.1:8000`; documentation API FastAPI : `/docs`.
- Frontend local : `http://127.0.0.1:5173`.
- API frontend : `VITE_API_URL` ou, par défaut, `http://127.0.0.1:8000/api`.

**Attention à la base de données :** un ancien fichier `backend/jobhunter.db` a aussi été constaté. Il ne doit pas être confondu avec la base racine active. Avant toute opération de maintenance, vérifier `JOBHUNTER_DB` et faire une sauvegarde.

## 2. Fonctionnalités du frontend

Les fonctionnalités documentées dans les travaux précédents comprennent :

- Tableau de bord et statistiques de recherche.
- Consultation des offres d'emploi collectées.
- Recherche et filtrage des offres.
- Présentation du score de correspondance entre le profil et une offre.
- Accès aux détails d'une offre et à sa description nettoyée lorsque le collecteur fournit du HTML.
- Suivi de l'état des candidatures.
- Création et consultation de brouillons de lettres de motivation et d'e-mails.
- Module distinct pour les doctorats, financements et opportunités académiques.
- Module recruteurs, profils de recruteurs et offres associées.
- Catalogue de ressources d'immigration et de mobilité internationale.
- Interface en français.

Le projet a été construit pour faciliter la recherche, la sélection et la préparation des candidatures. Il ne faut pas présenter l'envoi automatique de candidatures comme une fonctionnalité existante : aucun envoi automatique n'est confirmé dans les travaux consignés.

## 3. Fonctionnalités du backend

### 3.1 API et persistance

- API FastAPI avec routes sous `/api`.
- Persistance SQLite.
- Endpoint de santé utilisé pour vérifier l'état du service, la base et la synchronisation.
- Endpoints d'offres, statistiques, suivi des candidatures et brouillons.
- Routes dédiées aux doctorats, aux recruteurs et au catalogue d'immigration.
- Synchronisations de sources avec journalisation des exécutions et comptage des éléments ajoutés/mis à jour lorsque le collecteur le fournit.

Routes connues et observées dans le projet (la liste doit être rapprochée de `/docs` pour obtenir la liste exhaustive de la version locale) :

| Route | Fonction |
|---|---|
| `GET /api/jobs` | Consulter les offres d'emploi |
| `GET /api/jobs/{id}/application` | Consulter les données de candidature associées à une offre |
| Routes `/api/drafts` | Gérer les brouillons |
| Routes `/api/doctorates` | Consulter les opportunités doctorales |
| Routes `/api/doctorates/sources` | Consulter les sources doctorales |
| `POST /api/doctorates/sync` | Déclencher une synchronisation doctorale |
| `GET /api/immigration` | Lire le catalogue de mobilité/immigration |
| `GET/POST /api/recruiters` | Consulter et créer des profils de recruteurs |
| `GET/POST /api/recruiters/offers` | Consulter et créer des offres de recruteurs |
| `GET /api/recruiters/{id}` | Consulter un recruteur |

Les routes exactes et méthodes disponibles doivent être vérifiées dans le Swagger local, car elles peuvent évoluer.

### 3.2 Collecte et synchronisation automatiques

Les réglages consignés dans le projet indiquaient :

- Synchronisation des offres d'emploi : activée, intervalle de 60 minutes.
- Synchronisation doctorale : activée, intervalle de 24 heures.
- Synchronisation des recruteurs : activée, intervalle de 6 heures.
- Synchronisation en arrière-plan conservée comme exigence du projet.
- Les connecteurs optionnels peuvent dépendre de variables d'environnement, de clés ou de crédits.
- Une source peut être intégrée mais renvoyer zéro résultat; cela ne prouve pas à lui seul que la source n'a aucune offre.

Ne pas désactiver les synchronisations automatiques existantes lors d'une modification. Vérifier les variables d'environnement réelles avant d'affirmer qu'un connecteur optionnel est actif.

### 3.3 Qualité et normalisation des données

Travaux consignés :

- Nettoyage de descriptions d'offres contenant du HTML côté backend.
- Nettoyage/affichage de texte HTML encodé dans le panneau doctoral du frontend.
- Déduplication des offres via une empreinte de contenu et index unique `idx_jobs_content_hash`.
- Conservation recherchée des informations de financement et de date limite dans le module doctoral.
- Classification d'opportunités et de rôles, notamment Full Stack et Mobile.
- Les mots-clés de classification mobile incluent Flutter, React Native, iOS et Android.

### 3.4 Profil et ciblage

Le profil utilisé pour orienter la recherche vise des postes expérimentés Full Stack, backend/web et mobile, avec intérêt pour le Sénégal et l'international, notamment les possibilités à distance, de mobilité ou de relocalisation. Technologies mentionnées dans le profil : Java, Spring Boot, Spring Batch, Angular, PHP, Symfony, Laravel, PostgreSQL, Docker, REST, Kafka, Grails, Vue.js, C#, Flutter et React.

Le scoring est décrit comme un score de correspondance heuristique. Ne pas le présenter comme un modèle IA entraîné ou comme un système LLM/RAG entièrement opérationnel sans nouvelle vérification du code.

## 4. Sources d'offres d'emploi : inventaire connu

### 4.1 API et plateformes d'emploi

Les collecteurs suivants ont été repérés dans le projet et/ou mentionnés dans les audits d'intégration :

| Source | Type | État à documenter avec prudence |
|---|---|---|
| Arbeitnow | API d'offres | Intégrée; utilisée lors de synchronisations précédentes |
| Remotive | API d'offres à distance | Intégrée; utilisée lors de synchronisations précédentes |
| Jobicy | API d'offres à distance | Intégrée; utilisée lors de synchronisations précédentes |
| Remote Jobs API | Connecteur optionnel | Présence signalée; dépend de la configuration |
| JobSpy | Agrégation via bibliothèque/outils | Présence signalée; configuration et dépendances nécessaires |
| Greenhouse | Tableaux de recrutement/API par employeur | Optionnel; dépend des tableaux/configurations |
| Lever | Tableaux de recrutement/API par employeur | Optionnel; dépend des tableaux/configurations |
| Crawl4AI | Outil de collecte web | Optionnel; configuration nécessaire |
| ScrapeGraphAI | Collecte assistée par extraction | Optionnel; un essai précédent a échoué faute de crédits suffisants |
| Hirehunt | Connecteur mentionné dans les audits | Présence signalée; dernier état opérationnel non confirmé |

Un audit antérieur a recensé 33 collecteurs au total, et identifié 12 collecteurs sans tests dédiés correspondants à cette date : Arbeitnow, CNRS, Crawl4AI, Greenhouse, Hirehunt, Jobicy, JobSpy, Lever, Remote Jobs API, Remotive, ScrapeGraphAI et UN Careers. Ce constat décrit l'état des tests au moment de l'audit, pas nécessairement l'état après tous les travaux ultérieurs.

### 4.2 Sources locales du Sénégal

Les collecteurs suivants ont été mentionnés comme intégrés dans le projet :

- Expat-Dakar
- Liggey
- EmploiSenegal
- Emploi Dakar
- Senjob

Des tests dédiés Expat-Dakar et Liggey ont été rapportés avec **8 tests réussis**. La présence d'un collecteur ne garantit pas que le site renvoie des résultats à chaque exécution. Ne pas relancer des diagnostics déjà effectués sans consulter l'historique des tests et synchronisations.

### 4.3 Flux institutionnels et offres internationales

Sources/collecteurs mentionnés dans les travaux :

- ONU Careers / UN Careers.
- UNDP (PNUD).
- IOM (Organisation internationale pour les migrations).
- UN Women.
- CNRS, via flux RSS.
- GIZ, dans les suites de tests institutionnelles.
- Campus France, intégré au collecteur doctoral pour les opportunités académiques.
- EURAXESS, historiquement présent mais suspendu dans les travaux récents en raison de restrictions/robots.
- Autres flux RSS/Atom doctoraux configurés, notamment DAAD et Sussex; les sources doctorales ont aussi inclus une offre Max Planck Solar System.

**UN Women :** un collecteur utilisant l'API officielle Oracle a été corrigé pour conserver la pagination, convertir les codes pays en noms et afficher un avertissement de recrutement local. Six tests ont réussi lors d'une étape; deux tests supplémentaires ont ensuite été ajoutés, mais une erreur de syntaxe littérale `\n` a été signalée dans le fichier de test et le résultat final après correction n'est pas confirmé ici. Ne pas déclarer les deux derniers tests validés sans leur sortie pytest.

**CNRS :** flux RSS public examiné; une analyse a détecté des titres de thèse et des postes techniques. Les offres d'emploi d'ingénierie/développement doivent rester distinctes du module doctoral lorsqu'elles correspondent à des emplois ordinaires.

**ONU Careers / UN Careers :** collecteur présent, mais il avait été identifié comme n'ayant pas de test dédié lors d'un audit antérieur. Son état réseau actuel doit être évalué via les logs existants plutôt que supposé.

### 4.4 Nouveau module : formations et appels à candidatures

**État au 19 octobre 2026 : module à concevoir.** La recherche
effectuée dans `backend`, `frontend` et `docs` n'a trouvé aucune
référence à FORCE-N ou au 3FPT. Cela ne prouve pas l'absence de
toute implémentation dans d'autres emplacements du dépôt.

Objectif : créer une rubrique indépendante des offres d'emploi et
du module doctoral, dédiée aux formations gratuites, aux programmes
de formation et aux appels à candidatures d'organismes sénégalais.

Sources prioritaires envisagées :
- FORCE-N : formations numériques et appels à candidatures officiels.
- 3FPT : formations professionnelles et techniques, dispositifs de
  financement ou de prise en charge, et appels à candidatures.
- Extension ultérieure possible à d'autres organismes publics et
  programmes de formation, après vérification de leurs sources officielles.

Fonctionnalités à prévoir dans une vue dédiée :
- filtres par organisme, domaine, région, niveau requis et échéance ;
- fiche d'offre avec titre, description, prérequis, durée, lieu,
  dates, source officielle et lien de candidature ;
- suivi des candidatures ouvertes, échéances proches et offres expirées ;
- statut de gratuité/financement : gratuité confirmée, prise en charge
  partielle, à vérifier ou inconnue ;
- déduplication des annonces et conservation de la source d'origine.

Règles : ne jamais déclarer une formation gratuite sans élément
probant ; distinguer absence de résultats et erreur de collecte ;
respecter les conditions d'accès et les limites des sites officiels.
Aucun collecteur ni écran FORCE-N/3FPT n'est déclaré opérationnel
à ce stade. Concevoir ce module sans modifier les flux de synchronisation
des emplois et des doctorats.

### 4.5 MESRI Sénégal : collecteur d'emplois

État vérifié le 19 octobre 2026 :
- le collecteur `collect_mesri_jobs(client)` est présent dans
  `backend/app/main.py` ;
- il est raccordé à `run_collection()` sous le nom `MESRI Sénégal` ;
- les sources examinées comprennent le portail universitaire officiel
  et certains PDF liés aux annonces ;
- les contrôles comprennent notamment la validation des URL/hôtes,
  des limites de taille et de pages PDF, ainsi que l'extraction de texte ;
- les annonces informatiques sont filtrées selon les rôles et les
  échéances détectées. Les résultats doivent toujours être vérifiés
  sur la publication officielle.

Les tests dédiés MESRI ont réussi (8 tests) et la suite backend a
réussi (300 tests) lors de la vérification rapportée le 19 octobre 2026.
Ces résultats sont historiques et ne constituent pas une nouvelle
exécution lors de la lecture de ce document.

La vérification du raccordement et des tests a été réalisée sans lancer
de collecte réelle et sans modifier la base de données.

## 5. Module doctorats, financements et mobilité académique

Le module doctoral est distinct du module principal d'offres d'emploi. Il gère les opportunités doctorales, les sources et les synchronisations.

### Sources et intégrations recensées

- Flux RSS/Atom doctoraux configurés.
- DAAD, flux RSS doctoral.
- Sussex, flux d'opportunités doctorales financées.
- Max Planck Solar System, source doctorale.
- Campus France, collecteur officiel intégré.
- EURAXESS : source historiquement testée mais suspendue dans les travaux récents en raison des règles d'accès.
- CNRS RSS : analysé et utilisé pour la découverte d'opportunités; distinguer les thèses des postes salariés ordinaires.

### États de financement

Les catégories de financement définies sont :

- `CONFIRMED_FULL`
- `PARTIAL`
- `UNCONFIRMED`
- `UNKNOWN`

Règles métier consignées :

- Ne pas qualifier automatiquement de financement complet une offre parce qu'elle mentionne un salaire ou une bourse.
- Les frais de scolarité seuls correspondent à un financement partiel.
- Écarter/normaliser la mention « Not funded by EU programme » afin qu'elle ne soit pas interprétée comme une confirmation de financement européen.
- Conserver les échéances, les établissements, les lieux et les informations de financement déjà obtenus.
- Garder visibles les offres partielles ou incertaines en les étiquetant clairement plutôt que de les supprimer silencieusement.

### Collecteur Campus France

Le collecteur consigné dans `backend/app/doctoral.py` comprend :

- Validation des hôtes officiels et HTTPS.
- Refus des redirections.
- Lecture et traitement des listes et détails HTML/JSON.
- Pagination plafonnée à trois pages de 25 éléments.
- Limite de réponse de 2 Mio.
- Contrôles de type de contenu et de réponses HTTP/JSON.
- Déduplication et normalisation des opportunités.
- Intégration à `sync_doctorates`.
- Conservation des flux RSS/Atom actifs.
- Compteur de sources incluant le collecteur Campus France.

Les tests déjà mentionnés couvrent notamment la sécurité des URL, les liens officiels, le rejet de liens externes, les titres, les financements et les échéances. Des lacunes de tests autour de la pagination, des erreurs simulées et de la préservation des données avaient été identifiées.

## 6. Module recruteurs et offres de recruteurs

Le module recruteurs est distinct des offres d'emploi générales.

### Sources

- Hacker News — fil « Who Is Hiring » et commentaires.
- Sites officiels de recruteurs/entreprises configurés dans `backend/app/recruiter_official.py` :
  - Crossover
  - ITSync
  - First Point Group
  - Trinamics
  - X-Team
- Des profils historiques supplémentaires étaient présents en base : Aizen Recruitment, Kernel, Klipspringer et Noordt & Co.
- Shepherd a été examiné à partir d'un commentaire HN; le lien fourni menait à une page carrières et non à une offre individuelle, il ne fallait donc pas inventer un intitulé d'offre.

### Comportement des collecteurs

Le collecteur officiel :

- Vérifie `robots.txt`.
- Refuse les redirections.
- Limite les URL et pages traitées.
- Privilégie les pages du même hôte.
- Recherche des URL d'emploi selon des chemins reconnus et des métadonnées JSON-LD `JobPosting`.
- Peut détecter/enregistrer un profil de recruteur sans avoir trouvé d'offre.
- Ne doit pas transformer une page générique « Careers » en offre d'emploi inventée.

Le collecteur Hacker News inspecte les commentaires et tente d'identifier les offres individuelles, liens, lieux et contacts publics. Il ne doit pas inventer de titre, de salaire, d'adresse e-mail ou de possibilité de visa si ces informations ne sont pas explicitement présentes.

### Synchronisation et résultats observés

- Synchronisation des recruteurs programmée toutes les six heures.
- HN et sites officiels exécutés dans le scheduler, avec gestion séparée des erreurs.
- À une vérification du 19 octobre 2026 : intégrité SQLite `ok`, 36 profils recruteurs et 19 offres recruteurs.
- Exécution HN réussie observée : 27 publications repérées, environ 20 offres individuelles détectées dans cette exécution; un run ultérieur a signalé 46 enregistrements mis à jour (compteur mêlant profils et offres, ne pas le décrire comme 46 offres).
- Une exécution officielle a enregistré 4 nouvelles offres. Un test manuel de First Point Group a trouvé 5 offres, dont des postes Java en Afrique du Sud; la cinquième n'était pas confirmée comme persistée.
- Répartition enregistrée lors d'un audit : 19 offres associées à HN et 4 à First Point Group; les autres profils officiels n'avaient pas d'offre associée à ce moment-là.
- Les résultats ITSync ne contenaient pas d'offre individuelle exploitable dans les tests effectués. Le portail utilise Zoho Recruit, mais l'HTML initial inspecté ne contenait aucun lien direct vers les offres. **ITSync reste donc une source configurée mais sans collecte d'offres confirmée**, et non une source à déclarer pleinement opérationnelle.

### Tests recruteurs

Les suites mentionnées sont :

```bash
PYTHONPATH="$PWD/backend" backend/.venv/bin/python -m pytest -q \
  backend/tests/test_recruiter_official.py \
  backend/tests/test_recruiter_sync.py \
  backend/tests/test_recruiter_hn.py \
  backend/tests/test_recruiters_api.py
```

Un résultat antérieur indiquait 43 tests réussis pour ces suites. À une étape intermédiaire, les tests ciblés du collecteur officiel affichaient 8 réussites et 1 échec : l'échec concernait la création d'un profil lorsque la liste des offres est vide. Une correction de la synchronisation a été proposée ensuite, mais ne doit être considérée comme validée que si le résultat de test correspondant est disponible.

## 7. Catalogue immigration et mobilité internationale

- Endpoint de lecture : `GET /api/immigration`.
- Catalogue documenté de 13 parcours uniques.
- Destinations mentionnées : Allemagne, Canada, Union européenne, France, Pays-Bas, États-Unis et Irlande.
- Tests rapportés pour l'unicité des identifiants, les champs obligatoires, HTTPS, les statuts autorisés et les destinations.
- Les tests du module immigration ont réussi à 4/4.
- Le 18 octobre 2026, la suite backend complète a été rapportée à **235 tests réussis sur 235**, après mise à jour de tests immigration devenus obsolètes.
- Le catalogue est un outil d'information/repérage; ne pas présenter chaque voie comme une garantie de visa ou d'éligibilité individuelle.

## 8. Sécurité, conformité et limites

Principes appliqués ou exigés par le projet :

- Respecter les règles publiques `robots.txt` des sites collectés.
- Ne pas contourner authentification, contrôle d'accès ou protection anti-bot.
- Ne pas suivre automatiquement des redirections lorsque le collecteur les interdit.
- Limiter taille de réponse, nombre de pages et hôtes autorisés.
- Valider HTTPS et les hôtes des flux institutionnels.
- Refuser les XML contenant des déclarations `DOCTYPE`/`ENTITY` lorsque le validateur de flux l'exige.
- Traiter les contenus externes comme des données non fiables.
- Ne pas inventer de poste, de contact, de salaire, de financement, de date limite ou de statut de visa.
- Distinguer l'absence de résultat d'une erreur de réseau, d'un blocage, d'une source vide ou d'un collecteur non configuré.
- Ne jamais écraser les informations déjà obtenues sur les financements et échéances doctorales sans règle explicite.
- Faire une sauvegarde horodatée avant toute modification de code ou de base.
- Préserver les synchronisations automatiques déjà activées.

## 9. Tests et vérifications historiques

Résultats consignés à différentes dates — ils ne remplacent pas une exécution complète actuelle :

| Périmètre | Résultat rapporté | Précision |
|---|---:|---|
| Suite backend complète | 235/235 | Rapporté le 18 octobre 2026 après actualisation des tests immigration |
| Immigration | 4/4 | Tests dédiés |
| Recruteurs (4 suites) | 43 réussis | Résultat rapporté à une étape antérieure |
| Expat-Dakar + Liggey | 8 réussis | Tests des collecteurs |
| UN Women | 6 réussis | Avant l'ajout de deux tests; leur résultat final est à confirmer |
| Campus France | Tests dédiés existants | Sécurité URL, liens officiels, extraction titres/financement/échéance; couverture complémentaire à vérifier |
| HN Who Is Hiring | Plusieurs runs réseau réussis | Les résultats varient d'une exécution à l'autre |
| ScrapeGraphAI | Échec de collecte antérieur | Crédits insuffisants signalés |
| ITSync | Profil trouvé, pas d'offre confirmée | HTML initial sans liens directs; source à réévaluer plus tard |

## 10. État des données connu

Des audits à des moments différents ont rapporté :

- 4 377 offres d'emploi et 92 opportunités doctorales au 18 octobre 2026.
- Plus tard, environ 4 866 offres d'emploi lors d'un audit séparé.
- Le 19 octobre 2026 : intégrité de la base `ok`, 36 profils recruteurs et 19 offres recruteurs; une exécution officielle a ensuite inséré quatre offres.

Ces nombres sont des instantanés datés et ne doivent pas être additionnés entre eux. La base active prévue est le `jobhunter.db` à la racine du projet.

## 11. Variables d'environnement et points opérationnels

Variables et réglages repérés :

- `JOBHUNTER_DB=./jobhunter.db`
- `VITE_API_URL` pour l'URL de l'API côté frontend.
- `DOCTORAL_AUTO_SYNC_ENABLED=true`
- `DOCTORAL_SYNC_INTERVAL_HOURS=24`
- `RECRUITER_AUTO_SYNC_ENABLED=true`
- `RECRUITER_SYNC_INTERVAL_HOURS=6`

La synchronisation des offres générales était configurée avec un intervalle de 60 minutes. Les clés API, tableaux Greenhouse/Lever, crédits et autres paramètres optionnels doivent être vérifiés dans l'environnement local avant d'annoncer une activation. Ne pas inclure de secrets ni de valeurs de clés dans cette documentation.

Commandes utiles :

```bash
# Depuis la racine du projet
PYTHONPATH="$PWD/backend" backend/.venv/bin/python -m pytest -q

# Vérifier la santé de l'API si le backend est lancé
curl -sS http://127.0.0.1:8000/api/health

# Ouvrir la documentation API locale
# http://127.0.0.1:8000/docs
```

Si le chemin du test complet diffère dans la version locale, utiliser le chemin réel indiqué par le dépôt; ne pas modifier la configuration pour faire passer une commande copiée sans vérifier les scripts disponibles.

## 12. Éléments à confirmer lors d'un prochain audit global

Cette liste est volontairement limitée aux incertitudes documentées; elle n'implique pas de recommencer les diagnostics déjà terminés :

1. Vérifier les résultats pytest finaux après les dernières modifications du collecteur officiel des recruteurs et des tests UN Women.
2. Contrôler dans l'interface et dans les logs quelles sources optionnelles sont activées dans l'environnement courant.
3. Consulter `/docs` pour actualiser la liste exhaustive des routes API.
4. Confirmer le comportement final de création des profils recruteurs même lorsqu'aucune offre n'est détectée.
5. Garder ITSync configuré mais marqué « aucune offre confirmée » tant qu'un résultat exploitable n'a pas été démontré.
6. Distinguer clairement dans les écrans/logs : source désactivée, échec réseau, collecte réussie sans résultat, offres nouvelles et offres mises à jour.
7. Continuer la feuille de route des sources internationales et des agences ONU sans réexaminer inutilement les sources déjà testées.

## 13. Règles de maintenance pour la suite

- Consulter ce document et l'historique des tests avant de proposer une nouvelle commande de diagnostic.
- Réutiliser les résultats déjà obtenus; ne pas redemander un contrôle déjà terminé sans raison précise.
- Travailler par petites étapes et demander la sortie de la commande en cours avant d'en proposer une autre.
- Créer une sauvegarde horodatée avant les modifications du code ou de la base.
- Ne jamais supprimer les offres existantes, les candidatures, les profils recruteurs ou les données de financement/échéance.
- Maintenir la synchronisation automatique en arrière-plan.
- Séparer clairement les offres d'emploi ordinaires, les doctorats, les profils recruteurs et les informations d'immigration.
- Mettre à jour ce document après chaque intégration importante, en indiquant le statut exact : intégré, testé, actif, conditionnel, suspendu ou non confirmé.

---

**Fin du document.**
- Maintenir séparés les modules Emplois, Doctorats/financements
  académiques et Formations/appels à candidatures.
- Prévoir FORCE-N et 3FPT dans le nouveau module de formations ;
  ne pas les déclarer intégrés avant la création et la validation
  des collecteurs, des routes API et de la vue frontend.
- Préserver le raccordement MESRI à la synchronisation générale,
  ainsi que les synchronisations automatiques déjà activées.
- Pour une mise à jour documentaire, sauvegarder le fichier et vérifier
  les ancres avant insertion ; ne pas lancer de collecte ni modifier
  la base de données si la tâche porte uniquement sur la documentation.
