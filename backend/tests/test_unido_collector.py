import asyncio
from urllib.parse import urlparse, parse_qs

from app.main import (
    UNIDO_BASE_URL,
    UNIDO_SEARCH_URL,
    collect_unido,
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
        parsed = urlparse(url)
        if parsed.path == urlparse(UNIDO_SEARCH_URL).path:
            keyword = parse_qs(parsed.query).get("q", [""])[0]
            return FakeResponse(self.pages.get(keyword, ""))
        return FakeResponse(self.details.get(url, ""))


def listing(url, title):
    return f'<html><a href="{url}">{title}</a></html>'


def detail(title, body):
    return f"<html><h1>{title}</h1><main>{body}</main></html>"


def test_unido_collects_technical_open_job_and_marks_local_recruitment():
    url = UNIDO_BASE_URL + "/job/Vienna-Software-Developer/12345/"
    client = FakeClient(
        {"software": listing(url, "Software Developer")},
        {
            url: detail(
                "Software Developer",
                "Application Deadline: 12-Nov-2099\n"
                "Location: Vienna, Austria\n"
                "This post is for local recruitment only.",
            )
        },
    )
    jobs = asyncio.run(collect_unido(client))
    assert len(jobs) == 1
    assert jobs[0]["company"] == "UNIDO"
    assert jobs[0]["external_id"] == "12345"
    assert jobs[0]["recruitment_scope"] == "local"
    assert "local recruitment" in jobs[0]["description"].lower()


def test_unido_excludes_expired_technical_job():
    url = UNIDO_BASE_URL + "/job/Vienna-Software-Developer/12346/"
    client = FakeClient(
        {"software": listing(url, "Software Developer")},
        {
            url: detail(
                "Software Developer",
                "Application Deadline: 01-Jan-2020\nLocation: Vienna",
            )
        },
    )
    assert asyncio.run(collect_unido(client)) == []


def test_unido_excludes_nontechnical_title_even_if_page_mentions_software():
    url = UNIDO_BASE_URL + "/job/Vienna-Project-Associate/12347/"
    client = FakeClient(
        {"software": listing(url, "Project Associate")},
        {
            url: detail(
                "Project Associate",
                "Supports projects involving software and digital tools.",
            )
        },
    )
    assert asyncio.run(collect_unido(client)) == []


def test_unido_rejects_external_and_non_job_links():
    client = FakeClient(
        {
            "software": (
                '<a href="https://example.com/job/evil/1/">Software Developer</a>'
                '<a href="/about-us/">Software Developer</a>'
            )
        },
        {},
    )
    assert asyncio.run(collect_unido(client)) == []
    assert all("example.com" not in url for url in client.calls)


def test_unido_catalogue_entry_is_enabled():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["UNIDO Careers"]["enabled"] is True
    assert sources["UNIDO Careers"]["configuration_required"] is False
