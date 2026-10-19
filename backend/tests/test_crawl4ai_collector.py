import asyncio
import json
import os
import sys
import types
from concurrent.futures import ThreadPoolExecutor

from app import main


def test_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(main, "CRAWL4AI_ENABLED", False)
    monkeypatch.setattr(os, "environ", dict(os.environ, CRAWL4AI_SEED_URLS="https://example.com/jobs"))

    async def forbidden(*args, **kwargs):
        raise AssertionError("Aucune collecte ne doit être lancée")

    monkeypatch.setattr(main.asyncio, "to_thread", forbidden)

    assert asyncio.run(main.collect_crawl4ai()) == []


def test_returns_empty_without_seed_urls(monkeypatch):
    monkeypatch.setattr(main, "CRAWL4AI_ENABLED", True)
    monkeypatch.setenv("CRAWL4AI_SEED_URLS", "")

    async def forbidden(*args, **kwargs):
        raise AssertionError("Aucune collecte ne doit être lancée")

    monkeypatch.setattr(main.asyncio, "to_thread", forbidden)

    assert asyncio.run(main.collect_crawl4ai()) == []


def test_extracts_jobposting_jsonld_with_mocked_crawler(monkeypatch):
    monkeypatch.setattr(main, "CRAWL4AI_ENABLED", True)
    monkeypatch.setenv("CRAWL4AI_SEED_URLS", "https://example.test/careers")

    html = """
    <html><head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "JobPosting",
      "title": "Full Stack Developer",
      "url": "https://example.test/jobs/123",
      "datePosted": "2026-10-17",
      "employmentType": "FULL_TIME",
      "description": "React and Java development.",
      "hiringOrganization": {"name": "Example Tech"},
      "jobLocation": {
        "address": {
          "addressLocality": "Dakar",
          "addressCountry": "Senegal"
        }
      }
    }
    </script></head><body></body></html>
    """

    class FakeResult:
        def __init__(self):
            self.html = html

    class FakeCrawler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def arun(self, url, config):
            assert url == "https://example.test/careers"
            return FakeResult()

    fake_module = types.ModuleType("crawl4ai")
    fake_module.AsyncWebCrawler = FakeCrawler
    fake_module.CrawlerRunConfig = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "crawl4ai", fake_module)

    # Garder le vrai to_thread : le collecteur appelle asyncio.run dans ce thread.

    jobs = asyncio.run(main.collect_crawl4ai())

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Full Stack Developer"
    assert jobs[0]["company"] == "Example Tech"
    assert jobs[0]["url"] == "https://example.test/jobs/123"
    assert jobs[0]["source"] == "Crawl4AI · JSON-LD"
    assert jobs[0]["content_hash"]
    assert "Dakar" in jobs[0]["location"]


def test_ignores_non_jobposting_jsonld(monkeypatch):
    monkeypatch.setattr(main, "CRAWL4AI_ENABLED", True)
    monkeypatch.setenv("CRAWL4AI_SEED_URLS", "https://example.test/careers")

    html = """
    <script type="application/ld+json">
    {"@type": "Organization", "name": "Example"}
    </script>
    """

    class FakeResult:
        pass

    FakeResult.html = html

    class FakeCrawler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def arun(self, url, config):
            return FakeResult()

    fake_module = types.ModuleType("crawl4ai")
    fake_module.AsyncWebCrawler = FakeCrawler
    fake_module.CrawlerRunConfig = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "crawl4ai", fake_module)

    # Garder le vrai to_thread pour éviter une récursion dans le mock.

    assert asyncio.run(main.collect_crawl4ai()) == []


def test_catalog_marks_crawl4ai_as_configurable():
    sources = {
        item["name"]: item
        for item in main.source_catalog()["sources"]
    }

    assert sources["Crawl4AI"]["configuration_required"] is True
    assert sources["Crawl4AI"]["enabled"] is main.CRAWL4AI_ENABLED
