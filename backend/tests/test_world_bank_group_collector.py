import asyncio
import json
import re
from datetime import datetime, timezone

from app.main import (
    WORLD_BANK_GROUP_HOME,
    WORLD_BANK_GROUP_API,
    collect_world_bank_group,
    source_catalog,
)


class FakeResponse:
    def __init__(self, body=None, text="", content=b""):
        self._body = body
        self.text = text
        self.content = content or text.encode()

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, jobs):
        self.jobs = jobs
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(("GET", url))
        return FakeResponse(text='{"token":"test-token"}')

    async def post(self, url, json=None, headers=None):
        self.calls.append(("POST", url, json, headers))
        assert headers["Authorization"] == "Bearer test-token"
        return FakeResponse(
            body={
                "status": "success",
                "data": {"totalCount": len(self.jobs), "requisitions": self.jobs},
            }
        )


def _job(
    identifier,
    title,
    expiration="10/31/2026",
    location="Washington, DC",
    description="Technical software development role.",
):
    return {
        "requisitionId": str(identifier),
        "displayJobTitle": title,
        "postingEffectiveDate": "10/16/2026",
        "postingExpirationDate": expiration,
        "locations": [{"city": location, "country": "US"}],
        "externalDescription": f"<p>{description}</p>",
    }


def test_world_bank_group_collects_relevant_open_jobs_and_deduplicates():
    client = FakeClient([
        _job(38675, "Associate Senior Solutions Architect"),
        _job(38676, "Software Engineer"),
        _job(38677, "Finance Officer", description="Finance and budget administration role."),
        _job(38678, "Mobile Developer", expiration="01/01/2020"),
    ])

    jobs = asyncio.run(collect_world_bank_group(client))

    assert client.calls[0] == ("GET", WORLD_BANK_GROUP_HOME)
    assert all(call[1] == WORLD_BANK_GROUP_API for call in client.calls[1:])
    assert len(jobs) == 2
    assert {job["external_id"] for job in jobs} == {"38675", "38676"}
    for job in jobs:
        assert job["source"] == "World Bank Group Careers"
        assert job["url"].startswith(
            "https://worldbankgroup.csod.com/ux/ats/careersite/1/requisition/"
        )
        assert "visa" in job["description"].lower()
        assert job["company"] == "World Bank Group"


def test_world_bank_group_catalogue_entry_is_enabled():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["World Bank Group Careers"]["enabled"] is True
    assert sources["World Bank Group Careers"]["configuration_required"] is False


def test_world_bank_group_never_logs_or_returns_session_token():
    client = FakeClient([_job(38676, "Software Engineer")])
    jobs = asyncio.run(collect_world_bank_group(client))
    assert all("test-token" not in json.dumps(job) for job in jobs)


def test_world_bank_group_title_filter_covers_modern_development_roles():
    from app.main import WORLD_BANK_GROUP_TITLE_TERMS

    titles = [
        "Full Stack Developer",
        "Backend Engineer",
        "Back-end Software Engineer",
        "Frontend Engineer",
        "Front-end Developer",
        "AI Engineer",
        "Platform Engineer",
        "Mobile Developer",
    ]
    for title in titles:
        assert WORLD_BANK_GROUP_TITLE_TERMS.search(title), title


def test_world_bank_group_search_terms_cover_modern_development_roles():
    from app.main import WORLD_BANK_GROUP_SEARCH_TERMS

    terms = {term.lower() for term in WORLD_BANK_GROUP_SEARCH_TERMS}
    assert "full stack developer" in terms
    assert "backend engineer" in terms
    assert "frontend engineer" in terms
    assert "ai engineer" in terms
    assert "platform engineer" in terms
