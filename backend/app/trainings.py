"""Catalogue des formations et financements, séparé des offres d'emploi."""
import os
import re
import sqlite3
from ipaddress import ip_address
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

DB_PATH = Path(os.getenv(
    "JOBHUNTER_DB",
    str(Path(__file__).resolve().parents[1] / "jobhunter.db"),
))

router = APIRouter(prefix="/api/trainings", tags=["Formations & financements"])

FUNDING_STATUSES = {
    "CONFIRMED_FULL", "PARTIAL", "UNCONFIRMED", "UNKNOWN",
}
APPLICATION_STATUSES = {
    "À examiner", "Favori", "Candidature préparée",
    "Candidature envoyée", "Acceptée", "Refus", "Abandonnée",
}
CATEGORIES = {
    "formation", "bourse", "financement", "certification", "autre",
}

SOURCES = [
    {
        "id": "force-n",
        "name": "FORCE-N",
        "country": "Sénégal",
        "url": "https://www.force-n.sn/formations",
        "category": "formation",
        "collection_status": "À vérifier",
    },
    {
        "id": "3fpt-financements",
        "name": "3FPT — Financements",
        "country": "Sénégal",
        "url": "https://financements.3fpt.sn/",
        "category": "financement",
        "collection_status": "À vérifier",
    },
    {
        "id": "3fpt-espoir-jeunes",
        "name": "3FPT — Espoir Jeunes",
        "country": "Sénégal",
        "url": "https://espoirjeunes.3fpt.sn/",
        "category": "formation",
        "collection_status": "À vérifier",
    },
]


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    return db


def validate_https_url(value):
    value = str(value or "").strip()
    if not value:
        return ""

    try:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "L’URL doit être une adresse HTTPS publique valide."
        ) from exc

    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port not in (None, 443)
        or hostname == "localhost"
        or hostname.endswith((".localhost", ".local"))
    ):
        raise ValueError("L’URL doit être une adresse HTTPS publique valide.")

    # Refuser les adresses IP littérales, notamment IPv4 et IPv6.
    try:
        ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("Une URL doit utiliser un nom de domaine public.")

    return value


class TrainingIn(BaseModel):
    title: str = Field(min_length=2, max_length=400)
    provider: str = Field(default="Non précisé", max_length=250)
    category: str = "formation"
    country: str = Field(default="Sénégal", max_length=120)
    location: str = Field(default="", max_length=250)
    delivery_mode: str = Field(default="Non précisé", max_length=100)
    duration: str = Field(default="", max_length=120)
    eligibility: str = ""
    description: str = ""
    official_url: str = ""
    application_url: str = ""
    funding_status: str = "UNKNOWN"
    funding_evidence: str = ""
    cost_details: str = ""
    deadline: str | None = None
    published_at: str | None = None
    source_name: str = "Ajout manuel"

    @field_validator("official_url", "application_url")
    @classmethod
    def check_url(cls, value):
        return validate_https_url(value)

    @field_validator("funding_status")
    @classmethod
    def check_funding_status(cls, value):
        if value not in FUNDING_STATUSES:
            raise ValueError("Statut de financement invalide.")
        return value

    @field_validator("category")
    @classmethod
    def check_category(cls, value):
        if value not in CATEGORIES:
            raise ValueError("Catégorie invalide.")
        return value


class TrainingUpdate(BaseModel):
    application_status: str | None = None
    is_favorite: bool | None = None


