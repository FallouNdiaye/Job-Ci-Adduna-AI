import asyncio
from datetime import date, timedelta

from app.main import AFRICAN_UNION_API_URL, collect_african_union, source_catalog


class FakeResponse:
    def __init__(self, payload=None, content=""):
        self.payload = payload
        self.content = content.encode() if isinstance(content, str) else content

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


class FakeClient:
    def __init__(self, rows, details):
        self.rows = rows
        self.details = details

    async def post(self, url, json=None, headers=None):
        assert url == AFRICAN_UNION_API_URL
        return FakeResponse({"items": self.rows})

    async def get(self, url, headers=None):
        for key, value in self.details.items():
            if key in url:
                return FakeResponse(content=value)
        raise AssertionError(f"URL inattendue : {url}")


def row(title, job_id="3115", deadline=None, slug="ict-officer"):
    return {
        "id": job_id,
        "unifiedStandardTitle": title,
        "unifiedUrlTitle": slug,
        "mfield1": "Ethiopia",
        "jobGrade": "P2",
        "cus_postingdate": "2026-10-01",
        "cus_enddate": deadline or (date.today() + timedelta(days=10)).isoformat(),
    }


def test_keeps_open_it_job_and_metadata():
    item = row("ICT Officer")
    url = f"https://jobs.au.int/job/{item['unifiedUrlTitle']}/{item['id']}-en_US"
    client = FakeClient(
        [item],
        {url: "<h1>ICT Officer</h1><div class='job'>Maintain information systems.</div>"},
    )
    jobs = asyncio.run(collect_african_union(client))
    assert len(jobs) == 1
    assert jobs[0]["source"] == "African Union Careers"
    assert jobs[0]["external_id"] == "3115"
    assert jobs[0]["url"] == url
    assert jobs[0]["location"] == "Ethiopia"
    assert "Date limite" in jobs[0]["description"]
    assert "Grade : P2" in jobs[0]["description"]


def test_excludes_expired_and_unrelated_roles():
    expired = row(
        "ICT Officer", "expired",
        (date.today() - timedelta(days=1)).isoformat(), "expired",
    )
    finance = row("Finance Director", "finance", slug="finance")
    url = "https://jobs.au.int/job/finance/finance-en_US"
    client = FakeClient(
        [expired, finance],
        {url: "<h1>Finance Director</h1><div class='job'>Uses IT software.</div>"},
    )
    assert asyncio.run(collect_african_union(client)) == []


def test_source_is_enabled_in_catalog():
    sources = {x["name"]: x for x in source_catalog()["sources"]}
    assert sources["African Union Careers"]["enabled"] is True
    assert sources["African Union Careers"]["configuration_required"] is False
