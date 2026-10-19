import asyncio
from datetime import date, timedelta

from app.main import collect_ecowas, source_catalog


BASE = "https://www.ecowas.int"
LIST_URL = BASE + "/jobs/?lang=fr"
IT_URL = BASE + "/jobs/it-officer/?lang=fr"
FINANCE_URL = BASE + "/jobs/finance-director/?lang=fr"


class FakeResponse:
    def __init__(self, content, url):
        self.content = content.encode()
        self.url = url

    def raise_for_status(self):
        pass


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError(f"URL inattendue : {url}")
        return FakeResponse(self.pages[url], url)


def listing_page():
    return f"""
    <html><body>
      <h1>Jobs</h1>
      <a href="/jobs/it-officer/?lang=fr">Chargé(e) des technologies de l’information</a>
      <a href="{FINANCE_URL}">Directeur financier</a>
      <a href="/jobs/page/2/?lang=fr">2</a>
    </body></html>
    """


def test_keeps_it_offer_and_marks_unknown_deadline():
    client = FakeClient({
        LIST_URL: listing_page(),
        IT_URL: """
          <html><h1>Chargé(e) des technologies de l’information</h1>
          <article><time datetime="2026-09-22">Sep 22, 2026</time>
          <p>Responsable des systèmes informatiques.</p></article></html>
        """,
        "https://www.ecowas.int/jobs/page/2/?lang=fr": "<html><body>Jobs</body></html>",
    })
    jobs = asyncio.run(collect_ecowas(client))
    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "CEDEAO Careers"
    assert job["company"] == "CEDEAO / ECOWAS"
    assert job["external_id"] == "ecowas:it-officer"
    assert job["url"] == IT_URL
    assert "non détectée" in job["description"]
    assert "date limite" in job["description"].lower()
    assert FINANCE_URL not in client.calls


def test_excludes_expired_offer():
    client = FakeClient({
        LIST_URL: listing_page(),
        IT_URL: """
          <html><h1>IT Officer</h1><article>
          <p>Application deadline: 2000-01-01</p>
          <p>Information technology officer.</p></article></html>
        """,
        "https://www.ecowas.int/jobs/page/2/?lang=fr": "<html><body>Jobs</body></html>",
    })
    assert asyncio.run(collect_ecowas(client)) == []


def test_source_is_enabled_in_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["CEDEAO Careers"]["enabled"] is True
    assert sources["CEDEAO Careers"]["configuration_required"] is False
