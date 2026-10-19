import asyncio

from app.main import collect_jobicy, source_catalog


API_URL = "https://jobicy.com/api/v2/remote-jobs"


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


def test_collects_and_maps_jobicy_fields():
    client = FakeClient({
        "jobs": [{
            "id": 101,
            "jobTitle": "Senior Java Developer",
            "companyName": "Example Tech",
            "jobUrl": "https://example.com/jobs/101",
            "jobGeo": "Worldwide",
            "jobDescription": "Build Java and Spring Boot applications.",
            "pubDate": "2026-10-17",
            "jobType": "Full-time",
        }]
    })

    jobs = asyncio.run(collect_jobicy(client))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Senior Java Developer"
    assert job["company"] == "Example Tech"
    assert job["url"] == "https://example.com/jobs/101"
    assert job["location"] == "Worldwide"
    assert job["source"] == "Jobicy API"
    assert job["published_at"] == "2026-10-17"
    assert job["contract_type"] == "Full-time"
    assert job["content_hash"]
    assert client.calls[0][0] == API_URL
    assert client.calls[0][1] == {
        "count": 100,
        "industry": "engineering",
    }


def test_accepts_alternative_field_names():
    client = FakeClient({
        "jobs": [{
            "title": "Frontend Developer",
            "company": "Company B",
            "url": "https://example.com/jobs/frontend",
            "location": "Remote",
            "description": "React and JavaScript development.",
        }]
    })

    jobs = asyncio.run(collect_jobicy(client))

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Frontend Developer"
    assert jobs[0]["company"] == "Company B"
    assert jobs[0]["location"] == "Remote"


def test_skips_jobs_missing_required_fields():
    client = FakeClient({
        "jobs": [
            {
                "jobTitle": "Developer",
                "companyName": "Company A",
                "jobUrl": "https://example.com/jobs/1",
            },
            {
                "jobTitle": "Incomplete listing",
                "companyName": "Company B",
            },
        ]
    })

    jobs = asyncio.run(collect_jobicy(client))

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Developer"


def test_handles_empty_or_unexpected_top_level_payloads():
    for payload in ({}, [], None, {"jobs": []}):
        client = FakeClient(payload)
        assert asyncio.run(collect_jobicy(client)) == []


def test_jobicy_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}

    assert sources["Jobicy API"]["enabled"] is True
    assert sources["Jobicy API"]["configuration_required"] is False
