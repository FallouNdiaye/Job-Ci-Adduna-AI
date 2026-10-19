import asyncio
from datetime import date, timedelta

from app.main import (
    NRC_API_BASE,
    NRC_DETAIL_ENDPOINT,
    NRC_LIST_ENDPOINT,
    _nrc_date,
    collect_nrc,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.content = b"{}"

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, pages, details):
        self.pages = pages
        self.details = details
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params or {}))
        if url == NRC_LIST_ENDPOINT:
            finder = (params or {}).get("finder", "")
            offset = int(finder.split("offset=")[1].split(",")[0])
            if offset not in self.pages:
                raise AssertionError(f"Offset NRC inattendu : {offset}")
            return FakeResponse(self.pages[offset])
        if url == NRC_DETAIL_ENDPOINT:
            finder = (params or {}).get("finder", "")
            identifier = finder.split("Id=")[1].split(",")[0]
            if identifier not in self.details:
                raise AssertionError(f"Fiche NRC inattendue : {identifier}")
            return FakeResponse(self.details[identifier])
        raise AssertionError(f"URL NRC inattendue : {url}")


def listing(rows, total=None):
    return {
        "items": [{
            "TotalJobsCount": len(rows) if total is None else total,
            "requisitionList": rows,
        }]
    }


def detail(description, deadline=None):
    row = {
        "ExternalDescriptionStr": description,
        "ExternalResponsibilitiesStr": "<p>Concevoir et maintenir les outils.</p>",
        "ExternalQualificationsStr": "<p>Expérience professionnelle requise.</p>",
    }
    if deadline:
        row["ExternalPostedEndDate"] = deadline
    return {"items": [row]}


def test_nrc_parses_iso_deadlines():
    assert _nrc_date("2026-10-26T00:00:00+00:00") == date(2026, 10, 26)
    assert _nrc_date("date inconnue") is None


def test_nrc_collects_relevant_job_and_preserves_full_description():
    rows = [
        {
            "Id": 98765,
            "Title": "Software Developer",
            "PostedDate": "2026-10-12",
            "PostingEndDate": "2099-10-26T00:00:00+00:00",
            "PrimaryLocationCountry": "Kenya",
            "PrimaryLocation": "Nairobi, Kenya",
        },
        {
            "Id": 12345,
            "Title": "Finance Assistant",
            "PrimaryLocationCountry": "Kenya",
        },
    ]
    client = FakeClient(
        pages={0: listing(rows, total=2)},
        details={
            "98765": detail(
                "<p>Java, APIs et développement logiciel.</p>",
                "2099-10-26T00:00:00+00:00",
            )
        },
    )

    jobs = asyncio.run(collect_nrc(client))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Software Developer"
    assert job["company"] == "Norwegian Refugee Council (NRC)"
    assert job["source"] == "NRC Careers"
    assert job["external_id"] == "98765"
    assert job["country"] == "Kenya"
    assert "Java, APIs" in job["description"]
    assert "Expérience professionnelle requise" in job["description"]
    assert "Date limite publiée par NRC : 2099-10-26" in job["description"]
    assert job["contract_type"] == "Non précisé"
    assert job["work_mode"] == "Non précisé"
    assert job["url"].startswith(NRC_API_BASE + "/hcmUI/CandidateExperience/")
    assert len(client.calls) == 2


def test_nrc_maps_workplace_type_without_mislabeling_contract():
    rows = [
        {
            "Id": 98765,
            "Title": "Software Developer",
            "PrimaryLocationCountry": "Kenya",
            "PrimaryLocation": "Nairobi, Kenya",
            "WorkplaceType": "Hybrid",
            "WorkplaceTypeCode": "ORA_HYBRID",
        }
    ]
    client = FakeClient(
        pages={0: listing(rows)},
        details={"98765": detail("Software development and APIs.")},
    )

    jobs = asyncio.run(collect_nrc(client))

    assert len(jobs) == 1
    assert jobs[0]["work_mode"] == "Hybride"
    assert jobs[0]["contract_type"] == "Non précisé"


def test_nrc_excludes_expired_relevant_job():
    expired = (date.today() - timedelta(days=2)).isoformat()
    rows = [{
        "Id": 98765,
        "Title": "Database Officer",
        "PostingEndDate": expired,
        "PrimaryLocationCountry": "Ukraine",
    }]
    client = FakeClient(
        pages={0: listing(rows)},
        details={"98765": detail("Database and reporting duties.", expired)},
    )
    assert asyncio.run(collect_nrc(client)) == []


def test_nrc_paginates_until_total_count():
    first = [{
        "Id": index,
        "Title": "Software Engineer",
        "PrimaryLocationCountry": "Kenya",
    } for index in range(1, 26)]
    second = [{
        "Id": 26,
        "Title": "Database Officer",
        "PrimaryLocationCountry": "Kenya",
    }]
    details = {
        str(index): detail("Software development and APIs.")
        for index in range(1, 26)
    }
    details["26"] = detail("Database administration and reporting.")
    client = FakeClient(
        pages={0: listing(first, total=26), 25: listing(second, total=26)},
        details=details,
    )

    jobs = asyncio.run(collect_nrc(client))

    assert len(jobs) == 26
    offsets = [
        int(params["finder"].split("offset=")[1].split(",")[0])
        for url, params in client.calls if url == NRC_LIST_ENDPOINT
    ]
    assert offsets == [0, 25]


def test_nrc_rejects_unrecognized_listing_shape():
    client = FakeClient(
        pages={0: {"items": [{"unexpected": []}]}},
        details={},
    )
    assert asyncio.run(collect_nrc(client)) == []
