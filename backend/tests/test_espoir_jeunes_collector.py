from app import espoir_jeunes_collector as collector


def test_accepts_only_official_https_domain():
    assert collector.validate_source_url(collector.SOURCE_URL)
    assert not collector.validate_source_url(
        "http://espoirjeunes.3fpt.sn/catalogue.pdf"
    )
    assert not collector.validate_source_url(
        "https://example.com/catalogue.pdf"
    )
    assert not collector.validate_source_url(
        "https://espoirjeunes.3fpt.sn:444/catalogue.pdf"
    )
    assert not collector.validate_source_url(
        "https://user@espoirjeunes.3fpt.sn/catalogue.pdf"
    )
    assert not collector.validate_source_url(
        "https://espoirjeunes.3fpt.sn/catalogue.pdf#page=2"
    )


def test_detects_it_related_lines_without_creating_offers():
    text = """
    Catalogue de formation
    Développement web et programmation
    Maintenance des équipements agricoles
    Technicien informatique
    Couture traditionnelle
    """

    matches = collector.find_it_related_lines(text)

    assert any("Développement web" in line for line in matches)
    assert any("Technicien informatique" in line for line in matches)
    assert not any("Couture traditionnelle" in line for line in matches)


def test_removes_duplicate_it_lines():
    text = "Formation informatique\nFormation informatique\n"

    matches = collector.find_it_related_lines(text)

    assert len(matches) == 1


def test_rejects_non_pdf_input():
    try:
        collector.extract_pdf_text(b"ceci n'est pas un PDF", enable_ocr=False)
    except ValueError as exc:
        assert "PDF" in str(exc)
    else:
        raise AssertionError("Un contenu non PDF aurait dû être refusé.")


def test_catalogue_is_marked_historical_and_funding_unknown():
    assert collector.CATALOGUE_HISTORICAL is True

    # Une simple ligne issue du catalogue ne prouve ni l'ouverture
    # des candidatures ni le financement intégral.
    assert collector.find_it_related_lines(
        "Formation en développement logiciel"
    )
    assert collector.SOURCE_URL.endswith("ISEP-catalogue-Formation.pdf")


def test_download_rejects_untrusted_url_before_network_access(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Aucun accès réseau ne devrait être tenté.")

    monkeypatch.setattr(collector.httpx, "Client", unexpected_client)

    try:
        collector.download_catalogue("https://example.com/fake.pdf")
    except ValueError as exc:
        assert "URL non autorisée" in str(exc)
    else:
        raise AssertionError("Une URL externe aurait dû être refusée.")
