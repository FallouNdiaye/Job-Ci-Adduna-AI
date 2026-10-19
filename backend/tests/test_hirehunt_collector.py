import asyncio
from types import SimpleNamespace

from app import main


def test_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(main, "HIREHUNT_ENABLED", False)

    assert asyncio.run(main.collect_hirehunt()) == []


def test_normalizes_dictionary_job_when_enabled(monkeypatch):
    monkeypatch.setattr(main, "HIREHUNT_ENABLED", True)

    raw = {
        "title": "Java Spring Developer",
        "company": "Example Tech",
        "url": "https://example.com/jobs/java",
        "location": "Worldwide",
        "description": "Java and Spring Boot development.",
    }

    monkeypatch.setattr(
        main.asyncio,
        "to_thread",
        lambda fn: asyncio.sleep(0, result=[raw]),
    )

    jobs = asyncio.run(main.collect_hirehunt())

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Java Spring Developer"
    assert jobs[0]["company"] == "Example Tech"
    assert jobs[0]["url"] == "https://example.com/jobs/java"
    assert jobs[0]["source"].startswith("Hirehunt")
    assert jobs[0]["content_hash"]


def test_ignores_invalid_records(monkeypatch):
    monkeypatch.setattr(main, "HIREHUNT_ENABLED", True)

    raw_jobs = [
        None,
        "invalid",
        {"title": "Incomplete listing"},
    ]

    monkeypatch.setattr(
        main.asyncio,
        "to_thread",
        lambda fn: asyncio.sleep(0, result=raw_jobs),
    )

    jobs = asyncio.run(main.collect_hirehunt())

    assert jobs == []


def test_catalog_marks_hirehunt_as_optional():
    sources = {
        item["name"]: item
        for item in main.source_catalog()["sources"]
    }

    assert sources["Hirehunt"]["configuration_required"] is True
    assert sources["Hirehunt"]["enabled"] is main.HIREHUNT_ENABLED
