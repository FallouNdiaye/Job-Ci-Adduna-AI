from bs4 import BeautifulSoup

from app import training_collector as collector


def test_detects_individual_training_card():
    html = """
    <div class="pad">
      <div class="details-ctnr">
        <h3 class="name">
          <a href="/certificat/developpement-logiciel-java">
            Développement logiciel Java
          </a>
        </h3>
        <div class="desc prez">
          Apprentissage de Java et du développement logiciel.
        </div>
      </div>
      <div class="cta-ctnr">
        <a href="/certificat/developpement-logiciel-java">Voir la formation</a>
      </div>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = collector.find_cards(soup)

    assert len(cards) == 1
    url, title, summary = collector.extract_card_link(
        cards[0], collector.CATALOG_URL
    )

    assert title == "Développement logiciel Java"
    assert url == (
        "https://force-n.sn/certificat/developpement-logiciel-java"
    )
    assert "Java" in summary
    assert collector.is_it_related(f"{title} {summary}")


def test_rejects_external_and_unsafe_urls():
    assert collector.official_url(
        "https://force-n.sn/certificat/cybersecurite"
    )
    assert not collector.official_url(
        "http://force-n.sn/certificat/cybersecurite"
    )
    assert not collector.official_url(
        "https://example.com/certificat/cybersecurite"
    )
    assert not collector.official_url(
        "https://force-n.sn:444/certificat/cybersecurite"
    )
    assert not collector.official_url(
        "https://user@force-n.sn/certificat/cybersecurite"
    )


def test_non_it_card_is_not_classified_as_it():
    assert not collector.is_it_related(
        "Formation en couture et broderie traditionnelle"
    )


def test_free_funding_requires_explicit_evidence():
    import re

    explicit_phrases = (
        "Cette formation est 100% gratuite.",
        "Formation entièrement offerte par la Fondation Mastercard",
        "Formation entierement offerte par la Fondation Mastercard",
    )
    vague = "Des possibilités de financement peuvent exister."

    for phrase in explicit_phrases:
        assert any(
            re.search(pattern, phrase, flags=re.IGNORECASE)
            for pattern in collector.FREE_PATTERNS
        ), f"La gratuité explicite n'est pas reconnue : {phrase}"

    assert not any(
        re.search(pattern, vague, flags=re.IGNORECASE)
        for pattern in collector.FREE_PATTERNS
    )


def test_detects_explicit_free_badge_on_catalogue_card():
    html = """
    <div class="pad">
      <h3 class="name">
        <a href="/certificat/dessin-digital">Dessin digital</a>
      </h3>
      <div class="desc prez">Formation pratique en dessin digital.</div>
      <span class="badge">Gratuit</span>
      <a href="/certificat/dessin-digital">Voir la formation</a>
    </div>
    """
    card = BeautifulSoup(html, "html.parser").select_one(".pad")
    assert collector.card_has_explicit_free_badge(card)


def test_does_not_treat_vague_financing_as_free_badge():
    html = """
    <div class="pad">
      <h3 class="name"><a href="/certificat/test">Formation test</a></h3>
      <div class="desc prez">
        Des possibilités de financement peuvent exister.
      </div>
    </div>
    """
    card = BeautifulSoup(html, "html.parser").select_one(".pad")
    assert not collector.card_has_explicit_free_badge(card)


def test_extracts_explicit_pre_registration_link_without_following_redirects():
    html = """
    <a href="https://urlz.fr/lB3G">Se préinscrire</a>
    <a href="https://fode.force-n.sn/fode">Accéder à la plateforme</a>
    """
    page = BeautifulSoup(html, "html.parser")
    assert collector.extract_application_url(
        page, "https://force-n.sn/certificat/test"
    ) == "https://urlz.fr/lB3G"


def test_rejects_unsafe_pre_registration_links():
    html = """
    <a href="https://example.com/apply">Se préinscrire</a>
    <a href="http://urlz.fr/lB3G">Se préinscrire</a>
    <a href="javascript:alert(1)">Se préinscrire</a>
    """
    page = BeautifulSoup(html, "html.parser")
    assert collector.extract_application_url(
        page, "https://force-n.sn/certificat/test"
    ) == ""
