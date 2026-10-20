# Collecteurs, sources et synchronisations

## 1. Comment lire cet inventaire

Les sources sont classées par famille. Les termes « intégré », « optionnel » et « historique » décrivent la présence connue du code ou des configurations, pas une garantie de disponibilité réseau.

- **Intégré** : collecteur ou route présent dans le projet.
- **Optionnel/configurable** : dépend d'une variable, d'une dépendance, d'une clé, d'un service ou d'une liste de sites.
- **Suspendu/non confirmé** : accès ou résultat opérationnel non garanti.
- **Catalogue statique** : liens et informations présents dans le code, sans collecte réseau en direct.

## 2. Offres d'emploi générales

### API, plateformes et agrégateurs

| Source | État documentaire | Remarque |
|---|---|---|
| Arbeitnow | Collecteur intégré | API publique d'offres |
| Remotive | Collecteur intégré | API d'emplois à distance |
| Jobicy | Collecteur intégré | API publique d'emplois à distance |
| Greenhouse | Configurable | Slugs des tableaux via `GREENHOUSE_BOARDS` |
| Lever | Configurable | Slugs des sites via `LEVER_SITES` |
| SmartRecruiters | Collecteur intégré | Entreprises configurables; valeurs par défaut définies dans le code |
| Remote Jobs API | Optionnel | Requiert une URL explicite de service |
| JobSpy | Optionnel, désactivé par défaut | Dépend de `requirements-collectors.txt` et de `JOBSPY_ENABLED` |
| Hirehunt | Optionnel, désactivé par défaut | Dépend de `requirements-collectors.txt` et de `HIREHUNT_ENABLED` |
| Crawl4AI | Optionnel, désactivé par défaut | Dépend de `CRAWL4AI_ENABLED` et d'URL publiques configurées |
| ScrapeGraphAI | Optionnel, désactivé par défaut | Clé et crédits de service possibles; un essai antérieur a signalé des crédits insuffisants |

### Sources locales et régionales

Collecteurs et tests présents ou mentionnés dans les travaux :
- Emploi Dakar
- Senjob
- Expat-Dakar
- Liggey
- EmploiSenegal
- MESRI Sénégal

Les collecteurs publics peuvent utiliser des sitemaps, pages d'annonces, métadonnées ou documents PDF selon le site. Ils appliquent des filtres de pertinence informatique, mais l'annonce officielle reste la référence. La présence du collecteur ne garantit ni une collecte à chaque cycle ni un résultat exploitable.

### Sources institutionnelles et internationales

Les collecteurs et tests présents dans le dépôt couvrent notamment les organisations et portails suivants :

- CNRS et EURAXESS.
- ONU/UN Careers, PNUD/UNDP, UNICEF, UNESCO, UN Women, UNFPA, UNIDO, UNOPS et WFP/PAM.
- Organisation internationale pour les migrations (OIM/IOM).
- Organisation internationale du travail (OIT/ILO).
- Groupe de la Banque mondiale.
- Banque européenne pour la reconstruction et le développement (BERD/EBRD).
- Union africaine et CEDEAO/ECOWAS.
- GIZ.
- FAO.
- Comité international de la Croix-Rouge (CICR/ICRC).
- Médecins Sans Frontières (MSF).
- International Rescue Committee (IRC).
- Danish Refugee Council (DRC).
- Action contre la Faim (ACF).
- Handicap International (HI).
- Norwegian Refugee Council (NRC).
- ICAO, ITU et autres sources institutionnelles représentées dans les collecteurs et tests.

Les fichiers de tests attestent l'existence d'une couverture de test, pas nécessairement la réussite d'une collecte réelle aujourd'hui. Consulter les tests actuels et les logs pour établir le statut opérationnel précis.

### CNRS et EURAXESS

Le flux RSS CNRS est utilisé pour rechercher des offres pertinentes. Les postes informatiques salariés doivent être classés dans le module Emplois, tandis que les thèses et opportunités doctorales relèvent du module académique.

EURAXESS a été utilisé historiquement, mais des restrictions d'accès ont été signalées. Ne pas contourner les contrôles d'accès ou les politiques du site.

## 3. Doctorats, recherche et bourses

Le module doctoral dispose d'un catalogue séparé et de sa propre synchronisation.

Sources et collecteurs recensés :
- Flux RSS/Atom définis via `DOCTORAL_FEEDS`.
- DAAD.
- Sussex.
- Max Planck Solar System.
- Campus France.
- Bourses Eiffel.
- Sources CNRS utilisées pour repérer les opportunités académiques et doctorales.

Les sources actives dépendent des URL et de la configuration chargées. EURAXESS peut rester suspendu ou inaccessible. Les flux ne doivent pas être considérés comme exhaustifs.

### Statuts de financement

| Statut | Signification |
|---|---|
| `CONFIRMED_FULL` | Financement complet étayé par les éléments disponibles |
| `PARTIAL` | Financement partiel ou frais couverts en partie |
| `UNCONFIRMED` | Mention de financement présente, mais confirmation insuffisante |
| `UNKNOWN` | Éléments insuffisants pour déterminer le financement |

