import asyncio
import json

from app.main import collect_smartrecruiters, source_catalog


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeClient:
    def __init__(self, listings, details=None, failures=None):
        self.listings = listings
        self.details = details or {}
        self.failures = failures or set()
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params or {}))
        assert headers and "User-Agent" in headers

        if any(token in url for token in self.failures):
            raise RuntimeError("Erreur simulée")

        if "/postings/" in url:
            posting_id = url.rsplit("/", 1)[-1]
            if posting_id not in self.details:
                raise AssertionError(f"Détail inattendu : {posting_id}")
            return FakeResponse(self.details[posting_id])

        offset = (params or {}).get("offset", 0)
        company = url.split("/companies/", 1)[-1].split("/", 1)[0]
        pages = self.listings.get(company, {})
        return FakeResponse(pages.get(offset, {
            "content": [],
            "totalFound": 0,
        }))


def posting(job_id, title, company="ALTEN"):
    return {
        "id": job_id,
        "name": title,
        "postingUrl": f"https://jobs.smartrecruiters.com/{company}/{job_id}",
        "location": {
            "city": "Paris",
            "country": "France",
        },
    }


def detail(job_id, company="ALTEN"):
    return {
        "id": job_id,
        "company": {"name": company},
        "postingUrl": f"https://jobs.smartrecruiters.com/{company}/{job_id}",
        "releasedDate": "2026-10-09T00:00:00.000Z",
        "typeOfEmployment": {"label": "Permanent"},
        "location": {"city": "Paris", "country": "France"},
        "jobAd": {
            "sections": {
                "jobDescription": {
                    "text": "<p>Java, Spring Boot, PostgreSQL</p>"
                }
            }
        },
    }


def test_smartrecruiters_filters_non_it_and_normalizes_jobs(monkeypatch):
    monkeypatch.setenv("SMARTRECRUITERS_COMPANIES", "ALTEN")
    monkeypatch.setenv("SMARTRECRUITERS_MAX_PAGES", "2")

    client = FakeClient(
        listings={
            "ALTEN": {
                0: {
                    "totalFound": 2,
                    "content": [
                        posting("it-1", "Software Engineer"),
                        posting("admin-1", "Finance Administrative Assistant"),
                    ],
                }
            }
        },
        details={"it-1": detail("it-1")},
    )

    jobs = asyncio.run(collect_smartrecruiters(client))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Software Engineer"
    assert job["company"] == "ALTEN"
    assert job["source"] == "SmartRecruiters · ALTEN"
    assert job["external_id"] == "it-1"
    assert job["url"] == "https://jobs.smartrecruiters.com/ALTEN/it-1"
    assert "Java" in job["description"]
    assert job["published_at"] is not None


def test_smartrecruiters_paginates_and_deduplicates(monkeypatch):
    monkeypatch.setenv("SMARTRECRUITERS_COMPANIES", "ALTEN")
    monkeypatch.setenv("SMARTRECRUITERS_MAX_PAGES", "3")

    first_page = [
        posting(f"other-{i}", "Administrative Assistant")
        for i in range(99)
    ]
    first_page.append(posting("java-1", "Java Developer"))

    client = FakeClient(
        listings={
            "ALTEN": {
                0: {"totalFound": 101, "content": first_page},
                100: {
                    "totalFound": 101,
                    "content": [
                        posting("java-1", "Java Developer"),
                        posting("java-2", "Full Stack Developer"),
                    ],
                },
            }
        },
        details={
            "java-1": detail("java-1"),
            "java-2": detail("java-2"),
        },
    )

    jobs = asyncio.run(collect_smartrecruiters(client))

    assert {job["external_id"] for job in jobs} == {"java-1", "java-2"}
    offsets = [
        params.get("offset")
        for url, params in client.calls
        if url.endswith("/postings")
    ]
    assert offsets == [0, 100]


def test_smartrecruiters_isolates_company_errors(monkeypatch):
    monkeypatch.setenv("SMARTRECRUITERS_COMPANIES", "BROKEN,ALTEN")
    monkeypatch.setenv("SMARTRECRUITERS_MAX_PAGES", "1")

    client = FakeClient(
        listings={
            "ALTEN": {
                0: {
                    "totalFound": 1,
                    "content": [posting("ok-1", "Software Engineer")],
                }
            }
        },
        details={"ok-1": detail("ok-1")},
        failures={"/BROKEN/postings"},
    )

    jobs = asyncio.run(collect_smartrecruiters(client))

    assert len(jobs) == 1
    assert jobs[0]["external_id"] == "ok-1"


def test_smartrecruiters_is_listed_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["SmartRecruiters"]["enabled"] is True
    assert sources["SmartRecruiters"]["configuration_required"] is False
    assert "non exhaustif" in sources["SmartRecruiters"]["note"].lower()
