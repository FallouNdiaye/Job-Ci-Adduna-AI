import pytest
from app.doctoral import (
    parse_campus_france_detail,
    parse_campus_france_listing_row,
    validate_campus_france_url,
)


def test_rejects_non_official_campus_france_urls():
    for url in (
        "http://doctorat.campusfrance.org/fr/phd/offers",
        "https://example.org/fr/phd/offers",
        "https://doctorat.campusfrance.org.evil.example/phd",
        "https://user@doctorat.campusfrance.org/phd",
        "https://doctorat.campusfrance.org:8443/phd",
    ):
        with pytest.raises(ValueError):
            validate_campus_france_url(url)


def test_accepts_official_campus_france_url():
    url = "https://doctorat.campusfrance.org/fr/phd/offers/CF202649648"
    assert validate_campus_france_url(url) == url


def test_listing_row_extracts_only_official_detail_links():
    row = {
        "action": '<a href="/fr/phd/offers/CF202649647">Voir</a>',
        "dt_name": "",
    }
    assert parse_campus_france_listing_row(row) == (
        "https://doctorat.campusfrance.org/fr/phd/offers/CF202649647"
    )


def test_listing_row_rejects_external_link():
    row = {
        "action": '<a href="https://example.org/phd">Voir</a>',
        "dt_name": "",
    }
    assert parse_campus_france_listing_row(row) is None


def test_detail_parser_extracts_title_and_conservative_funding():
    html = """
    <html><head><title>PhD in software engineering</title></head>
    <body><h1>PhD in software engineering</h1>
    <p>Doctorat. Domaine Informatique.</p>
    <p>Financement multiple. Date limite de candidature : 31/12/2026</p>
    </body></html>
    """
    result = parse_campus_france_detail(
        html,
        "https://doctorat.campusfrance.org/fr/phd/offers/CF202649648",
    )
    assert result["title"] == "PhD in software engineering"
    assert result["opportunity_type"] == "doctorats"
    assert result["funding_status"] in {
        "UNKNOWN", "UNCONFIRMED", "PARTIAL", "CONFIRMED_FULL"
    }
    assert result["deadline"] == "2026-12-31"
    assert result["source"] == "Campus France — offres de doctorat"


def test_rejects_malformed_port_with_controlled_error():
    with pytest.raises(ValueError, match="URL Campus France refusée"):
        validate_campus_france_url(
            "https://doctorat.campusfrance.org:99999/fr/phd/offers"
        )


def test_collector_handles_http_error_without_crashing():
    import asyncio
    import httpx
    from app.doctoral import collect_campus_france

    def handler(request):
        return httpx.Response(
            503,
            headers={"content-type": "application/json"},
            json={"data": [], "recordsTotal": 0},
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        ) as client:
            return await collect_campus_france(client, max_pages=1)

    result = asyncio.run(run())
    assert result["offers"] == []
    assert result["pages_scanned"] == 1
    assert len(result["errors"]) == 1
    assert "503" in result["errors"][0]


def test_collector_continues_after_one_detail_fails():
    import asyncio
    import httpx
    from app.doctoral import collect_campus_france

    good_url = "https://doctorat.campusfrance.org/fr/phd/offers/CF202600002"

    def handler(request):
        if request.url.path.endswith("ajax_dtlist"):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "recordsTotal": 2,
                    "recordsFiltered": 2,
                    "data": [
                        {"action": '<a href="/fr/phd/offers/CF202600001">Voir</a>'},
                        {"action": '<a href="/fr/phd/offers/CF202600002">Voir</a>'},
                    ],
                },
            )
        if request.url.path.endswith("CF202600001"):
            return httpx.Response(
                500, headers={"content-type": "text/html"}, text="Erreur simulée"
            )
        if request.url.path.endswith("CF202600002"):
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text="<html><body><h1>PhD in software engineering</h1><p>Doctorat en informatique.</p></body></html>",
            )
        return httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        ) as client:
            return await collect_campus_france(client, max_pages=1, page_size=2)

    result = asyncio.run(run())
    assert len(result["offers"]) == 1
    assert result["offers"][0]["url"] == good_url
    assert len(result["errors"]) == 1
    assert "CF202600001" in result["errors"][0]
