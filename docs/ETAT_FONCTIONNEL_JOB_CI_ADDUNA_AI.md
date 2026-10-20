# État fonctionnel — Job Ci Adduna AI

> Document de référence fonctionnelle. Les fonctionnalités décrites doivent être distinguées de la disponibilité effective des sources distantes. Les résultats de tests historiques ne valent pas validation du code courant.

## Présentation

Job Ci Adduna AI est une application locale de veille d'opportunités professionnelles, académiques, de formation et de mobilité internationale. Elle comprend un frontend React/TypeScript/Vite, un backend FastAPI et une base SQLite.

## Modules

1. **Emplois** : collecte multi-source, recherche, filtres, score de correspondance, ajout/suppression d'offres et suivi des candidatures.
2. **Brouillons de candidature** : préparation d'e-mails et de lettres de motivation. Aucun envoi automatique n'est confirmé.
3. **Doctorats et recherche** : flux académiques, opportunités de recherche, bourses et statuts de financement.
4. **Recruteurs** : profils de recruteurs et annonces individuelles lorsque les sources permettent de les identifier.
5. **Formations et appels à candidatures** : FORCE-N, financements 3FPT et Espoir Jeunes.
6. **Immigration et mobilité** : catalogue informatif de voies officielles, y compris Green Card fondée sur l'emploi, Diversity Visa, H-1B et L-1B.
7. **Statistiques et synchronisations** : état de santé, statistiques et exécutions de collecte.

## API

Les routes principales comprennent :
- Santé, profil, sources et statistiques : `/api/health`, `/api/profile`, `/api/sources`, `/api/stats`.
- Emplois et candidatures : `/api/jobs`, `/api/jobs/{job_id}/application`, `/api/drafts`.
- Synchronisation des emplois : `/api/sync/status`, `/api/sync/run`.
- Doctorats : `/api/doctorates`, `/api/doctorates/sources`, `/api/doctorates/sync`.
- Recruteurs : `/api/recruiters` et `/api/recruiters/offers`.
- Formations : `/api/trainings` et `/api/trainings/sources`.
- Immigration : `/api/immigration`.

Consulter `/docs` pour la liste effective des routes de la version exécutée.

## Sources

Le dépôt comprend des collecteurs et tests pour des plateformes d'emploi, des sources sénégalaises, des organismes internationaux, des portails académiques, des recruteurs et des programmes de formation. Voir [l'inventaire des sources et synchronisations](COLLECTEURS_ET_SYNCHRONISATION.md) pour les familles et les limites connues.

Les connecteurs optionnels peuvent nécessiter une activation explicite, des dépendances, une clé ou un service externe. La présence d'un collecteur ne garantit pas une collecte réussie.

## Synchronisations automatiques

Les domaines Emplois, Doctorats, Recruteurs et Formations disposent de mécanismes de synchronisation distincts. Les intervalles usuels documentés sont respectivement de 60 minutes, 24 heures, 6 heures et 24 heures. Vérifier l'environnement et le code pour confirmer les valeurs réellement appliquées.

Ne pas désactiver les synchronisations automatiques lors d'une modification documentaire.

## Financements

Le module académique utilise les statuts `CONFIRMED_FULL`, `PARTIAL`, `UNCONFIRMED` et `UNKNOWN`. Une mention de salaire ou de bourse n'est pas suffisante pour conclure à un financement complet. Les informations de financement, preuves et échéances déjà enregistrées doivent être conservées lors des mises à jour.

## Données et sécurité

- Base prévue : `./jobhunter.db`, sous réserve de `JOBHUNTER_DB`.
- Un ancien fichier `backend/jobhunter.db` a été constaté ; ne pas le confondre avec la base active.
- Sauvegarder avant toute modification de données.
- Respecter les règles d'accès et conditions des sites sources.
- Ne pas contourner les protections anti-bot.
- Ne pas inventer d'offres, de contacts, de financements, d'échéances ou de conditions de visa.
- Ne pas publier les secrets du fichier `.env`.

## Vérifications

Tests backend :

```bash
PYTHONPATH="$PWD/backend" backend/.venv/bin/python -m pytest -q
```

Construction frontend :

```bash
cd frontend && npm run build
```

Ces commandes doivent être exécutées pour produire un état de validation daté. Les nombres de tests rapportés dans des audits antérieurs sont historiques et ne sont pas repris ici comme résultats actuels.

## Documentation complémentaire

- [Frontend](FRONTEND.md)
- [Backend et API](BACKEND.md)
- [Collecteurs et synchronisations](COLLECTEURS_ET_SYNCHRONISATION.md)
- [Installation, configuration et tests](INSTALLATION_ET_CONFIGURATION.md)
- [Inventaire technique automatique](INVENTAIRE_TECHNIQUE_AUTOMATIQUE.md)
