#!/usr/bin/env python3
"""Génère le suivi des fonctionnalités livrées à partir de Git."""

from __future__ import annotations

import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "FONCTIONNALITES_LIVREES.md"

CATEGORIES = {
    "feat": "Fonctionnalités",
    "fix": "Corrections",
    "perf": "Performances",
    "refactor": "Refactorisation",
    "docs": "Documentation",
    "test": "Tests",
    "build": "Build et dépendances",
    "ci": "Intégration continue",
    "chore": "Maintenance",
    "revert": "Annulations",
}


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def classify(subject: str) -> tuple[str, str]:
    import re

    match = re.match(
        r"^(feat|fix|perf|refactor|docs|test|build|ci|chore|revert)"
        r"(?:\([^)]*\))?!?:\s*(.+)$",
        subject,
        flags=re.IGNORECASE,
    )
    if not match:
        return "Autres changements", subject
    return CATEGORIES[match.group(1).lower()], match.group(2)


def main() -> None:
    raw = git(
        "log", "--reverse", "--no-merges",
        "--format=%H%x1f%ad%x1f%s",
        "--date=format:%Y-%m-%d",
    )
    commits: list[tuple[str, str, str, list[str]]] = []

    for line in raw.splitlines():
        fields = line.split("\x1f", 2)
        if len(fields) != 3:
            continue
        commit_hash, date, subject = fields

        # Ne pas intégrer les commits générés par ce workflow dans le rapport.
        if subject.startswith("docs: update delivered features"):
            continue

        changed = git(
            "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash
        )
        files = sorted(set(changed.splitlines()))
        commits.append((commit_hash[:7], date, subject, files))

    grouped: dict[str, dict[str, list[tuple[str, str, list[str]]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for short_hash, date, subject, files in commits:
        category, description = classify(subject)
        grouped[date][category].append((short_hash, description, files))

    lines = [
        "# Fonctionnalités livrées — Job Ci Adduna AI",
        "",
        "> Document généré automatiquement depuis l'historique Git.",
        "> Les descriptions reflètent les messages de commit et les fichiers modifiés ;",
        "> elles ne constituent pas une validation fonctionnelle indépendante.",
        "",
    ]

    if not commits:
        lines.extend(["Aucun commit disponible.", ""])
    else:
        for date in sorted(grouped, reverse=True):
            lines.extend([f"## {date}", ""])
            categories = grouped[date]
            order = [name for name in CATEGORIES.values() if name in categories]
            order.extend(sorted(name for name in categories if name not in order))
            for category in order:
                lines.extend([f"### {category}", ""])
                for short_hash, description, files in reversed(categories[category]):
                    lines.append(f"- **{description}** (`{short_hash}`)")
                    if files:
                        lines.append("  - Fichiers : " + ", ".join(f"`{f}`" for f in files))
                lines.append("")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Documentation fonctionnelle générée : {OUTPUT.relative_to(ROOT)}")
    print(f"Commits recensés : {len(commits)}")


if __name__ == "__main__":
    main()
