import asyncio

from app.main import collect_remotive, source_catalog


API_URL = "https://remotive.com/api/remote-jobs"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params))
        term = params["search"]
        result = self.responses[term]
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)


def job(job_id, title, company):
    return {
        "id": job_id,
        "title": title,
        "company_name": company,
        "url": f"https://example.com/jobs/{job_id}",
        "candidate_required_location": "Worldwide",
        "description": "Build and maintain software applications.",
    }


def test_collects_jobs_for_all_three_search_terms():
    client = FakeClient({
        "Java": {"jobs": [job("1", "Java Developer", "Company A")]},
        "Spring Boot": {"jobs": [job("2", "Backend Engineer", "Company B")]},
        "Angular": {"jobs": [job("3", "Angular Developer", "Company C")]},
    })

    jobs = asyncio.run(collect_remotive(client))

    assert len(jobs) == 3
    assert {item["external_id"] for item in jobs} == {"1", "2", "3"}
    assert all(item["source"] == "Remotive API" for item in jobs)
    assert [params["search"] for _, params in client.calls] == [
        "Java", "Spring Boot", "Angular"
    ]
    assert all(url == API_URL for url, _ in client.calls)
    assert all(params["limit"] == 50 for _, params in client.calls)


def test_continues_when_one_search_fails():
    client = FakeClient({
        "Java": RuntimeError("Erreur réseau simulée"),
        "Spring Boot": {"jobs": [job("2", "Spring Engineer", "Company B")]},
        "Angular": {"jobs": [job("3", "Angular Developer", "Company C")]},
    })

    jobs = asyncio.run(collect_remotive(client))

    assert len(jobs) == 2
    assert {item["external_id"] for item in jobs} == {"2", "3"}
    assert len(client.calls) == 3


def test_handles_empty_and_unexpected_payloads():
    client = FakeClient({
        "Java": {},
        "Spring Boot": [],
        "Angular": None,
    })

    assert asyncio.run(collect_remotive(client)) == []


def test_skips_jobs_missing_required_fields():
    client = FakeClient({
        "Java": {
            "jobs": [
                job("1", "Java Developer", "Company A"),
                {"title": "Incomplete job"},
            ]
        },
        "Spring Boot": {"jobs": []},
        "Angular": {"jobs": []},
    })

    jobs = asyncio.run(collect_remotive(client))

    assert len(jobs) == 1
    assert jobs[0]["external_id"] == "1"


def test_remotive_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}

    assert sources["Remotive API"]["enabled"] is True
    assert sources["Remotive API"]["configuration_required"] is False
