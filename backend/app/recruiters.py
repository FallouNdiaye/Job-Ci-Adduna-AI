"""Répertoire indépendant des recruteurs internationaux et de leurs offres."""
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

DB_PATH = Path(os.getenv(
    "JOBHUNTER_DB",
    str(Path(__file__).resolve().parents[1] / "jobhunter.db"),
))

router = APIRouter(prefix="/api/recruiters", tags=["Recruteurs"])


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def connect():
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    return db


def init_recruiters_db():
    """Crée uniquement les tables propres au module Recruteurs."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS recruiters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                website_url TEXT NOT NULL DEFAULT '',
                country TEXT NOT NULL DEFAULT '',
                specialties TEXT NOT NULL DEFAULT '[]',
                contact_name TEXT NOT NULL DEFAULT '',
                contact_role TEXT NOT NULL DEFAULT '',
                contact_email TEXT NOT NULL DEFAULT '',
                contact_phone TEXT NOT NULL DEFAULT '',
                linkedin_url TEXT NOT NULL DEFAULT '',
                contact_url TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL,
                source_name TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                verified_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(name, source_url)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS recruiter_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recruiter_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                country TEXT NOT NULL DEFAULT '',
                work_mode TEXT NOT NULL DEFAULT '',
                contract_type TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL UNIQUE,
                source_url TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                deadline TEXT,
                skills TEXT NOT NULL DEFAULT '[]',
                collected_at TEXT NOT NULL,
                last_checked_at TEXT,
                FOREIGN KEY(recruiter_id) REFERENCES recruiters(id)
                    ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS recruiter_sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'started',
                inserted INTEGER NOT NULL DEFAULT 0,
                updated INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            )
        """)
        # Migration additive : préserver les fiches recruteurs existantes.
        recruiter_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(recruiters)")
        }
        for column, definition in {
            "contact_phone": "TEXT NOT NULL DEFAULT ''",
            "linkedin_url": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in recruiter_columns:
                db.execute(
                    f"ALTER TABLE recruiters ADD COLUMN {column} {definition}"
                )

        # Migration additive : préserver les données et les colonnes existantes.
        existing_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(recruiter_offers)")
        }
        new_columns = {
            "visa_sponsorship_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "relocation_support_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "senegal_eligibility_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "eligibility_notes": "TEXT NOT NULL DEFAULT ''",
            "evidence_url": "TEXT NOT NULL DEFAULT ''",
            "verification_status": "TEXT NOT NULL DEFAULT 'unverified'",
            "verified_at": "TEXT",
        }
        for column, definition in new_columns.items():
            if column not in existing_columns:
                db.execute(
                    f"ALTER TABLE recruiter_offers "
                    f"ADD COLUMN {column} {definition}"
                )

        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_recruiter_offers_recruiter "
            "ON recruiter_offers(recruiter_id)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_recruiter_offers_published "
            "ON recruiter_offers(published_at)"
        )
        db.commit()


class RecruiterIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    website_url: str = ""
    country: str = ""
    specialties: list[str] = Field(default_factory=list)
    contact_name: str = ""
    contact_role: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    linkedin_url: str = ""
    contact_url: str = ""
    source_url: str = Field(min_length=8, max_length=2000)
    source_name: str = ""
    notes: str = ""


class RecruiterOfferIn(BaseModel):
    recruiter_id: int
    title: str = Field(min_length=2, max_length=300)
    company: str = ""
    location: str = ""
    country: str = ""
    work_mode: str = ""
    contract_type: str = ""
    description: str = ""
    url: str = Field(min_length=8, max_length=2000)
    source_url: str = ""
    published_at: Optional[str] = None
    deadline: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    visa_sponsorship_status: Literal[
        "confirmed", "mentioned", "not_offered", "unknown"
    ] = "unknown"
    relocation_support_status: Literal[
        "confirmed", "mentioned", "not_offered", "unknown"
    ] = "unknown"
    senegal_eligibility_status: Literal[
        "eligible", "ineligible", "unclear", "unknown"
    ] = "unknown"
    eligibility_notes: str = ""
    evidence_url: str = ""
    verification_status: Literal[
        "verified", "unverified", "needs_review"
    ] = "unverified"
    verified_at: Optional[str] = None


def recruiter_dict(row):
    item = dict(row)
    item["specialties"] = json.loads(item.pop("specialties") or "[]")
    return item


def offer_dict(row):
    item = dict(row)
    item["skills"] = json.loads(item.pop("skills") or "[]")
    return item


@router.get("")
def list_recruiters(
    q: str = "",
    country: str = "",
    specialty: str = "",
    limit: int = Query(100, ge=1, le=500),
):
    sql = "SELECT * FROM recruiters WHERE 1=1"
    args = []
    if q.strip():
        sql += """ AND (name LIKE ? OR contact_name LIKE ?
                    OR contact_role LIKE ? OR contact_email LIKE ?
                    OR contact_phone LIKE ? OR linkedin_url LIKE ?)"""
        term = f"%{q.strip()}%"
        args.extend([term, term, term, term, term, term])
    if country.strip():
        sql += " AND country LIKE ?"
        args.append(f"%{country.strip()}%")
    if specialty.strip():
        sql += " AND specialties LIKE ?"
        args.append(f"%{specialty.strip()}%")
    sql += " ORDER BY name COLLATE NOCASE LIMIT ?"
    args.append(limit)

    with connect() as db:
        rows = db.execute(sql, args).fetchall()
    return [recruiter_dict(row) for row in rows]


