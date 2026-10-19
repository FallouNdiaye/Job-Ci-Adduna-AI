import asyncio

from app.main import collect_arbeitnow, source_catalog


API_URL = "https://www.arbeitnow.com/api/job-board-api"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        return FakeResponse(self.payload)


def test_collects_and_normalizes_valid_jobs():
    client = FakeClient({
        "data": [{
            "id": "job-123",
            "title": "Senior Full Stack Developer",
            "company_name": "Example Tech",
            "url": "https://example.com/jobs/123",
            "location": "Berlin",
            "description": "Develop applications with Java and Spring Boot.",
            "tags": ["Java", "Spring Boot"],
            "remote": True,
            "job_type": "Full-time",
            "created_at": "2026-10-17",
        }]
    })

    jobs = asyncio.run(collect_arbeitnow(client))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Senior Full Stack Developer"
    assert job["company"] == "Example Tech"
    assert job["url"] == "https://example.com/jobs/123"
    assert job["source"] == "Arbeitnow API"
    assert job["external_id"] == "job-123"
    assert job["location"] == "Berlin"
    assert job["work_mode"] == "Télétravail"
    assert job["contract_type"] == "Full-time"
    assert job["content_hash"]
    assert client.calls[0][0] == API_URL


def test_skips_jobs_missing_required_fields():
    client = FakeClient({
        "data": [
            {
                "title": "Developer",
                "company_name": "Example Tech",
                "url": "https://example.com/jobs/1",
            },
            {
                "title": "Developer",
                "company_name": "Example Tech",
            },
            {
                "company_name": "Example Tech",
                "url": "https://example.com/jobs/3",
            },
        ]
    })

    jobs = asyncio.run(collect_arbeitnow(client))

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Developer"


def test_handles_empty_or_unexpected_api_payload():
    for payload in ({}, [], None, {"data": None}, {"data": "invalid"}):
        client = FakeClient(payload)
        jobs = asyncio.run(collect_arbeitnow(client))
        assert jobs == []


def test_keeps_multiple_valid_jobs():
    client = FakeClient({
        "data": [
            {
                "id": "1",
                "title": "Java Developer",
                "company_name": "Company A",
                "url": "https://example.com/jobs/1",
            },
            {
                "id": "2",
                "title": "Mobile Developer",
                "company_name": "Company B",
                "url": "https://example.com/jobs/2",
            },
        ]
    })

    jobs = asyncio.run(collect_arbeitnow(client))

    assert len(jobs) == 2
    assert {job["external_id"] for job in jobs} == {"1", "2"}


def test_arbeitnow_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}

    assert sources["Arbeitnow API"]["enabled"] is True
    assert sources["Arbeitnow API"]["configuration_required"] is False
