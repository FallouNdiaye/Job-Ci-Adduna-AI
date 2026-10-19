from app.immigration import ROUTES, list_immigration_routes


def test_catalogue_contains_unique_routes():
    result = list_immigration_routes()

    assert result["count"] == len(ROUTES)
    assert result["count"] >= 6
    assert len({route["id"] for route in result["routes"]}) == result["count"]
    assert result["read_only"] is True


def test_each_route_has_required_information_and_https_url():
    required = {
        "id", "country", "title", "category", "offer_required",
        "offer_note", "sponsorship_status", "summary", "requirements",
        "official_url", "source_status",
    }
    allowed_statuses = {
        "LIEN_OFFICIEL_A_VERIFIER",
        "SOURCE_OFFICIELLE",
        "DATES_A_VERIFIER",
        "CONDITIONS_A_VERIFIER",
    }

    for route in ROUTES:
        assert required.issubset(route.keys()), route.get("id")
        assert route["official_url"].startswith("https://"), route["id"]
        assert route["source_status"] in allowed_statuses, route["id"]


def test_expected_destinations_are_present():
    countries = {route["country"] for route in ROUTES}

    assert {
        "Allemagne",
        "Canada",
        "Union européenne",
        "France",
        "Pays-Bas",
        "États-Unis",
    }.issubset(countries)

    assert "Irlande" in countries
def test_immigration_endpoint_is_registered_in_fastapi():
    from app.main import app

    paths = app.openapi().get("paths", {})
    assert "/api/immigration" in paths
    assert "get" in paths["/api/immigration"]
