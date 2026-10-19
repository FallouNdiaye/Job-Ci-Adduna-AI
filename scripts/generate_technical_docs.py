#!/usr/bin/env python3
"""Génère un inventaire technique à partir du code, sans accéder aux bases ni aux secrets."""

from __future__ import annotations

import ast
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "INVENTAIRE_TECHNIQUE_AUTOMATIQUE.md"


def git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else "indisponible"
    except (OSError, subprocess.SubprocessError):
        return "indisponible"


def active_files(folder: Path, pattern: str) -> list[Path]:
    if not folder.exists():
        return []
    result = []
    for path in folder.rglob(pattern):
        if any(part in {
            ".git", "__pycache__", ".venv", "node_modules", "dist",
            "build", ".pytest_cache"
        } for part in path.parts):
            continue
        if ".bak" in path.name or ".before" in path.name:
            continue
        result.append(path)
    return sorted(result)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def python_routes(files: list[Path]) -> list[tuple[str, str, str, str]]:
    routes = []
    methods = {"get", "post", "put", "patch", "delete", "api_route", "options", "head"}
    for path in files:
        try:
            tree = ast.parse(read_text(path), filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr.lower() not in methods:
                    continue
                if not isinstance(func.value, ast.Name) or func.value.id not in {"app", "router"}:
                    continue

                path_value = "dynamique ou non littéral"
                if decorator.args and isinstance(decorator.args[0], ast.Constant):
                    if isinstance(decorator.args[0].value, str):
                        path_value = decorator.args[0].value
                method = func.attr.upper().replace("API_ROUTE", "API_ROUTE")
                if func.attr == "api_route":
                    for kw in decorator.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            vals = [
                                str(x.value).upper()
                                for x in kw.value.elts
                                if isinstance(x, ast.Constant) and isinstance(x.value, str)
                            ]
                            if vals:
                                method = ", ".join(vals)
                routes.append((str(path.relative_to(ROOT)), method, path_value, node.name))
    return sorted(set(routes))


def dependencies(path: Path) -> list[str]:
    if not path.is_file():
        return []
    if path.name == "package.json":
        try:
            data = json.loads(read_text(path))
            deps = {}
            deps.update(data.get("dependencies", {}))
            deps.update(data.get("devDependencies", {}))
            return [f"{name}: {version}" for name, version in sorted(deps.items())]
        except (json.JSONDecodeError, TypeError):
            return ["Manifest JSON illisible"]
    return [
        line.strip()
        for line in read_text(path).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def main() -> None:
    backend_files = active_files(ROOT / "backend" / "app", "*.py")
    frontend_files = active_files(ROOT / "frontend" / "src", "*.tsx")
    frontend_files += active_files(ROOT / "frontend" / "src", "*.ts")
    test_files = active_files(ROOT / "backend" / "tests", "test_*.py")
    routes = python_routes(backend_files)

    config_keys = []
    example = ROOT / "backend" / ".env.example"
    for line in read_text(example).splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            config_keys.append(stripped.split("=", 1)[0].strip())

    requirements = dependencies(ROOT / "backend" / "requirements.txt")
    extra_requirements = dependencies(ROOT / "backend" / "requirements-collectors.txt")
    frontend_deps = dependencies(ROOT / "frontend" / "package.json")

    branch = git("branch", "--show-current")
    commit = git("log", "-1", "--format=%h %s")
    status = git("status", "--short")
    status_text = "propre" if not status else "modifications locales présentes"

    lines = [
        "# Inventaire technique automatique — Job Ci Adduna AI",
        "",
        "> Fichier généré par `scripts/generate_technical_docs.py`.",
        "> Il décrit les éléments détectés dans le dépôt ; il ne certifie pas leur fonctionnement.",
        "",
        f"- Généré le : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- Branche Git : `{branch}`",
        f"- Dernier commit : `{commit}`",
        f"- État Git au moment du relevé : **{status_text}**",
        "- Bases de données : non ouvertes ni inspectées par ce script.",
        "- Fichiers `.env` : jamais lus ; seules les clés du modèle `.env.example` sont listées.",
        "",
        "## Structure détectée",
        "",
        f"- Modules Python actifs dans `backend/app/` : **{len(backend_files)}**",
        f"- Fichiers TypeScript/TSX dans `frontend/src/` : **{len(set(frontend_files))}**",
        f"- Fichiers de tests `test_*.py` : **{len(test_files)}**",
        f"- Routes déclarées détectées statiquement : **{len(routes)}**",
        "",
        "## Modules Python",
        "",
    ]

    lines.extend(f"- `{p.relative_to(ROOT)}`" for p in backend_files)
    lines += ["", "## Frontend", ""]
    lines.extend(f"- `{p.relative_to(ROOT)}`" for p in sorted(set(frontend_files)))

    lines += ["", "## Routes API déclarées dans le code", "",
              "| Fichier | Méthode | Chemin déclaré | Fonction |",
              "|---|---|---|---|"]
    if routes:
        for file, method, path, function in routes:
            path = path.replace("|", r"\|")
            lines.append(f"| `{file}` | `{method}` | `{path}` | `{function}` |")
    else:
        lines.append("| — | — | Aucune route détectée | — |")

    lines += ["", "## Fichiers de tests", ""]
    lines.extend(f"- `{p.relative_to(ROOT)}`" for p in test_files)

    lines += ["", "## Dépendances backend — requirements.txt", ""]
    lines.extend(f"- `{item}`" for item in requirements)
    lines += ["", "## Dépendances complémentaires — requirements-collectors.txt", ""]
    lines.extend(f"- `{item}`" for item in extra_requirements)
    lines += ["", "## Dépendances frontend détectées dans package.json", ""]
    lines.extend(f"- `{item}`" for item in frontend_deps)

    lines += ["", "## Variables présentes dans backend/.env.example", "",
              "> Noms seulement : aucune valeur de configuration n'est publiée ici.", ""]
    lines.extend(f"- `{key}`" for key in config_keys)

    lines += [
        "",
        "## Régénération",
        "",
        "Depuis la racine du dépôt, exécuter :",
        "",
        "```bash",
        "python3 scripts/generate_technical_docs.py",
        "```",
        "",
        "## Limites",
        "",
        "- Les routes sont détectées par analyse syntaxique statique ; les préfixes ajoutés à l'exécution peuvent ne pas apparaître dans le chemin déclaré.",
        "- La présence d'un fichier ou d'une route ne prouve ni son accessibilité ni son bon fonctionnement.",
        "- Les collecteurs configurés, activés ou fonctionnels ne sont pas déduits uniquement de cet inventaire.",
        "- Ce rapport n'exécute aucun test, serveur, collecteur ou synchronisation.",
        "",
    ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Documentation générée : {OUTPUT.relative_to(ROOT)}")
    print(f"Modules Python : {len(backend_files)}")
    print(f"Fichiers frontend : {len(set(frontend_files))}")
    print(f"Fichiers de tests : {len(test_files)}")
    print(f"Routes déclarées détectées : {len(routes)}")
    print("Aucune base de données ni valeur de fichier .env n'a été lue.")


if __name__ == "__main__":
    main()
