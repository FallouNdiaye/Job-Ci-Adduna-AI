import asyncio

from app.main import FAO_SEARCH_URL, collect_fao, source_catalog


def make_record(internal_id, title, requisition, location="Italy-Rome",
                date_text="16/Oct/2026"):
    record = [""] * 36
    record[2] = str(internal_id)
    record[3] = title
    record[7] = str(requisition)
    record[8] = location
    record[14] = date_text
    return record


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, page):
        self.page = page
        self.requested_url = None

    async def get(self, url, headers=None):
        self.requested_url = url
        assert headers and "User-Agent" in headers
        return FakeResponse(self.page)


def make_page(*records):
    import reprlib
    flat = [value for record in records for value in record]
    # repr(list) creates a Python literal accepted by the parser under test.
    return (
        "<html><script>"
        "api.fillList('requisitionListInterface', 'listRequisition', "
        + reprlib.repr(flat).replace("...", "")
        + ");</script></html>"
    )


def test_fao_collects_it_jobs_and_uses_unique_identifiers():
    # Use a complete literal rather than reprlib's abbreviated representation.
    import reprlib
    records = [
        make_record(1, "Software Developer", 2602157),
        make_record(2, "IT Systems Specialist", 2602155),
        make_record(3, "Finance Specialist", 2602154),
    ]
    flat = [value for record in records for value in record]
    page = (
        "<script>api.fillList('requisitionListInterface', 'listRequisition', "
        + repr(flat)
        + ");</script>"
    )
    client = FakeClient(page)

    jobs = asyncio.run(collect_fao(client))

    assert client.requested_url == FAO_SEARCH_URL
    assert len(jobs) == 2
    assert {job["external_id"] for job in jobs} == {"2602157", "2602155"}
    assert len({job["content_hash"] for job in jobs}) == 2
    assert all(job["url"] == FAO_SEARCH_URL for job in jobs)
    assert all("Numéro de réquisition FAO" in job["description"] for job in jobs)
    assert next(job for job in jobs if job["external_id"] == "2602157")["published_at"] == "2026-10-16"


def test_fao_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["FAO Careers"]["enabled"] is True
    assert sources["FAO Careers"]["configuration_required"] is False


def test_fao_rejects_malformed_record_structure():
    client = FakeClient(
        "<script>api.fillList('requisitionListInterface', 'listRequisition', ['bad']);</script>"
    )
    try:
        asyncio.run(collect_fao(client))
    except ValueError as exc:
        assert "Structure des résultats FAO" in str(exc)
    else:
        raise AssertionError("Une structure FAO invalide aurait dû être rejetée.")
