import asyncio

import pytest
from app import main


API_URL = "https://remote-jobs.example.test/api/jobs"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload=None):
        self.payload = payload
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        return FakeResponse(self.payload)


def test_returns_empty_without_configured_url(monkeypatch):
    monkeypatch.setattr(main, "REMOTE_JOBS_API_URL", "")
    client = FakeClient({"jobs": [{"title": "Should not be fetched"}]})

    assert asyncio.run(main.collect_remote_jobs_api(client)) == []
    assert client.calls == []


def test_maps_jobs_payload(monkeypatch):
    monkeypatch.setattr(main, "REMOTE_JOBS_API_URL", API_URL)
    client = FakeClient({
        "jobs": [{
            "title": "Java Developer",
            "companyName": "Example Tech",
            "applyUrl": "https://example.com/jobs/java",
            "remoteRegion": "Worldwide",
            "descriptionText": "Java and Spring Boot development.",
            "publishedAt": "2026-10-17",
        }]
    })

    jobs = asyncio.run(main.collect_remote_jobs_api(client))

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Java Developer"
    assert jobs[0]["company"] == "Example Tech"
    assert jobs[0]["url"] == "https://example.com/jobs/java"
    assert jobs[0]["location"] == "Worldwide"
    assert jobs[0]["source"] == "Remote Jobs API (agrégateur configuré)"
    assert jobs[0]["published_at"] == "2026-10-17"
    assert client.calls[0][0] == API_URL


@pytest.mark.parametrize("payload", [
    {"data": [{
        "title": "React Developer",
        "company": "Company B",
        "job_url": "https://example.com/react",
    }]},
    [{
        "title": "Backend Developer",
        "company": "Company C",
        "url": "https://example.com/backend",
    }],
])
def test_accepts_alternative_payload_shapes(monkeypatch, payload):
    monkeypatch.setattr(main, "REMOTE_JOBS_API_URL", API_URL)

    jobs = asyncio.run(main.collect_remote_jobs_api(FakeClient(payload)))

    assert len(jobs) == 1
    assert jobs[0]["title"] in {"React Developer", "Backend Developer"}


@pytest.mark.parametrize("payload", [
    {},
    {"jobs": []},
    {"data": []},
    None,
    [],
])
def test_handles_empty_or_unexpected_payloads(monkeypatch, payload):
    monkeypatch.setattr(main, "REMOTE_JOBS_API_URL", API_URL)

    assert asyncio.run(
        main.collect_remote_jobs_api(FakeClient(payload))
    ) == []


def test_skips_non_dictionary_rows(monkeypatch):
    monkeypatch.setattr(main, "REMOTE_JOBS_API_URL", API_URL)
    client = FakeClient({
        "jobs": [
            None,
            "invalid row",
            {
                "title": "Valid Developer",
                "company": "Example",
                "url": "https://example.com/valid",
            },
        ]
    })

    jobs = asyncio.run(main.collect_remote_jobs_api(client))

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Valid Developer"


def test_source_catalog_marks_connector_as_configurable():
    sources = {
        item["name"]: item
        for item in main.source_catalog()["sources"]
    }

    source = sources["Remote Jobs API"]
    assert source["configuration_required"] is True
    assert source["enabled"] is bool(main.REMOTE_JOBS_API_URL)
