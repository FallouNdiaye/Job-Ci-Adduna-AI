# Guide de contribution Git — Job Ci Adduna AI

## 1. Préparer son environnement

Depuis la racine du projet :

```bash
git status
git switch main
git pull --ff-only origin main
```

Le hook local génère l'inventaire technique et le changelog avant chaque commit.
Pour l'activer dans un nouveau clone :

```bash
git config core.hooksPath .githooks
```

## 2. Développer une fonctionnalité sur une branche dédiée

Créer une branche à partir de `main` à jour :

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/nom-de-la-fonctionnalite
```

Après les modifications, vérifier les changements et lancer les tests adaptés :

```bash
git status
git diff --check
git diff
```

Ajouter uniquement les fichiers voulus, puis créer un commit :

```bash
git add chemin/du/fichier1 chemin/du/fichier2
git diff --cached --check
git diff --cached
git commit -m "feat: décrire la fonctionnalité"
```

Exemples de préfixes : `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.

Pousser la branche :

```bash
git push -u origin feature/nom-de-la-fonctionnalite
```

Ouvrir ensuite une Pull Request vers `main`. Décrire le besoin, les changements visibles,
les tests effectués et les éventuelles limites. Attendre les vérifications et la validation
avant la fusion.

## 3. Travailler directement sur main

Cette méthode est réservée aux changements simples lorsque le projet l'autorise :

```bash
git switch main
git pull --ff-only origin main
# Modifier les fichiers et lancer les tests
git add chemin/du/fichier
git diff --cached --check
git commit -m "fix: décrire la correction"
git push origin main
```

Ne pas utiliser `git push --force` pour contourner un problème de synchronisation.
Pour une fonctionnalité importante, préférer une branche et une Pull Request.

## 4. Documentation automatique

- Le hook `pre-commit` génère l'inventaire technique et `CHANGELOG.md`.
- Le script `scripts/generate_feature_docs.py` produit
  `docs/FONCTIONNALITES_LIVREES.md` à partir des commits et des fichiers modifiés.
- Le workflow GitHub Actions `.github/workflows/documentation-main.yml` régénère
  et publie ce document après un push sur `main`, si les permissions du dépôt l'autorisent.

Le résumé automatique décrit les changements détectés ; il ne remplace pas une description
fonctionnelle détaillée, les instructions d'utilisation, ni la validation des tests.
Les messages de commit et les descriptions de Pull Request doivent donc être explicites.

La documentation automatique ne doit jamais lire les secrets ou les valeurs des fichiers
`.env`, accéder à la base de données de l'application ni déclencher une synchronisation
des offres d'emploi.
