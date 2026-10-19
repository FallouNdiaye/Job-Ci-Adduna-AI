import asyncio

from app.main import ILO_RSS_URL, collect_ilo, source_catalog


class FakeResponse:
    def __init__(self, content):
        self.content = content.encode("utf-8")

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.requested_url = None

    async def get(self, url, headers=None):
        self.requested_url = url
        assert headers and "User-Agent" in headers
        return FakeResponse(self.content)


def test_ilo_filters_it_jobs_and_preserves_official_urls():
    feed = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>Software Developer (Geneva, CH)</title>
        <link>https://jobs.ilo.org/job/Geneva-Software-Developer/123/?utm_source=rss</link>
        <guid>https://jobs.ilo.org/job/Geneva-Software-Developer/123/?feedId=null</guid>
        <pubDate>Thu, 15 Oct 2026 00:00:00 GMT</pubDate>
        <description><![CDATA[<p>Application deadline: 29 October 2026</p>
          <p>Location: Geneva, Switzerland</p>]]></description>
      </item>
      <item>
        <title>Finance and Administrative Assistant (Abuja, NG)</title>
        <link>https://jobs.ilo.org/job/Abuja-Finance-Assistant/456/</link>
        <description>Finance duties.</description>
      </item>
      <item>
        <title>Software Developer (Geneva, CH)</title>
        <link>https://jobs.ilo.org/job/Geneva-Software-Developer/123/?utm_campaign=other</link>
        <description>Duplicate listing.</description>
      </item>
      <item>
        <title>Software Engineer</title>
        <link>https://example.org/job/999</link>
        <description>Not an official ILO URL.</description>
      </item>
    </channel></rss>"""

    client = FakeClient(feed)
    jobs = asyncio.run(collect_ilo(client))

    assert client.requested_url == ILO_RSS_URL
    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "ILO Careers"
    assert job["title"] == "Software Developer (Geneva, CH)"
    assert job["url"] == "https://jobs.ilo.org/job/Geneva-Software-Developer/123/"
    assert job["external_id"] == job["url"]
    assert job["published_at"] is not None
    assert "29 October 2026" in job["description"]
    assert "Fiche officielle :" in job["description"]


def test_ilo_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["ILO Careers"]["enabled"] is True
    assert sources["ILO Careers"]["configuration_required"] is False


def test_ilo_rejects_doctype():
    client = FakeClient(
        '<!DOCTYPE rss [<!ENTITY x "bad">]><rss><channel></channel></rss>'
    )
    try:
        asyncio.run(collect_ilo(client))
    except ValueError as exc:
        assert "DOCTYPE/ENTITY" in str(exc)
    else:
        raise AssertionError("Le flux contenant un DOCTYPE aurait dû être rejeté.")
