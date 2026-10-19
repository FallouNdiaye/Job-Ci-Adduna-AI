import asyncio
from datetime import date, timedelta

from app.main import (
    _drc_is_relevant,
    _drc_parse_date,
    collect_drc,
    source_catalog,
)


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, title="Software Engineer", deadline=None, apply=True):
        self.title = title
        self.deadline = deadline or (date.today() + timedelta(days=10)).strftime("%d %b %Y")
        self.apply = apply
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        if url == "https://drc.ngo/en/jobs/":
            return FakeResponse(f"""
            <html><body><main id="main"><section id="jobList">
              <article class="jobList__item">
                <h3><a class="casper" href="/jobs/job?id=177123">{self.title}</a></h3>
                <span>Senegal</span><span>Published 16 Oct 2026</span>
                <span>Deadline {self.deadline}</span>
              </article>
              <article class="jobList__item">
                <h3><a class="casper" href="https://evil.example/jobs/job?id=999">Data Engineer</a></h3>
              </article>
            </section></main></body></html>
            """)
        if url == "https://drc.ngo/jobs/job?id=177123":
            apply = (
                '<a href="https://candidate.hr-manager.net/ApplicationInit.aspx?cid=1036&ProjectId=177123">Apply Now</a>'
                if self.apply else ""
            )
            return FakeResponse(f"""
            <html><head><meta property="og:title" content="{self.title}"></head>
            <body><main id="main">
              <h1>{self.title}</h1>
              <p>Country Senegal Workplace Dakar Contract International contract</p>
              <p>Published 16 Oct 2026 Deadline {self.deadline}</p>
              <p>Build and maintain software systems.</p>{apply}
            </main></body></html>
            """)
        raise AssertionError(f"Unexpected URL: {url}")


def test_drc_keeps_relevant_job_and_official_application_link():
    client = FakeClient()
    jobs = asyncio.run(collect_drc(client))
    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "DRC Careers"
    assert job["company"] == "Danish Refugee Council (DRC)"
    assert job["external_id"] == "177123"
    assert job["url"] == "https://drc.ngo/jobs/job?id=177123"
    assert "candidate.hr-manager.net/ApplicationInit.aspx" in job["description"]
    assert "date limite" in job["description"].lower()
    assert all("evil.example" not in url for url in client.calls)


def test_drc_excludes_irrelevant_titles():
    assert not _drc_is_relevant("Finance Assistant")
    assert not _drc_is_relevant("Executive Director Partnerships")
    assert _drc_is_relevant("Information Management Manager")
    assert _drc_is_relevant("Software Engineer")


def test_drc_excludes_expired_deadlines():
    expired = (date.today() - timedelta(days=5)).strftime("%d %b %Y")
    assert asyncio.run(collect_drc(FakeClient(deadline=expired))) == []


def test_drc_does_not_require_an_application_link():
    jobs = asyncio.run(collect_drc(FakeClient(apply=False)))
    assert len(jobs) == 1
    assert "non détecté" in jobs[0]["description"]


def test_drc_parses_explicit_dates_only():
    assert _drc_parse_date("Deadline 26 Oct 2026") == date(2026, 10, 26)
    assert _drc_parse_date("2026-12-15") == date(2026, 12, 15)
    assert _drc_parse_date("No deadline announced") is None


def test_drc_is_enabled_in_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["DRC Careers"]["enabled"] is True
    assert sources["DRC Careers"]["configuration_required"] is False
