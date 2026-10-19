import pytest

from app import recruiters
import app.recruiter_sync as sync


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(recruiters, "DB_PATH", tmp_path / "recruiters-test.db")
    recruiters.init_recruiters_db()


def sample_post():
    return {
        "company_candidate": "Entreprise Test",
        "comment_url": "https://news.ycombinator.com/item?id=123456",
        "text_preview": "Recherche ingénieur Java et Spring Boot",
        "skills": ["Java", "Spring Boot"],
        "published_at": "2026-10-18T12:00:00+00:00",
        "location_restrictions": [],
        "individual_offers": [
            {
                "url": "https://example.com/jobs/backend-test",
                "title_candidate": "Développeur Backend Java",
                "employer_candidate": "Entreprise Test",
                "title_status": "confirmed_from_public_api",
            }
        ],
    }


def test_sync_is_idempotent_and_preserves_unknown_mobility(
    isolated_db, monkeypatch
):
    monkeypatch.setattr(
        sync, "collect_hiring_records",
        lambda **kwargs: {"posts": [sample_post()]},
    )

    first = sync.sync_hackernews_recruiters()
    second = sync.sync_hackernews_recruiters()

    with recruiters.connect() as db:
        recruiter_count = db.execute(
            "SELECT COUNT(*) FROM recruiters"
        ).fetchone()[0]
        offer_count = db.execute(
            "SELECT COUNT(*) FROM recruiter_offers"
        ).fetchone()[0]
        offer = db.execute(
            """
            SELECT visa_sponsorship_status, relocation_support_status,
                   senegal_eligibility_status, verification_status
            FROM recruiter_offers
            """
        ).fetchone()
        runs = db.execute(
            "SELECT COUNT(*) FROM recruiter_sync_runs"
        ).fetchone()[0]

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert recruiter_count == 1
    assert offer_count == 1
    assert offer["visa_sponsorship_status"] == "unknown"
    assert offer["relocation_support_status"] == "unknown"
    assert offer["senegal_eligibility_status"] == "unknown"
    assert offer["verification_status"] == "verified"
    assert runs == 2


def test_sync_records_failure(isolated_db, monkeypatch):
    def failing_collector(**kwargs):
        raise RuntimeError("Erreur simulée du collecteur")

    monkeypatch.setattr(sync, "collect_hiring_records", failing_collector)

    with pytest.raises(RuntimeError, match="Erreur simulée"):
        sync.sync_hackernews_recruiters()

    with recruiters.connect() as db:
        run = db.execute(
            """
            SELECT status, error, finished_at
            FROM recruiter_sync_runs
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()

    assert run["status"] == "failed"
    assert "Erreur simulée" in run["error"]
    assert run["finished_at"] is not None

def test_sync_preserves_existing_verified_mobility_data(
    isolated_db, monkeypatch
):
    monkeypatch.setattr(
        sync, "collect_hiring_records",
        lambda **kwargs: {"posts": [sample_post()]},
    )

    sync.sync_hackernews_recruiters()

    with recruiters.connect() as db:
        db.execute("""
            UPDATE recruiter_offers
            SET location = 'Berlin',
                country = 'Germany',
                work_mode = 'remote',
                contract_type = 'CDI',
                visa_sponsorship_status = 'confirmed',
                relocation_support_status = 'mentioned',
                senegal_eligibility_status = 'eligible',
                eligibility_notes = 'Mobilité confirmée par une vérification manuelle.',
                evidence_url = 'https://example.com/visa-policy',
                verification_status = 'verified',
                verified_at = '2026-10-18T12:00:00+00:00'
        """)
        db.commit()

    sync.sync_hackernews_recruiters()

    with recruiters.connect() as db:
        offer = db.execute("""
            SELECT location, country, work_mode, contract_type,
                   visa_sponsorship_status, relocation_support_status,
                   senegal_eligibility_status, eligibility_notes,
                   evidence_url, verification_status, verified_at
            FROM recruiter_offers
        """).fetchone()

    assert offer["location"] == "Berlin"
    assert offer["country"] == "Germany"
    assert offer["work_mode"] == "remote"
    assert offer["contract_type"] == "CDI"
    assert offer["visa_sponsorship_status"] == "confirmed"
    assert offer["relocation_support_status"] == "mentioned"
    assert offer["senegal_eligibility_status"] == "eligible"
    assert offer["eligibility_notes"] == (
        "Mobilité confirmée par une vérification manuelle."
    )
    assert offer["evidence_url"] == "https://example.com/visa-policy"
    assert offer["verification_status"] == "verified"
    assert offer["verified_at"] == "2026-10-18T12:00:00+00:00"



def test_sync_transmits_detected_mobility_statuses(isolated_db, monkeypatch):
    post = sample_post()
    post["mobility_statuses"] = {
        "visa_sponsorship_status": "not_offered",
        "relocation_support_status": "confirmed",
        "senegal_eligibility_status": "eligible",
    }
    monkeypatch.setattr(
        sync, "collect_hiring_records",
        lambda **kwargs: {"posts": [post]},
    )

    result = sync.sync_hackernews_recruiters()

    with recruiters.connect() as db:
        offer = db.execute("""
            SELECT visa_sponsorship_status, relocation_support_status,
                   senegal_eligibility_status
            FROM recruiter_offers
        """).fetchone()

    assert result["status"] == "success"
    assert offer["visa_sponsorship_status"] == "not_offered"
    assert offer["relocation_support_status"] == "confirmed"
    assert offer["senegal_eligibility_status"] == "eligible"


def test_sync_keeps_restrictions_out_of_geographic_fields(
    isolated_db, monkeypatch
):
    post = sample_post()
    post["location_restrictions"] = [
        "Présence sur site ou hybride",
        "Parrainage de visa mentionné",
    ]
    monkeypatch.setattr(
        sync, "collect_hiring_records",
        lambda **kwargs: {"posts": [post]},
    )

    result = sync.sync_hackernews_recruiters()

    with recruiters.connect() as db:
        offer = db.execute("""
            SELECT location, country, eligibility_notes
            FROM recruiter_offers
        """).fetchone()

    assert result["status"] == "success"
    assert offer["location"] == ""
    assert offer["country"] == ""
    assert "Présence sur site ou hybride" in offer["eligibility_notes"]
    assert "Parrainage de visa mentionné" in offer["eligibility_notes"]
