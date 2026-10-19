import json
import sqlite3

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import app.recruiters as r


@pytest.fixture
def recruiter_db(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "DB_PATH", tmp_path / "recruiters-test.db")
    r.init_recruiters_db()
    return r.DB_PATH


def create_test_recruiter():
    return r.create_recruiter(r.RecruiterIn(
        name="Entreprise Test International",
        source_url="https://example.org/recruiters",
        country="France",
    ))


def create_test_offer(recruiter_id, **overrides):
    data = {
        "recruiter_id": recruiter_id,
        "title": "Full Stack Software Engineer",
        "company": "Entreprise Test International",
        "country": "France",
        "url": "https://example.org/jobs/fullstack-test",
        "source_url": "https://example.org/jobs",
    }
    data.update(overrides)
    return r.create_recruiter_offer(r.RecruiterOfferIn(**data))


def test_migration_legacy_schema_preserves_existing_offer(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(r, "DB_PATH", db_path)

    # Simuler l'ancien schéma, avant l'ajout des sept colonnes.
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE recruiters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                source_url TEXT NOT NULL
            );

            CREATE TABLE recruiter_offers (
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
            );

            INSERT INTO recruiters (id, name, source_url)
            VALUES (7, 'Ancienne Entreprise',
                    'https://example.org/old-source');

            INSERT INTO recruiter_offers (
                id, recruiter_id, title, company, country, url,
                source_url, skills, collected_at
            ) VALUES (
                42, 7, 'Ancienne offre Full Stack',
                'Ancienne Entreprise', 'France',
                'https://example.org/old-offer',
                'https://example.org/old-source', '["Java"]',
                '2026-01-01T00:00:00+00:00'
            );
        """)

    r.init_recruiters_db()

    with r.connect() as db:
        offer = db.execute(
            "SELECT * FROM recruiter_offers WHERE id = 42"
        ).fetchone()
        recruiter = db.execute(
            "SELECT * FROM recruiters WHERE id = 7"
        ).fetchone()

        columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(recruiter_offers)")
        }

    assert offer is not None
    assert offer["title"] == "Ancienne offre Full Stack"
    assert offer["url"] == "https://example.org/old-offer"
    assert recruiter["name"] == "Ancienne Entreprise"
    assert json.loads(offer["skills"]) == ["Java"]

    assert offer["visa_sponsorship_status"] == "unknown"
    assert offer["relocation_support_status"] == "unknown"
    assert offer["senegal_eligibility_status"] == "unknown"
    assert offer["eligibility_notes"] == ""
    assert offer["evidence_url"] == ""
    assert offer["verification_status"] == "unverified"
    assert offer["verified_at"] is None

    assert {
        "visa_sponsorship_status",
        "relocation_support_status",
        "senegal_eligibility_status",
        "eligibility_notes",
        "evidence_url",
        "verification_status",
        "verified_at",
    } <= columns


def test_offer_creation_and_default_values(recruiter_db):
    recruiter = create_test_recruiter()
    offer = create_test_offer(recruiter["id"])

    assert offer["title"] == "Full Stack Software Engineer"
    assert offer["visa_sponsorship_status"] == "unknown"
    assert offer["relocation_support_status"] == "unknown"
    assert offer["senegal_eligibility_status"] == "unknown"
    assert offer["verification_status"] == "unverified"
    assert offer["eligibility_notes"] == ""
    assert offer["evidence_url"] == ""
    assert offer["verified_at"] is None


def test_mobility_fields_are_saved_and_filterable(recruiter_db):
    recruiter = create_test_recruiter()
    offer = create_test_offer(
        recruiter["id"],
        visa_sponsorship_status="confirmed",
        relocation_support_status="mentioned",
        senegal_eligibility_status="eligible",
        eligibility_notes="Éligibilité indiquée dans l'offre de test.",
        evidence_url="https://example.org/jobs/fullstack-test",
        verification_status="verified",
        verified_at="2026-10-18T00:00:00+00:00",
    )

    assert offer["visa_sponsorship_status"] == "confirmed"
    assert offer["relocation_support_status"] == "mentioned"
    assert offer["senegal_eligibility_status"] == "eligible"
    assert offer["verification_status"] == "verified"

    assert len(r.list_recruiter_offers(
        visa_sponsorship_status="confirmed", limit=200
    )) == 1
    assert len(r.list_recruiter_offers(
        relocation_support_status="mentioned", limit=200
    )) == 1
    assert len(r.list_recruiter_offers(
        senegal_eligibility_status="eligible", limit=200
    )) == 1
    assert r.list_recruiter_offers(
        visa_sponsorship_status="not_offered", limit=200
    ) == []


@pytest.mark.parametrize("field,value", [
    ("visa_sponsorship_status", "maybe"),
    ("relocation_support_status", "guaranteed"),
    ("senegal_eligibility_status", "probably"),
    ("verification_status", "trusted"),
])
def test_invalid_statuses_are_rejected(field, value):
    with pytest.raises(ValidationError):
        r.RecruiterOfferIn(
            recruiter_id=1,
            title="Full Stack Software Engineer",
            url="https://example.org/jobs/invalid",
            **{field: value},
        )


def test_invalid_filter_is_rejected(recruiter_db):
    with pytest.raises(HTTPException) as exc:
        r.list_recruiter_offers(
            visa_sponsorship_status="valeur_invalide"
        )
    assert exc.value.status_code == 400
