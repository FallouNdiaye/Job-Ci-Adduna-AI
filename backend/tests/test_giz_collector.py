import asyncio
import json
from datetime import date, timedelta

from app.main import (
    GIZ_API_URL,
    GIZ_CONFIG_URL,
    collect_giz,
    source_catalog,
)


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.content = b"{}"

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeClient:
    def __init__(self, items):
        self.items = items
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        if url == GIZ_CONFIG_URL:
            return FakeResponse({
                "configWidgetContainer": {
                    "search": {
                        "parameter": {
                            "matchedObjectDescriptor": {
                                "search": {"PositionTitle": {"enabled": True}}
                            }
                        }
                    }
                }
            })
        if url == GIZ_API_URL:
            payload = json.loads(params["data"])
            assert payload["LanguageCode"] == "EN"
            assert payload["SearchParameters"]["CountItem"] == 50
            assert payload["SearchParameters"]["FirstItem"] == 1
            return FakeResponse({
                "SearchResult": {"SearchResultItems": self.items}
            })
        raise AssertionError(f"URL inattendue : {url}")


def make_item(title, identifier="GIZ-123", end_date=None, url=None,
              location=None):
    return {
        "MatchedObjectId": identifier,
        "MatchedObjectDescriptor": {
            "ID": identifier,
            "PositionTitle": title,
            "PositionURI": url or (
                f"https://jobs.giz.de/index.php?ac=jobad&id={identifier}"
            ),
            "PublicationStartDate": "2026-10-15",
            "PublicationEndDate": end_date or (
                date.today() + timedelta(days=10)
            ).isoformat(),
            "PositionLocation": location or [{
                "CityName": "Bonn",
                "CountryName": "Germany",
            }],
            "JobCategory": "Information Technology",
            "CareerLevel": "Experienced",
        },
    }


def test_giz_keeps_open_it_job_with_official_url():
    client = FakeClient([
        make_item("Software Developer (m/f/d)"),
        make_item("Communications Officer", identifier="GIZ-124"),
    ])
    jobs = asyncio.run(collect_giz(client))
    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "GIZ Careers"
    assert job["company"].startswith("Deutsche Gesellschaft")
    assert job["external_id"] == "GIZ-123"
    assert job["url"].startswith("https://jobs.giz.de/")
    assert job["country"] == "Germany"
    assert "visa" in job["description"].lower()
    assert len(client.calls) == 2


def test_giz_excludes_expired_it_job():
    client = FakeClient([
        make_item(
            "Software Engineer",
            end_date=(date.today() - timedelta(days=1)).isoformat(),
        )
    ])
    assert asyncio.run(collect_giz(client)) == []


def test_giz_excludes_internships_and_non_it_roles():
    client = FakeClient([
        make_item("Intern (m/f/d) Software Development", "GIZ-201"),
        make_item("Partnerships Officer", "GIZ-202"),
    ])
    assert asyncio.run(collect_giz(client)) == []


def test_giz_rejects_non_official_job_urls():
    client = FakeClient([
        make_item(
            "Software Developer",
            url="https://example.com/fake-job",
        )
    ])
    assert asyncio.run(collect_giz(client)) == []


def test_giz_handles_location_as_dictionary():
    client = FakeClient([
        make_item(
            "IT Systems Engineer",
            location={"CityName": "New Delhi", "CountryName": "India"},
        )
    ])
    jobs = asyncio.run(collect_giz(client))
    assert len(jobs) == 1
    assert "New Delhi" in jobs[0]["location"]
    assert jobs[0]["country"] == "India"


def test_giz_deduplicates_identical_ids():
    client = FakeClient([
        make_item("Software Developer", "GIZ-DUP"),
        make_item("Software Developer", "GIZ-DUP"),
    ])
    jobs = asyncio.run(collect_giz(client))
    assert len(jobs) == 1


def test_giz_is_enabled_in_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["GIZ Careers"]["enabled"] is True
    assert sources["GIZ Careers"]["configuration_required"] is False
