import asyncio
from urllib.parse import parse_qs, urlparse

from app.main import UNESCO_RSS_URL, collect_unesco, source_catalog


class FakeResponse:
    def __init__(self, content):
        self.content = content.encode()

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, feed):
        self.feed = feed
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        assert url.startswith(UNESCO_RSS_URL + "?")
        assert headers and "User-Agent" in headers
        return FakeResponse(self.feed)


def test_unesco_filters_titles_and_deduplicates_across_keywords():
    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>Team Leader (IT Infrastructure)</title>
        <link>https://careers.unesco.org/viewjob/123</link>
        <guid>123</guid>
        <pubDate>Fri, 16 Oct 2026 10:00:00 GMT</pubDate>
        <description><![CDATA[Location: Trieste, Italy. Manage IT infrastructure.]]></description>
      </item>
      <item>
        <title>INTERNSHIP: Digital Business Solutions</title>
        <link>https://careers.unesco.org/viewjob/456</link>
        <guid>456</guid>
        <description><![CDATA[Location: Paris, France. Support digital business solutions.]]></description>
      </item>
      <item>
        <title>Digital Education Officer</title>
        <link>https://careers.unesco.org/viewjob/789</link>
        <guid>789</guid>
        <description><![CDATA[Education policy and digital learning.]]></description>
      </item>
      <item>
        <title>Software Developer</title>
        <link>https://example.org/fake-job</link>
        <guid>999</guid>
        <description><![CDATA[Software development.]]></description>
      </item>
    </channel></rss>"""

    client = FakeClient(feed)
    jobs = asyncio.run(collect_unesco(client))

    assert len(client.calls) >= 8
    assert len(jobs) == 2
    by_title = {job["title"]: job for job in jobs}
    assert "Team Leader (IT Infrastructure)" in by_title
    assert "INTERNSHIP: Digital Business Solutions" in by_title
    assert "Digital Education Officer" not in by_title
    job = by_title["Team Leader (IT Infrastructure)"]
    assert job["source"] == "UNESCO Careers"
    assert job["external_id"] == "123"
    assert job["url"] == "https://careers.unesco.org/viewjob/123"
    assert "Trieste, Italy" in job["location"]
    assert "Source officielle : UNESCO Careers" in job["description"]


def test_unesco_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["UNESCO Careers"]["enabled"] is True
    assert sources["UNESCO Careers"]["configuration_required"] is False
