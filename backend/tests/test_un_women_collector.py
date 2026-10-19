import asyncio
from datetime import date, timedelta

from app.main import (
    UN_WOMEN_API_BASE,
    UN_WOMEN_DETAIL_ENDPOINT,
    UN_WOMEN_LIST_ENDPOINT,
    collect_un_women,
    source_catalog,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

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
        params = params or {}
        self.calls.append((url, params))
        if url == UN_WOMEN_LIST_ENDPOINT:
            finder = params.get("finder", "")
            offset = int(finder.split("offset=")[1].split(",")[0])
            if offset not in self.pages:
                raise AssertionError(f"Offset inattendu : {offset}")
            return FakeResponse(self.pages[offset])
        if url == UN_WOMEN_DETAIL_ENDPOINT:
            finder = params.get("finder", "")
            identifier = finder.split("Id=")[1].split(",")[0]
            if identifier not in self.details:
                raise AssertionError(f"Fiche inattendue : {identifier}")
            return FakeResponse(self.details[identifier])
        raise AssertionError(f"URL inattendue : {url}")


def listing(rows, has_more=False, count=None):
    return {
        "items": [{"requisitionList": rows}],
        "count": len(rows) if count is None else count,
        "hasMore": has_more,
    }


def detail(identifier, description, deadline=None):
    row = {
        "Id": str(identifier),
        "Title": description,
        "ExternalDescriptionStr": f"<p>{description}</p>",
        "ExternalResponsibilitiesStr": "<p>Software development and APIs.</p>",
        "ExternalQualificationsStr": "<p>Relevant professional experience.</p>",
    }
    if deadline:
        row["ExternalPostedEndDate"] = deadline
    return {"items": [row]}


def test_un_women_collects_it_job_and_uses_official_urls():
    rows = [{
        "Id": 36891,
        "Title": "ICT Associate, G6, FTA, Kyiv, Ukraine",
        "PostedDate": "2026-10-13",
        "PostingEndDate": "2099-10-26",
        "PrimaryLocationCountry": "Ukraine",
        "PrimaryLocation": "Kyiv, Ukraine",
    }]
    client = FakeClient(
        {0: listing(rows)},
        {"36891": detail("36891", "ICT support and systems administration.",
                         "2099-10-26")},
    )

    jobs = asyncio.run(collect_un_women(client))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "UN Women Careers"
    assert job["company"] == "UN Women (ONU Femmes)"
    assert job["external_id"] == "36891"
    assert job["country"] == "Ukraine"
    assert "ICT support" in job["description"]
    assert "éligibilité" in job["description"]
    assert job["url"] == (
        UN_WOMEN_API_BASE
        + "/hcmUI/CandidateExperience/en/sites/CX_1001/job/36891"
    )
    assert all(
        "siteNumber=CX_1001" in params.get("finder", "")
        for _, params in client.calls
    )


def test_un_women_excludes_expired_it_job():
    expired = (date.today() - timedelta(days=2)).isoformat()
    rows = [{
        "Id": 36891,
        "Title": "ICT Associate",
        "PostingEndDate": expired,
        "PrimaryLocationCountry": "Ukraine",
    }]
    client = FakeClient(
        {0: listing(rows)},
        {"36891": detail("36891", "ICT systems administration.", expired)},
    )
    assert asyncio.run(collect_un_women(client)) == []


def test_un_women_ignores_non_it_roles_without_fetching_details():
    rows = [{
        "Id": 37452,
        "Title": "National Gender Statistics Consultant",
        "PrimaryLocationCountry": "Haiti",
    }]
    client = FakeClient({0: listing(rows)}, {})
    assert asyncio.run(collect_un_women(client)) == []
    assert len(client.calls) == 1


def test_un_women_paginates_using_count():
    first = [{
        "Id": index,
        "Title": "Software Developer",
        "PrimaryLocationCountry": "Kenya",
    } for index in range(1, 26)]
    second = [{
        "Id": 26,
        "Title": "Database Officer",
        "PrimaryLocationCountry": "Kenya",
    }]
    details = {
        str(index): detail(index, "Software development and APIs.")
        for index in range(1, 27)
    }
    client = FakeClient(
        {
            # Simule l'API réelle : 25 offres imbriquées mais count=1
            # et hasMore=False à la racine.
            0: listing(first, has_more=False, count=1),
            25: listing(second, has_more=False, count=1),
        },
        details,
    )
    jobs = asyncio.run(collect_un_women(client))
    assert len(jobs) == 26
    offsets = [
        int(params["finder"].split("offset=")[1].split(",")[0])
        for url, params in client.calls if url == UN_WOMEN_LIST_ENDPOINT
    ]
    assert offsets == [0, 25]


def test_un_women_catalog_is_enabled():
    sources = source_catalog()["sources"]
    source = next(item for item in sources if item["name"] == "UN Women Careers")
    assert source["enabled"] is True
    assert source["configuration_required"] is False


def test_un_women_rejects_unrecognized_listing_shape():
    client = FakeClient({0: {"items": [{"unexpected": []}]}}, {})
    assert asyncio.run(collect_un_women(client)) == []

def test_un_women_uses_country_name_from_detailed_location():
    rows = [{
        "Id": 36891,
        "Title": "ICT Associate, G6, Kyiv",
        "PrimaryLocation": "Kyiv, Ukraine",
        "PrimaryLocationCountry": "UA",
    }]
    full_detail = detail("36891", "ICT support and systems administration.")
    full_detail["items"][0].update({
        "PrimaryLocation": "Kyiv, Ukraine",
        "PrimaryLocationCountry": "UA",
    })
    client = FakeClient({0: listing(rows)}, {"36891": full_detail})

    jobs = asyncio.run(collect_un_women(client))

    assert len(jobs) == 1
    assert jobs[0]["country"] == "Ukraine"
    assert jobs[0]["location"] == "Kyiv, Ukraine"


def test_un_women_flags_local_recruitment_without_claiming_mobility():
    rows = [{
        "Id": 36892,
        "Title": "ICT Associate",
        "PrimaryLocation": "Kyiv, Ukraine",
        "PrimaryLocationCountry": "UA",
    }]
    full_detail = detail("36892", "ICT support and systems administration.")
    full_detail["items"][0].update({
        "PrimaryLocation": "Kyiv, Ukraine",
        "PrimaryLocationCountry": "UA",
        "RequisitionType": "FTA Local",
        "requisitionFlexFields": [
            {"Prompt": "Vacancy Category", "Value": "Local Opportunities"},
        ],
    })
    client = FakeClient({0: listing(rows)}, {"36892": full_detail})

    jobs = asyncio.run(collect_un_women(client))

    assert len(jobs) == 1
    assert jobs[0].get("recruitment_scope") == "local"
    assert "recrutement local" in jobs[0]["description"].lower()
    assert "mobilité internationale confirmée" in jobs[0]["description"].lower()
