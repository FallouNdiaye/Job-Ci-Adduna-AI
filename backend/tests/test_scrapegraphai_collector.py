import asyncio
import os
import sys
import types

from app import main


def test_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(main, "SCRAPEGRAPHAI_ENABLED", False)
    monkeypatch.setenv("SCRAPEGRAPHAI_URLS", "https://example.test/jobs")

    assert asyncio.run(main.collect_scrapegraphai()) == []


def test_returns_empty_without_urls(monkeypatch):
    monkeypatch.setattr(main, "SCRAPEGRAPHAI_ENABLED", True)
    monkeypatch.setenv("SCRAPEGRAPHAI_URLS", " , ")
    monkeypatch.setenv("SGAI_API_KEY", "fake-test-key")

    assert asyncio.run(main.collect_scrapegraphai()) == []


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.setattr(main, "SCRAPEGRAPHAI_ENABLED", True)
    monkeypatch.setenv("SCRAPEGRAPHAI_URLS", "https://example.test/jobs")
    monkeypatch.delenv("SGAI_API_KEY", raising=False)

    try:
        asyncio.run(main.collect_scrapegraphai())
    except RuntimeError as exc:
        assert "SGAI_API_KEY absent" in str(exc)
    else:
        raise AssertionError("Une clé absente doit produire une erreur explicite.")


def test_normalizes_successful_mocked_response(monkeypatch):
    monkeypatch.setattr(main, "SCRAPEGRAPHAI_ENABLED", True)
    monkeypatch.setenv("SCRAPEGRAPHAI_URLS", "https://example.test/jobs")
    monkeypatch.setenv("SGAI_API_KEY", "fake-test-key")

    class FakeResponse:
        status = "success"
        error = None
        elapsed_ms = 10
        data = {
            "jobs": [{
                "title": "Full Stack Developer",
                "company": "Example Tech",
                "url": "https://example.test/jobs/123",
                "location": "Dakar",
                "description": "React and Java",
                "publication_date": "2026-10-17",
                "job_type": "Full-time",
                "work_mode": "Remote",
            }]
        }

    class FakeScrapeGraphAI:
        def __init__(self):
            self._http = types.SimpleNamespace(timeout=None)

        def extract(self, **kwargs):
            assert kwargs["url"] == "https://example.test/jobs"
            assert "jobs" in kwargs["schema"]["properties"]
            return FakeResponse()

    fake_module = types.ModuleType("scrapegraph_py")
    fake_module.ScrapeGraphAI = FakeScrapeGraphAI
    monkeypatch.setitem(sys.modules, "scrapegraph_py", fake_module)

    jobs = asyncio.run(main.collect_scrapegraphai())

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Full Stack Developer"
    assert jobs[0]["company"] == "Example Tech"
    assert jobs[0]["url"] == "https://example.test/jobs/123"
    assert jobs[0]["source"] == "ScrapeGraphAI Cloud"
    assert jobs[0]["content_hash"]


def test_skips_failed_api_response_without_stopping(monkeypatch):
    monkeypatch.setattr(main, "SCRAPEGRAPHAI_ENABLED", True)
    monkeypatch.setenv(
        "SCRAPEGRAPHAI_URLS",
        "https://example.test/one,https://example.test/two",
    )
    monkeypatch.setenv("SGAI_API_KEY", "fake-test-key")

    visited = []

    class FakeScrapeGraphAI:
        def __init__(self):
            self._http = types.SimpleNamespace(timeout=None)

        def extract(self, **kwargs):
            visited.append(kwargs["url"])
            if kwargs["url"].endswith("/one"):
                return types.SimpleNamespace(
                    status="error",
                    error="Insufficient credits",
                    elapsed_ms=5,
                    data=None,
                )
            return types.SimpleNamespace(
                status="success",
                error=None,
                elapsed_ms=5,
                data={"jobs": [{
                    "title": "Java Developer",
                    "company": "Second Company",
                    "url": "https://example.test/job/456",
                }]},
            )

    fake_module = types.ModuleType("scrapegraph_py")
    fake_module.ScrapeGraphAI = FakeScrapeGraphAI
    monkeypatch.setitem(sys.modules, "scrapegraph_py", fake_module)

    jobs = asyncio.run(main.collect_scrapegraphai())

    assert visited == [
        "https://example.test/one",
        "https://example.test/two",
    ]
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Java Developer"


def test_catalog_marks_scrapegraphai_as_configurable():
    sources = {
        item["name"]: item
        for item in main.source_catalog()["sources"]
    }

    assert sources["ScrapeGraphAI"]["configuration_required"] is True
    assert sources["ScrapeGraphAI"]["requires_llm_key"] is True