def init_trainings_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS training_opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'Non précisé',
                category TEXT NOT NULL DEFAULT 'formation',
                country TEXT NOT NULL DEFAULT 'Sénégal',
                location TEXT NOT NULL DEFAULT '',
                delivery_mode TEXT NOT NULL DEFAULT 'Non précisé',
                duration TEXT NOT NULL DEFAULT '',
                eligibility TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                official_url TEXT NOT NULL DEFAULT '',
                application_url TEXT NOT NULL DEFAULT '',
                funding_status TEXT NOT NULL DEFAULT 'UNKNOWN',
                funding_evidence TEXT NOT NULL DEFAULT '',
                cost_details TEXT NOT NULL DEFAULT '',
                deadline TEXT,
                published_at TEXT,
                source_name TEXT NOT NULL DEFAULT 'Ajout manuel',
                application_status TEXT NOT NULL DEFAULT 'À examiner',
                is_favorite INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT NOT NULL UNIQUE,
                collected_at TEXT NOT NULL,
                last_checked_at TEXT,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_training_deadline
            ON training_opportunities(deadline)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_training_funding
            ON training_opportunities(funding_status)
        """)
        db.commit()


def save_training(training):
    data = training.model_dump() if isinstance(training, TrainingIn) else dict(training)
    title = str(data.get("title") or "").strip()
    if len(title) < 2:
        raise ValueError("Le titre de la formation est obligatoire.")

    data["title"] = title
    for field in ("official_url", "application_url"):
        data[field] = validate_https_url(data.get(field, ""))

    status = data.get("funding_status", "UNKNOWN")
    if status not in FUNDING_STATUSES:
        raise ValueError("Statut de financement invalide.")
    category = data.get("category", "formation")
    if category not in CATEGORIES:
        raise ValueError("Catégorie invalide.")

    # Une URL officielle identifie l'offre ; sinon, utiliser titre + organisme.
    identity = data["official_url"].strip().lower() or (
        title.casefold() + "|" +
        str(data.get("provider") or "").strip().casefold()
    )
    digest = sha256(identity.encode("utf-8")).hexdigest()
    data["content_hash"] = digest
    timestamp = now()

    text_fields = (
        "provider", "category", "country", "location", "delivery_mode",
        "duration", "eligibility", "description", "official_url",
        "application_url", "funding_status", "funding_evidence",
        "cost_details", "source_name",
    )
    defaults = {
        "provider": "Non précisé", "category": "formation",
        "country": "Sénégal", "location": "",
        "delivery_mode": "Non précisé", "duration": "",
        "eligibility": "", "description": "", "official_url": "",
        "application_url": "", "funding_status": "UNKNOWN",
        "funding_evidence": "", "cost_details": "",
        "source_name": "Ajout manuel",
    }
    for key in text_fields:
        if data.get(key) is None:
            data[key] = defaults[key]

    with connect() as db:
        existing = db.execute(
            "SELECT * FROM training_opportunities WHERE content_hash=?",
            (digest,),
        ).fetchone()

        if existing:
            # Une collecte partielle ne doit jamais effacer une donnée utile.
            updates = {"last_checked_at": timestamp}
            for key in text_fields:
                value = data.get(key)
                if value in (None, ""):
                    continue
                previous = existing[key] or ""
                if key == "description" and len(str(value)) < len(str(previous)):
                    continue
                if key == "funding_status":
                    previous_status = existing["funding_status"]
                    if previous_status == "CONFIRMED_FULL" and value != "CONFIRMED_FULL":
                        continue
                    if previous_status == "PARTIAL" and value not in {"PARTIAL", "CONFIRMED_FULL"}:
                        continue
                if key == "funding_evidence" and not str(value).strip():
                    continue
                updates[key] = value

            for key in ("deadline", "published_at"):
                value = data.get(key)
                if value not in (None, ""):
                    updates[key] = value

            # Ne pas perdre une échéance existante lors d'une collecte vide.
            assignments = ", ".join(f"{key}=?" for key in updates)
            db.execute(
                f"UPDATE training_opportunities SET {assignments} WHERE id=?",
                (*updates.values(), existing["id"]),
            )
            row = db.execute(
                "SELECT * FROM training_opportunities WHERE id=?",
                (existing["id"],),
            ).fetchone()
            return dict(row)

        columns = [
            "title", *text_fields, "deadline", "published_at",
            "content_hash", "collected_at", "last_checked_at", "created_at",
        ]
        values = [data.get(key) for key in columns]
        for key in ("collected_at", "last_checked_at", "created_at"):
            values[columns.index(key)] = timestamp

        placeholders = ",".join("?" for _ in columns)
        db.execute(
            f"INSERT INTO training_opportunities "
            f"({','.join(columns)}) VALUES ({placeholders})",
            values,
        )
        row = db.execute(
            "SELECT * FROM training_opportunities WHERE content_hash=?",
            (digest,),
        ).fetchone()
        return dict(row)


def present(row):
    item = dict(row)
    item["is_favorite"] = bool(item["is_favorite"])
    # L'état réel des inscriptions n'est pas encore vérifié par le collecteur.
    item["enrollment_status"] = "Inscriptions non vérifiées"
    deadline = item.get("deadline")
    try:
        item["opportunity_status"] = (
            "expirée" if deadline and date.fromisoformat(deadline[:10]) < date.today()
            else "à vérifier" if not deadline
            else "date limite à venir"
        )
    except (ValueError, TypeError):
        item["opportunity_status"] = "date à vérifier"
    return item


@router.get("/sources")
def list_training_sources():
    return {"count": len(SOURCES), "sources": SOURCES}


@router.get("")
def list_trainings(
    q: str | None = Query(default=None, max_length=200),
    category: str | None = None,
    funding_status: str | None = None,
    application_status: str | None = None,
    favorites_only: bool = False,
):
    clauses = []
    params = []
    if q:
        clauses.append("(title LIKE ? OR provider LIKE ? OR description LIKE ?)")
        params.extend([f"%{q}%"] * 3)
    if category:
        if category not in CATEGORIES:
            raise HTTPException(status_code=400, detail="Catégorie invalide.")
        clauses.append("category=?")
        params.append(category)
    if funding_status:
        if funding_status not in FUNDING_STATUSES:
            raise HTTPException(status_code=400, detail="Statut de financement invalide.")
        clauses.append("funding_status=?")
        params.append(funding_status)
    if application_status:
        if application_status not in APPLICATION_STATUSES:
            raise HTTPException(status_code=400, detail="Statut de candidature invalide.")
        clauses.append("application_status=?")
        params.append(application_status)
    if favorites_only:
        clauses.append("is_favorite=1")

    sql = "SELECT * FROM training_opportunities"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY CASE WHEN deadline IS NULL OR deadline='' THEN 1 ELSE 0 END, deadline, collected_at DESC"

    with connect() as db:
        rows = db.execute(sql, params).fetchall()
    return {"count": len(rows), "items": [present(row) for row in rows]}


@router.post("", status_code=201)
def create_training(training: TrainingIn):
    try:
        item = save_training(training)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return present(item)


@router.patch("/{training_id}")
def update_training(training_id: int, update: TrainingUpdate):
    changes = update.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Aucune modification fournie.")
    if "application_status" in changes and changes["application_status"] not in APPLICATION_STATUSES:
        raise HTTPException(status_code=422, detail="Statut de candidature invalide.")

    with connect() as db:
        existing = db.execute(
            "SELECT id FROM training_opportunities WHERE id=?",
            (training_id,),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Formation introuvable.")

        if "is_favorite" in changes:
            changes["is_favorite"] = int(changes["is_favorite"])
        assignments = ", ".join(f"{key}=?" for key in changes)
        db.execute(
            f"UPDATE training_opportunities SET {assignments} WHERE id=?",
            (*changes.values(), training_id),
        )
        row = db.execute(
            "SELECT * FROM training_opportunities WHERE id=?",
            (training_id,),
        ).fetchone()
    return present(row)
