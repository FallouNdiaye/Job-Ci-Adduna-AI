# Documentation frontend — Job Ci Adduna AI

## 1. Technologies

- React et TypeScript.
- Vite pour le serveur de développement et la construction.
- `lucide-react` pour les icônes.
- CSS du projet dans `frontend/src/style.css`.

Commandes :

```bash
cd frontend
npm install
npm run dev
npm run build
```

Le serveur de développement est configuré pour écouter sur `127.0.0.1`. La configuration habituelle du frontend utilise `VITE_API_URL` ou l'API locale `http://127.0.0.1:8000/api`.

## 2. Fichiers principaux

| Fichier | Responsabilité |
|---|---|
| `src/main.tsx` | Point d'entrée React |
| `src/App.tsx` | Application principale, navigation et module emplois |
| `src/DoctoratesPanel.tsx` | Doctorats, bourses et opportunités académiques |
| `src/ImmigrationPanel.tsx` | Procédures de mobilité, immigration et consultation de financements |
| `src/RecruitersPanel.tsx` | Profils de recruteurs et offres associées |
| `src/TrainingPanel.tsx` | Formations et appels à candidatures |
| `src/style.css` | Styles et présentation des vues |

## 3. Modules fonctionnels

### Emplois
La vue principale donne accès aux offres collectées et aux fonctions de recherche et de filtrage disponibles dans l'application. Le ciblage inclut les rôles informatiques, dont Full Stack et mobile, ainsi que des critères de localisation, de travail à distance et de mobilité lorsque les données de l'offre le permettent.

Les fonctions liées aux candidatures comprennent la mise à jour de leur état et la préparation de brouillons. La génération d'un brouillon n'envoie pas de message et ne soumet pas une candidature.

### Doctorats et opportunités académiques
Le panneau doctoral présente les offres et opportunités académiques avec filtres et libellés de financement. Les données affichées proviennent du catalogue backend et de programmes de référence. Une catégorie académique n'implique pas nécessairement un doctorat, et une bourse n'implique pas automatiquement un financement complet.

### Immigration et mobilité
Le panneau expose les parcours d'immigration répertoriés et leurs liens officiels. Il propose également une section de consultation de financements et programmes académiques provenant du catalogue doctoral. Les informations sont indicatives et doivent être vérifiées auprès des autorités et organismes concernés.

### Recruteurs
Les profils de recruteurs et leurs annonces sont présentés séparément des offres générales. Un recruteur peut être connu du système même si aucune annonce individuelle exploitable n'a été trouvée.

### Formations et financements
Le panneau des formations consulte les routes `/api/trainings` et `/api/trainings/sources`. Il présente les éléments collectés auprès des sources intégrées et les informations disponibles sur les organismes, le financement, les échéances et les liens.

Les champs absents ne doivent pas être interprétés comme une confirmation d'inscription ouverte ou de gratuité.

## 4. Comportements d'interface à préserver

- Conserver la séparation entre emplois, doctorats, immigration, recruteurs et formations.
- Ne pas retirer des offres existantes lors d'une mise à jour de l'interface.
- Ne pas confondre les brouillons avec l'envoi automatique de candidatures.
- Présenter les statuts de financement incertains sans les convertir en confirmations.
- Garder accessibles les liens vers les sources officielles.
- Vérifier les modes clair/sombre, l'affichage mobile et la lisibilité après toute modification CSS.
- Vérifier les erreurs réseau et les états de chargement et d'absence de résultat.

## 5. Vérification

```bash
cd frontend
npm run build
```

Le succès de la construction TypeScript/Vite vérifie la compilation frontend, mais ne prouve pas à lui seul que toutes les routes backend ou les sources distantes sont disponibles.
