import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.main import IOM_JOBS_API_URL, collect_iom, source_catalog


class FakeResponse:
    def __init__(self, payload):
        self.content = json.dumps(payload).encode()
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.response = FakeResponse(payload)
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        return self.response


def make_job(job_id, title, deadline, **extra):
    return {
        "Id": job_id,
        "Title": title,
        "PostedDate": datetime.now(timezone.utc).date().isoformat(),
        "PostingEndDate": deadline,
        "PrimaryLocation": "Geneva, Switzerland",
        "ShortDescriptionStr": "",
        **extra,
    }


def test_iom_keeps_open_it_jobs_and_preserves_metadata():
    deadline = (datetime.now(timezone.utc).date() + timedelta(days=5)).isoformat()
    payload = {"items": [{"requisitionList": [
        make_job(101, "Software Developer", deadline,
                 ExternalResponsibilitiesStr="Build web applications"),
        make_job(102, "Supply Chain Associate", deadline,
                 ExternalResponsibilitiesStr="Procurement and logistics"),
        make_job(103, "IT Support Officer", "2000-01-01"),
    ]}]}
    client = FakeClient(payload)

    jobs = asyncio.run(collect_iom(client))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Software Developer"
    assert job["source"] == "IOM Careers"
    assert job["external_id"] == "101"
    assert job["url"].endswith("/job/101")
    assert deadline in job["description"]
    assert "Geneva, Switzerland" in job["description"]
    assert client.calls[0][0] == IOM_JOBS_API_URL
    assert client.calls[0][1]["finder"].startswith("findReqs;siteNumber=CX_1001")


def test_iom_keeps_it_terms_found_in_responsibilities():
    deadline = (datetime.now(timezone.utc).date() + timedelta(days=5)).isoformat()
    payload = {"items": [{"requisitionList": [
        make_job(201, "Associate", deadline,
                 ExternalResponsibilitiesStr="Maintain database applications"),
    ]}]}

    jobs = asyncio.run(collect_iom(FakeClient(payload)))

    assert len(jobs) == 1
    assert jobs[0]["external_id"] == "201"


def test_iom_is_enabled_in_source_catalog():
    sources = source_catalog()["sources"]
    source = next(item for item in sources if item["name"] == "IOM Careers")
    assert source["enabled"] is True
    assert source["configuration_required"] is False
