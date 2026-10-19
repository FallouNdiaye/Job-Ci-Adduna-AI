import asyncio

import httpx
import pytest

from app.doctoral import (
    EIFFEL_CAMPUS_FRANCE_URL,
    EIFFEL_PARIS_SACLAY_URL,
    collect_eiffel_scholarships,
    parse_eiffel_page,
)


def test_national_eiffel_page_creates_aid_not_doctorate():
    html = """
    <html><head><title>France Excellence Eiffel 2027</title></head>
    <body>
      <h1>France Excellence Eiffel 2027-2028</h1>
      <p>Appel à candidatures ouvert aux niveaux master et doctorat.</p>
      <p>Date limite de transmission par les établissements : 6 janvier 2027.</p>
      <p>Les frais de scolarité ne sont pas pris en charge.</p>
    </body></html>
    """

    offer = parse_eiffel_page(html, "campus_france")

    assert offer["opportunity_type"] == "aides"
    assert offer["country"] == "France"
    assert offer["deadline"] == "2027-01-06"
    assert offer["funding_status"] == "PARTIAL"
    assert offer["tuition_status"] == "Non couverts"
    assert offer["url"] == EIFFEL_CAMPUS_FRANCE_URL
    assert "établissements" in offer["eligibility"].lower()


def test_paris_saclay_page_does_not_invent_internal_deadline():
    html = """
    <html><body>
      <h1>France Excellence Eiffel scholarship 2027-2028</h1>
      <p>Université Paris-Saclay supports applications for master and PhD.</p>
      <p>Contact the university for its application procedure.</p>
    </body></html>
    """

    offer = parse_eiffel_page(html, "paris_saclay")

    assert offer["opportunity_type"] == "aides"
    assert offer["institution"] == "Université Paris-Saclay"
    assert offer["deadline"] is None
    assert offer["url"] == EIFFEL_PARIS_SACLAY_URL


@pytest.mark.parametrize(
    "source_kind",
    ["campus_france", "paris_saclay"],
)
def test_eiffel_parser_rejects_pages_without_current_campaign(source_kind):
    with pytest.raises(ValueError):
        parse_eiffel_page(
            "<html><body><h1>Ancienne campagne</h1></body></html>",
            source_kind,
        )


def test_eiffel_collector_handles_http_errors_independently():
    def handler(request):
        if str(request.url) == EIFFEL_CAMPUS_FRANCE_URL:
            return httpx.Response(
                503,
                headers={"content-type": "text/html"},
                text="Service indisponible",
            )
        if str(request.url) == EIFFEL_PARIS_SACLAY_URL:
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=(
                    "<html><body><h1>France Excellence Eiffel "
                    "scholarship 2027-2028</h1>"
                    "<p>Université Paris-Saclay master and PhD.</p>"
                    "</body></html>"
                ),
            )
        return httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        ) as client:
            return await collect_eiffel_scholarships(client)

    result = asyncio.run(run())

    assert len(result["offers"]) == 1
    assert result["offers"][0]["institution"] == "Université Paris-Saclay"
    assert len(result["errors"]) == 1
    assert "503" in result["errors"][0]
