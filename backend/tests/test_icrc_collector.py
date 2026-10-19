import asyncio
from datetime import date, timedelta

from app.main import _icrc_deadline, collect_icrc


class FakeResponse:
    def __init__(self, html):
        self.content = html.encode()

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError(f"URL inattendue : {url}")
        return FakeResponse(self.pages[url])


def test_icrc_parses_application_deadline():
    assert _icrc_deadline("Deadline of Application: 06 November 2026") == date(2026, 11, 6)


def test_icrc_keeps_unknown_deadline_unknown():
    assert _icrc_deadline("Deadline of Application: To be confirmed") is None


def test_icrc_collects_it_job_and_deduplicates_links():
    listing = """
    <html><body>
      <a href="/job/Manila-Finance-ERP-Engineer-33687/1448282733/">
        Finance ERP Engineer
      </a>
      <a href="/job/Manila-Finance-ERP-Engineer-33687/1448282733/">
        Finance ERP Engineer
      </a>
      <a href="/job/Manila-Accountant-123/123456789/">
        General Ledger Accountant
      </a>
    </body></html>
    """
    detail_url = (
        "https://careers.icrc.org/job/"
        "Manila-Finance-ERP-Engineer-33687/1448282733/"
    )
    detail = """
    <html><body>
      <h1>Finance ERP Engineer</h1>
      <p>Job location: Manila, Philippines</p>
      <p>Contract type: Open-ended contract</p>
      <p>Deadline of Application: 06 November 2026</p>
      <p>Administers and supports financial ERP applications.</p>
      <p>Experience with PeopleSoft ERP and IT security.</p>
    </body></html>
    """
    client = FakeClient({
        "https://careers.icrc.org/go/All-Jobs/3807301/": listing,
        detail_url: detail,
    })

    jobs = asyncio.run(collect_icrc(client))

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Finance ERP Engineer"
    assert jobs[0]["company"] == "International Committee of the Red Cross (ICRC)"
    assert jobs[0]["source"] == "ICRC Careers"
    assert jobs[0]["external_id"] == "1448282733"
    assert jobs[0]["url"] == detail_url
    assert "PeopleSoft ERP" in jobs[0]["description"]
    assert len(client.calls) == 2


def test_icrc_excludes_expired_deadline():
    expired = (date.today() - timedelta(days=2)).strftime("%d %B %Y")
    listing = """
    <a href="/job/Manila-Finance-ERP-Engineer-33687/1448282733/">
      Finance ERP Engineer
    </a>
    """
    detail_url = (
        "https://careers.icrc.org/job/"
        "Manila-Finance-ERP-Engineer-33687/1448282733/"
    )
    detail = f"""
    <h1>Finance ERP Engineer</h1>
    <p>Deadline of Application: {expired}</p>
    <p>ERP applications and IT systems</p>
    """
    client = FakeClient({
        "https://careers.icrc.org/go/All-Jobs/3807301/": listing,
        detail_url: detail,
    })

    assert asyncio.run(collect_icrc(client)) == []


def test_icrc_rejects_external_job_links():
    listing = """
    <a href="https://example.com/job/Software-Engineer/123/">
      Software Engineer
    </a>
    """
    client = FakeClient({
        "https://careers.icrc.org/go/All-Jobs/3807301/": listing,
    })

    assert asyncio.run(collect_icrc(client)) == []