@router.get("/offers")
def list_recruiter_offers(
    q: str = "",
    country: str = "",
    work_mode: str = "",
    recruiter_id: Optional[int] = None,
    visa_sponsorship_status: str = "",
    relocation_support_status: str = "",
    senegal_eligibility_status: str = "",
    limit: int = Query(200, ge=1, le=1000),
):
    sql = """
        SELECT o.*, r.name AS recruiter_name
        FROM recruiter_offers o
        JOIN recruiters r ON r.id = o.recruiter_id
        WHERE 1=1
    """
    args = []
    if q.strip():
        sql += " AND (o.title LIKE ? OR o.company LIKE ? OR o.description LIKE ? OR o.skills LIKE ?)"
        term = f"%{q.strip()}%"
        args.extend([term, term, term, term])
    if country.strip():
        sql += " AND (o.country LIKE ? OR o.location LIKE ?)"
        args.extend([f"%{country.strip()}%", f"%{country.strip()}%"])
    if work_mode.strip():
        sql += " AND o.work_mode LIKE ?"
        args.append(f"%{work_mode.strip()}%")
    if recruiter_id is not None:
        sql += " AND o.recruiter_id = ?"
        args.append(recruiter_id)

    status_filters = {
        "visa_sponsorship_status": (
            visa_sponsorship_status,
            {"confirmed", "mentioned", "not_offered", "unknown"},
        ),
        "relocation_support_status": (
            relocation_support_status,
            {"confirmed", "mentioned", "not_offered", "unknown"},
        ),
        "senegal_eligibility_status": (
            senegal_eligibility_status,
            {"eligible", "ineligible", "unclear", "unknown"},
        ),
    }
    for column, (value, allowed) in status_filters.items():
        normalized = value.strip().lower()
        if normalized:
            if normalized not in allowed:
                raise HTTPException(
                    400,
                    f"Valeur invalide pour {column}. Valeurs autorisées : "
                    + ", ".join(sorted(allowed)),
                )
            sql += f" AND o.{column} = ?"
            args.append(normalized)

    sql += " ORDER BY COALESCE(o.published_at, o.collected_at) DESC LIMIT ?"
    args.append(limit)

    with connect() as db:
        rows = db.execute(sql, args).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["skills"] = json.loads(item.pop("skills") or "[]")
        result.append(item)
    return result


@router.get("/{recruiter_id}")
def get_recruiter(recruiter_id: int):
    with connect() as db:
        row = db.execute(
            "SELECT * FROM recruiters WHERE id = ?", (recruiter_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Recruteur introuvable")
    return recruiter_dict(row)


@router.post("", status_code=201)
def create_recruiter(payload: RecruiterIn):
    now = utcnow()
    email = payload.contact_email.strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Format d’adresse e-mail invalide")

    with connect() as db:
        try:
            cur = db.execute("""
                INSERT INTO recruiters (
                    name, website_url, country, specialties, contact_name,
                    contact_role, contact_email, contact_phone, linkedin_url,
                    contact_url, source_url, source_name, notes, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                payload.name.strip(), payload.website_url.strip(),
                payload.country.strip(), json.dumps(payload.specialties),
                payload.contact_name.strip(), payload.contact_role.strip(),
                email, payload.contact_phone.strip(), payload.linkedin_url.strip(),
                payload.contact_url.strip(), payload.source_url.strip(),
                payload.source_name.strip(), payload.notes.strip(), now, now,
            ))
            db.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Ce recruteur existe déjà pour cette source")
        row = db.execute(
            "SELECT * FROM recruiters WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return recruiter_dict(row)


@router.post("/offers", status_code=201)
def create_recruiter_offer(payload: RecruiterOfferIn):
    now = utcnow()
    with connect() as db:
        if not db.execute(
            "SELECT id FROM recruiters WHERE id = ?",
            (payload.recruiter_id,),
        ).fetchone():
            raise HTTPException(404, "Recruteur introuvable")
        try:
            cur = db.execute("""
                INSERT INTO recruiter_offers (
                    recruiter_id, title, company, location, country,
                    work_mode, contract_type, description, url, source_url,
                    published_at, deadline, skills, collected_at, last_checked_at,
                    visa_sponsorship_status, relocation_support_status,
                    senegal_eligibility_status, eligibility_notes, evidence_url,
                    verification_status, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?)
            """, (
                payload.recruiter_id, payload.title.strip(),
                payload.company.strip(), payload.location.strip(),
                payload.country.strip(), payload.work_mode.strip(),
                payload.contract_type.strip(), payload.description.strip(),
                payload.url.strip(), payload.source_url.strip(),
                payload.published_at, payload.deadline,
                json.dumps(payload.skills), now, now,
                payload.visa_sponsorship_status,
                payload.relocation_support_status,
                payload.senegal_eligibility_status,
                payload.eligibility_notes.strip(),
                payload.evidence_url.strip(),
                payload.verification_status,
                payload.verified_at,
            ))
            db.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Cette URL d’offre est déjà enregistrée")
        row = db.execute(
            "SELECT o.*, r.name AS recruiter_name "
            "FROM recruiter_offers o JOIN recruiters r ON r.id=o.recruiter_id "
            "WHERE o.id = ?", (cur.lastrowid,)
        ).fetchone()
    item = dict(row)
    item["skills"] = json.loads(item.pop("skills") or "[]")
    return item
