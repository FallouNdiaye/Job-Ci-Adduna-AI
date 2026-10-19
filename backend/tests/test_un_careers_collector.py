import asyncio

from app.main import UN_CAREERS_RSS_URL, collect_un_careers, source_catalog


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, headers))
        return FakeResponse(self.content)


def rss_item(title, url, description):
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<link>{url}</link>"
        f"<description><![CDATA[{description}]]></description>"
        "</item>"
    )


def rss(*items):
    return (
        "<rss version='2.0'><channel>"
        + "".join(items)
        + "</channel></rss>"
    ).encode("utf-8")


def test_collects_official_un_it_job_and_extracts_fields():
    url = "https://careers.un.org/jobSearchDescription/123456?language=fr"
    description = (
        "Job Network: Information and Telecommunication Technology\n"
        "Job Family: Information Technology\n"
        "Department/Office: United Nations\n"
        "Duty Station: Nairobi\n"
        "Level: P-2\n"
        "Publication Date: 17 October 2026\n"
        "Développement software et application support."
    )
    client = FakeClient(rss(rss_item("Information Systems Officer", url, description)))

    jobs = asyncio.run(collect_un_careers(client))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "ONU Careers RSS"
    assert job["url"] == url
    assert job["external_id"] == "123456"
    assert job["company"] == "United Nations"
    assert job["location"] == "Nairobi"
    assert client.calls[0][0] == UN_CAREERS_RSS_URL


def test_rejects_non_it_job():
    client = FakeClient(rss(rss_item(
        "Finance Assistant",
        "https://careers.un.org/jobSearchDescription/123457",
        "Finance, accounting, budgeting and administrative support.",
    )))

    assert asyncio.run(collect_un_careers(client)) == []


def test_rejects_non_official_job_urls():
    client = FakeClient(rss(rss_item(
        "Software Developer",
        "https://example.com/jobSearchDescription/123458",
        "Software development and databases.",
    )))

    assert asyncio.run(collect_un_careers(client)) == []


def test_skips_items_without_title_or_url():
    client = FakeClient(rss(
        rss_item("", "https://careers.un.org/jobSearchDescription/123459",
                 "Information technology support."),
        rss_item("Software Developer", "", "Software development."),
    ))

    assert asyncio.run(collect_un_careers(client)) == []


def test_rejects_doctype():
    client = FakeClient(
        b'<!DOCTYPE rss [<!ENTITY x "test">]><rss><channel/></rss>'
    )

    try:
        asyncio.run(collect_un_careers(client))
    except ValueError as exc:
        assert "DOCTYPE/ENTITY" in str(exc)
    else:
        raise AssertionError("Le flux avec DOCTYPE aurait dû être refusé.")


def test_rejects_oversized_feed():
    client = FakeClient(b" " * (5 * 1024 * 1024 + 1))

    try:
        asyncio.run(collect_un_careers(client))
    except ValueError as exc:
        assert "5 Mo" in str(exc)
    else:
        raise AssertionError("Le flux trop volumineux aurait dû être refusé.")


def test_un_careers_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}

    assert sources["ONU Careers RSS"]["enabled"] is True
    assert sources["ONU Careers RSS"]["configuration_required"] is False
