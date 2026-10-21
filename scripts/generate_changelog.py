#!/usr/bin/env python3
"""Génère CHANGELOG.md à partir de l'historique Git, sans modifier Git."""

from __future__ import annotations

import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "CHANGELOG.md"

SECTIONS = {
    "feat": "Fonctionnalités",
    "fix": "Corrections",
    "docs": "Documentation",
    "refactor": "Refactorisation",
    "perf": "Performances",
    "test": "Tests",
    "build": "Build et dépendances",
    "ci": "Intégration continue",
    "chore": "Maintenance",
    "revert": "Annulations",
}


def git_commits() -> list[tuple[str, str, str, str]]:
    result = subprocess.run(
        [
            "git", "log", "--reverse",
            "--format=%H%x1f%ad%x1f%s%x1f%b",
            "--date=format:%Y-%m-%d",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    commits = []
    for line in result.stdout.splitlines():
        fields = line.split("\x1f", 3)
        if len(fields) == 4:
            commits.append(tuple(fields))
    return commits


def classify(subject: str) -> tuple[str, str]:
    # Conventional Commits : feat(scope): message
    import re

    match = re.match(
        r"^(feat|fix|docs|refactor|perf|test|build|ci|chore|revert)"
        r"(?:\([^)]*\))?!?:\s*(.+)$",
        subject,
        flags=re.IGNORECASE,
    )
    if match:
        kind = match.group(1).lower()
        return SECTIONS.get(kind, "Autres changements"), match.group(2)

    if subject.lower().startswith("merge "):
        return "Maintenance", subject

    return "Autres changements", subject


def main() -> None:
    commits = git_commits()
    grouped: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for commit_hash, date, subject, _body in commits:
        section, message = classify(subject)
        grouped[date][section].append((commit_hash[:7], message))

    lines = [
        "# Changelog — Job Ci Adduna AI",
        "",
        "> Généré automatiquement depuis l'historique Git par",
        "> `scripts/generate_changelog.py`. Ne pas modifier manuellement.",
        "",
    ]

    if not commits:
        lines.extend(["Aucun commit disponible dans l'historique Git.", ""])
    else:
        for date in sorted(grouped, reverse=True):
            lines.extend([f"## {date}", ""])
            sections = grouped[date]
            ordered_sections = [
                name for name in SECTIONS.values() if name in sections
            ]
            ordered_sections.extend(
                sorted(name for name in sections if name not in ordered_sections)
            )
            for section in ordered_sections:
                lines.extend([f"### {section}", ""])
                for short_hash, message in reversed(sections[section]):
                    lines.append(f"- {message} (`{short_hash}`)")
                lines.append("")

    lines.extend([
        "---",
        "",
        f"Dernière génération : {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        "",
    ])
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Changelog généré : {OUTPUT.relative_to(ROOT)}")
    print(f"Commits recensés : {len(commits)}")


if __name__ == "__main__":
    main()
