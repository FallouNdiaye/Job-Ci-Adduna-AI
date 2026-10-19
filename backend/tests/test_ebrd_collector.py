import asyncio
from urllib.parse import urlparse

from app.main import (
    EBRD_BASE_URL,
    EBRD_CATEGORY_URLS,
    _ebrd_date,
    _EBRD_IT_TITLE_RE,
    collect_ebrd,
    source_catalog,
)


class FakeResponse:
    def __init__(self, body):
        self.text = body
        self.content = body.encode()

    def raise_for_status(self):
        pass


class FakeClient:
    def __init__(self, pages, details):
        self.pages = pages
        self.details = details
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        if url in self.pages:
            return FakeResponse(self.pages[url])
        return FakeResponse(self.details.get(url, ""))


def listing(url, title):
    return f'<html><a href="{url}">{title}</a></html>'


def detail(title, body):
    return f"<html><h1>{title}</h1><main>{body}</main></html>"


def test_ebrd_collects_open_technical_job_and_deduplicates():
    url = EBRD_BASE_URL + "/job/Sofia-Associate-Software-Developer/123456/"
    html = listing(url, "Associate, Software Developer Full Stack")
    client = FakeClient(
        {page: html for page in EBRD_CATEGORY_URLS},
        {
            url: detail(
                "Associate, Software Developer Full Stack",
                "Posting Date 8 Oct 2026\n"
                "Office Country Bulgaria\n"
                "Office City Sofia\n"
                "Division Information Technology\n"
                "Contract Type Fixed Term\n"
                "Contract Length 3 years\n"
                "Posting End Date 26/10/2099",
            )
        },
    )

    jobs = asyncio.run(collect_ebrd(client))

    assert len(jobs) == 1
    assert jobs[0]["company"].startswith("European Bank")
    assert jobs[0]["external_id"] == "123456"
    assert jobs[0]["source"] == "EBRD Careers"
    assert "Sofia" in jobs[0]["location"]
    assert "26/10/2099" in jobs[0]["description"]
    assert sum(call == url for call in client.calls) == 1


def test_ebrd_excludes_expired_technical_job():
    url = EBRD_BASE_URL + "/job/Sofia-Software-Developer/123457/"
    client = FakeClient(
        {EBRD_CATEGORY_URLS[0]: listing(url, "Software Developer")},
        {
            url: detail(
                "Software Developer",
                "Posting End Date 01/01/2020",
            )
        },
    )

    assert asyncio.run(collect_ebrd(client)) == []


def test_ebrd_keeps_job_when_deadline_is_missing_but_marks_uncertainty():
    url = EBRD_BASE_URL + "/job/Sofia-Frontend-Developer/123458/"
    client = FakeClient(
        {EBRD_CATEGORY_URLS[0]: listing(url, "Associate, Developer Frontend")},
        {
            url: detail(
                "Associate, Developer Frontend",
                "Office City Sofia\nOffice Country Bulgaria",
            )
        },
    )

    jobs = asyncio.run(collect_ebrd(client))

    assert len(jobs) == 1
    assert "non détectée" in jobs[0]["description"].lower()
    assert "disponibilité à confirmer" in jobs[0]["description"].lower()


def test_ebrd_rejects_external_and_non_job_links():
    client = FakeClient(
        {
            EBRD_CATEGORY_URLS[0]: (
                '<a href="https://example.com/job/evil/123/">Software Developer</a>'
                '<a href="/about-us/">Software Developer</a>'
                '<a href="https://jobs.ebrd.com/job/Sofia-Developer/not-an-id/">Developer</a>'
            )
        },
        {},
    )

    assert asyncio.run(collect_ebrd(client)) == []
    assert all(urlparse(url).hostname == "jobs.ebrd.com" for url in client.calls)


def test_ebrd_date_parser_handles_expected_format_and_invalid_dates():
    parsed, original = _ebrd_date("Posting End Date 26/10/2026")
    assert parsed.isoformat() == "2026-10-26"
    assert original == "26/10/2026"

    parsed, original = _ebrd_date("Posting End Date 99/99/2026")
    assert parsed is None
    assert original == "99/99/2026"


def test_ebrd_title_filter_covers_relevant_technical_roles():
    for title in (
        "Associate, Software Developer Full Stack",
        "Associate, Developer Frontend",
        "Principal, Full Stack Developer",
        "Analyst, ServiceNow Engineer",
        "QA Automation Engineer",
        "Principal, Engineering, AI",
        "Cybersecurity Engineer",
        "Mobile Developer",
    ):
        assert _EBRD_IT_TITLE_RE.search(title), title


def test_ebrd_catalogue_entry_is_enabled():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["EBRD Careers"]["enabled"] is True
    assert sources["EBRD Careers"]["configuration_required"] is False