La classification est prudente : salaire ou bourse seuls ne prouvent pas que tous les coûts sont couverts. Les échéances, preuves et informations d'établissement doivent être préservées lorsqu'elles existent.

## 4. Recruteurs

Sources intégrées ou configurées :
- Hacker News « Who Is Hiring ».
- Sites officiels de recruteurs configurés dans `recruiter_official.py`, notamment Crossover, ITSync, First Point Group, Trinamics et X-Team.
- D'autres profils peuvent exister dans les données déjà enregistrées.

La synchronisation des recruteurs est séparée des offres générales. Un profil peut être conservé sans annonce individuelle. Les pages génériques « Careers » ne doivent pas être transformées en offres inventées. ITSync a notamment été signalé historiquement comme n'ayant pas fourni d'annonce individuelle exploitable lors des essais décrits.

## 5. Formations et appels à candidatures

Collecteurs présents :
- FORCE-N, dans `training_collector.py`.
- Financements 3FPT, dans `training_collector.py`.
- Espoir Jeunes, dans `espoir_jeunes_collector.py`.

Routes :
- `GET /api/trainings`
- `GET /api/trainings/sources`
- `POST /api/trainings`
- `PATCH /api/trainings/{training_id}`

Le module dispose de son propre panneau frontend et de sa synchronisation planifiée. Les informations de financement, échéances, liens officiels et liens de candidature doivent être évalués séparément. Un lien absent n'est pas la preuve qu'aucune candidature n'est possible ; une URL de préinscription extraite n'est pas la preuve que les inscriptions sont encore ouvertes.

## 6. Immigration et Green Card

Le module `/api/immigration` renvoie un catalogue local en lecture seule. Il ne constitue pas un collecteur d'annonces d'immigration en direct.

Parcours présents dans le catalogue :
- Allemagne : Chancenkarte et portail d'offres Make it in Germany.
- Canada : Express Entry, Job Bank pour candidats étrangers et permis de travail.
- Union européenne : Carte bleue européenne.
- France : Passeport talent.
- Pays-Bas : Highly skilled migrant.
- Irlande : Critical Skills Employment Permit.
- États-Unis : Green Card fondée sur l'emploi, Diversity Visa, H-1B et L-1B.

Les deux notions américaines doivent rester distinctes :
- **Green Card fondée sur l'emploi** : voie de résidence permanente soumise aux règles de la catégorie.
- **Diversity Visa** : programme de loterie distinct, soumis à une période d'inscription et à des critères annuels. La sélection ne garantit pas l'obtention du visa.

Les liens officiels sont fournis dans `backend/app/immigration.py` et reflétés dans l'interface. Vérifier les règles et dates en vigueur auprès des autorités officielles.

## 7. Fréquences de synchronisation

| Domaine | Variable principale | Intervalle usuel |
|---|---|---|
| Emplois | `AUTO_SYNC_ENABLED`, `SYNC_INTERVAL_MINUTES` | 60 minutes |
| Doctorats | `DOCTORAL_AUTO_SYNC_ENABLED`, `DOCTORAL_SYNC_INTERVAL_HOURS` | 24 heures |
| Recruteurs | `RECRUITER_AUTO_SYNC_ENABLED`, `RECRUITER_SYNC_INTERVAL_HOURS` | 6 heures |
| Formations | `TRAINING_AUTO_SYNC_ENABLED`, `TRAINING_SYNC_INTERVAL_HOURS` | 24 heures |

Les valeurs effectives dépendent de l'environnement et du code. Le démarrage peut planifier le prochain cycle au lieu d'exécuter immédiatement chaque collecte. Ne pas lancer une synchronisation réelle dans le seul but de mettre à jour la documentation.

## 8. Sécurité et limites des collecteurs

Selon le collecteur, les contrôles peuvent comprendre :
- HTTPS et validation des hôtes autorisés.
- Refus de redirections.
- Plafonds de taille de réponse et de pages.
- Rejet de déclarations XML dangereuses.
- Validation de liens et normalisation des URL.
- Filtrage des rôles et déduplication.
- Traitement des erreurs au niveau de chaque annonce pour éviter qu'une annonce défectueuse interrompe toute une source.

Ces contrôles ne sont pas nécessairement identiques partout. Respecter `robots.txt`, les conditions d'utilisation et les limites des sources. Ne pas contourner les authentifications, protections anti-bot ou restrictions d'accès.

## 9. Vérification d'une source

Pour évaluer une source, distinguer :
1. Source non configurée ou désactivée.
2. Échec réseau ou HTTP.
3. Réponse valide sans offre pertinente.
4. Collecte réussie avec nouvelles offres.
5. Collecte réussie avec mises à jour uniquement.
6. Source bloquée ou temporairement inaccessible.

Un compteur nul ne permet pas à lui seul de distinguer ces cas. Les résultats doivent être vérifiés dans les logs et les tests du collecteur concerné.
