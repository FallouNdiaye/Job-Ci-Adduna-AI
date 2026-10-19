import asyncio

from app.main import _hi_is_relevant, collect_hi, source_catalog


API_URL = "https://apply.workable.com/api/v1/widget/accounts/hi-jobs?details=true"


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

    async def get(self, url, headers=None):
        self.calls.append((url, headers))
        assert url == API_URL
        return FakeResponse(self.payload)


def valid_job(**overrides):
    item = {
        "title": "Senior Software Engineer",
        "shortcode": "ABC123",
        "code": "HI-IT-123",
        "url": "https://apply.workable.com/hi-jobs/j/ABC123/",
        "application_url": "https://apply.workable.com/j/ABC123/apply",
        "city": "Lyon",
        "country": "France",
        "published_on": "2026-10-16",
        "employment_type": "Full-time",
        "description": "<p>Build and maintain software.</p>",
    }
    item.update(overrides)
    return item


def test_hi_collects_relevant_job_and_official_links():
    client = FakeClient({"jobs": [valid_job()]})
    jobs = asyncio.run(collect_hi(client))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "Handicap International (HI)"
    assert job["company"] == "Handicap International (HI)"
    assert job["external_id"] == "ABC123"
    assert job["url"] == "https://apply.workable.com/hi-jobs/j/ABC123/"
    assert "apply.workable.com/j/ABC123/apply" in job["description"]
    assert job["published_at"] == "2026-10-16"
    assert len(client.calls) == 1


def test_hi_rejects_generic_admin_roles_even_with_technical_description():
    irrelevant = valid_job(
        title="Project Administrator",
        description="ICT, software, databases and technology are mentioned here.",
        function="Administration",
        department="Projects",
    )
    assert asyncio.run(collect_hi(FakeClient({"jobs": [irrelevant]}))) == []


def test_hi_accepts_it_title_or_explicit_it_function():
    assert _hi_is_relevant("Full Stack Developer")
    assert _hi_is_relevant("Information Systems Officer")
    assert _hi_is_relevant("Senior Analyst", "Information Technology")
    assert not _hi_is_relevant("Finance Assistant", "Finance", "Administration")


def test_hi_rejects_untrusted_job_and_application_urls():
    item = valid_job(
        url="https://evil.example/hi-jobs/j/ABC123/",
        application_url="https://evil.example/j/ABC123/apply",
    )
    jobs = asyncio.run(collect_hi(FakeClient({"jobs": [item]})))
    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://apply.workable.com/hi-jobs/j/ABC123/"
    assert "evil.example" not in jobs[0]["description"]


def test_hi_handles_api_failure_without_crashing():
    class BrokenClient:
        async def get(self, url, headers=None):
            raise RuntimeError("simulated failure")

    assert asyncio.run(collect_hi(BrokenClient())) == []


def test_hi_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["Handicap International (HI)"]["enabled"] is True
    assert sources["Handicap International (HI)"]["configuration_required"] is False
