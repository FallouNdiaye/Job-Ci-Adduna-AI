import pytest
from pydantic import ValidationError

import app.trainings as t


@pytest.fixture
def training_db(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "DB_PATH", tmp_path / "trainings-test.db")
    t.init_trainings_db()
    return t.DB_PATH


def sample_training(**overrides):
    data = {
        "title": "Formation développeur web",
        "provider": "FORCE-N",
        "category": "formation",
        "country": "Sénégal",
        "description": "Programme complet de développement web et mobile.",
        "official_url": "https://example.org/formations/dev-web",
        "application_url": "https://example.org/candidature/dev-web",
        "funding_status": "CONFIRMED_FULL",
        "funding_evidence": "La page officielle indique une prise en charge complète.",
        "cost_details": "Formation prise en charge selon les conditions publiées.",
        "deadline": "2099-12-31",
        "source_name": "FORCE-N",
    }
    data.update(overrides)
    return t.TrainingIn(**data)


def test_create_training_and_defaults(training_db):
    item = t.save_training(sample_training())

    assert item["title"] == "Formation développeur web"
    assert item["funding_status"] == "CONFIRMED_FULL"
    assert item["application_status"] == "À examiner"
    assert item["is_favorite"] == 0
    assert item["deadline"] == "2099-12-31"


def test_same_official_url_does_not_create_duplicate(training_db):
    first = t.save_training(sample_training())
    second = t.save_training(sample_training(description="Description actualisée."))

    assert first["id"] == second["id"]
    with t.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM training_opportunities"
        ).fetchone()[0] == 1


def test_incomplete_refresh_preserves_description_deadline_and_funding(training_db):
    first = t.save_training(sample_training())

    refreshed = t.save_training(sample_training(
        description="Bref résumé.",
        deadline=None,
        funding_status="UNKNOWN",
        funding_evidence="",
        cost_details="",
        application_url="",
    ))

    assert refreshed["id"] == first["id"]
    assert refreshed["description"] == first["description"]
    assert refreshed["deadline"] == "2099-12-31"
    assert refreshed["funding_status"] == "CONFIRMED_FULL"
    assert refreshed["funding_evidence"] == first["funding_evidence"]
    assert refreshed["cost_details"] == first["cost_details"]
    assert refreshed["application_url"] == first["application_url"]


def test_confirmed_full_funding_is_not_downgraded_to_partial(training_db):
    t.save_training(sample_training(funding_status="CONFIRMED_FULL"))

    refreshed = t.save_training(sample_training(
        funding_status="PARTIAL",
        funding_evidence="Collecte moins précise.",
    ))

    assert refreshed["funding_status"] == "CONFIRMED_FULL"


@pytest.mark.parametrize("url", [
    "http://example.org/formation",
    "https://user:password@example.org/formation",
    "https://localhost/formation",
    "https://127.0.0.1/formation",
    "https://example.org/formation#section",
])
def test_rejects_unsafe_urls(url):
    with pytest.raises(ValidationError):
        sample_training(official_url=url)


def test_deadline_status_is_derived_without_inventing_dates():
    expired = {
        "deadline": "2000-01-01",
        "is_favorite": 0,
    }
    upcoming = {
        "deadline": "2099-12-31",
        "is_favorite": 0,
    }
    unknown = {
        "deadline": None,
        "is_favorite": 0,
    }

    assert t.present(expired)["opportunity_status"] == "expirée"
    assert t.present(upcoming)["opportunity_status"] == "date limite à venir"
    assert t.present(unknown)["opportunity_status"] == "à vérifier"

    # L'échéance ne prouve pas que les inscriptions sont ouvertes.
    expected = "Inscriptions non vérifiées"
    assert t.present(expired)["enrollment_status"] == expected
    assert t.present(upcoming)["enrollment_status"] == expected
    assert t.present(unknown)["enrollment_status"] == expected


def test_manual_application_tracking(training_db):
    item = t.save_training(sample_training())

    updated = t.update_training(
        item["id"],
        t.TrainingUpdate(
            application_status="Candidature préparée",
            is_favorite=True,
        ),
    )

    assert updated["application_status"] == "Candidature préparée"
    assert updated["is_favorite"] is True
