import sqlite3

import pytest

from app import doctoral


@pytest.fixture
def isolated_doctoral_db(tmp_path, monkeypatch):
    """Chaque test utilise sa propre base SQLite temporaire."""
    db_path = tmp_path / "doctoral_test.db"
    monkeypatch.setattr(doctoral, "DB_PATH", db_path)
    doctoral.init_doctoral_db()
    return db_path


def read_offer(db_path, url):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT * FROM doctoral_offers WHERE url = ?",
            (url,),
        ).fetchone()
        return dict(row) if row else None


def test_unknown_funding_does_not_downgrade_confirmed_full(
    isolated_doctoral_db,
):
    url = "https://example.org/phd/funding-preservation"

    doctoral.save_offer({
        "title": "Doctorat financé en informatique",
        "institution": "Université de test",
        "country": "France",
        "url": url,
        "source": "Source test",
        "funding_status": "CONFIRMED_FULL",
        "funding_evidence": "Fully funded doctoral position",
    })

    doctoral.save_offer({
        "title": "Doctorat financé en informatique",
        "institution": "Université de test",
        "country": "France",
        "url": url,
        "source": "Source test actualisée",
        "funding_status": "UNKNOWN",
        "funding_evidence": "",
    })

    saved = read_offer(isolated_doctoral_db, url)
    assert saved["funding_status"] == "CONFIRMED_FULL"
    assert saved["funding_evidence"] == "Fully funded doctoral position"


def test_empty_deadline_does_not_erase_existing_deadline(
    isolated_doctoral_db,
):
    url = "https://example.org/phd/deadline-preservation"

    doctoral.save_offer({
        "title": "Doctorat avec échéance",
        "url": url,
        "deadline": "2027-01-31",
    })

    doctoral.save_offer({
        "title": "Doctorat avec échéance",
        "url": url,
        "deadline": "",
    })

    saved = read_offer(isolated_doctoral_db, url)
    assert saved["deadline"] == "2027-01-31"


def test_shorter_description_does_not_replace_detailed_description(
    isolated_doctoral_db,
):
    url = "https://example.org/phd/description-preservation"
    detailed = (
        "Projet de recherche détaillé, financement, conditions "
        "de candidature et calendrier complet."
    )

    doctoral.save_offer({
        "title": "Doctorat description détaillée",
        "url": url,
        "description": detailed,
    })

    doctoral.save_offer({
        "title": "Doctorat description détaillée",
        "url": url,
        "description": "Projet de recherche.",
    })

    saved = read_offer(isolated_doctoral_db, url)
    assert saved["description"] == detailed


def test_duplicate_url_does_not_create_second_offer(
    isolated_doctoral_db,
):
    url = "https://example.org/phd/duplicate-check"

    first = doctoral.save_offer({
        "title": "Doctorat test doublon",
        "url": url,
    })
    second = doctoral.save_offer({
        "title": "Doctorat test doublon actualisé",
        "url": url,
    })

    with sqlite3.connect(isolated_doctoral_db) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM doctoral_offers WHERE url = ?",
            (url,),
        ).fetchone()[0]

    assert first is True
    assert second is False
    assert count == 1
