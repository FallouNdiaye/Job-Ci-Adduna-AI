import pytest

from app.doctoral import parse_feed, validate_feed_url


def test_allowed_https_feed_domain(monkeypatch):
    monkeypatch.setenv(
        "DOCTORAL_ALLOWED_FEED_HOSTS",
        "feeds.example.org;rss.example.net",
    )
    assert (
        validate_feed_url("https://feeds.example.org/doctoral.xml")
        == "https://feeds.example.org/doctoral.xml"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://feeds.example.org/feed.xml",
        "https://unknown.example.org/feed.xml",
        "https://user:password@feeds.example.org/feed.xml",
        "https://feeds.example.org:8443/feed.xml",
        "https://localhost/feed.xml",
        "https://127.0.0.1/feed.xml",
        "https://feeds.example.org/feed.xml#fragment",
    ],
)
def test_rejects_unsafe_or_unapproved_urls(monkeypatch, url):
    monkeypatch.setenv(
        "DOCTORAL_ALLOWED_FEED_HOSTS",
        "feeds.example.org",
    )
    with pytest.raises(ValueError):
        validate_feed_url(url)


def test_rejects_feed_when_allowlist_is_empty(monkeypatch):
    monkeypatch.delenv("DOCTORAL_ALLOWED_FEED_HOSTS", raising=False)
    with pytest.raises(ValueError):
        validate_feed_url("https://feeds.example.org/feed.xml")


def test_accepts_valid_rss_bytes():
    document = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <title>PhD position in Artificial Intelligence</title>
      <link>https://example.org/phd-ai</link>
      <description>Machine learning research.</description>
    </item></channel></rss>"""

    entries = parse_feed(document, "RSS test")
    assert len(entries) == 1
    assert entries[0]["title"] == "PhD position in Artificial Intelligence"
    assert entries[0]["url"] == "https://example.org/phd-ai"


def test_accepts_valid_atom_bytes():
    document = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>Doctoral researcher in computer science</title>
      <link href="https://example.org/doctoral" rel="alternate"/>
    </entry></feed>"""

    entries = parse_feed(document, "Atom test")
    assert len(entries) == 1
    assert entries[0]["url"] == "https://example.org/doctoral"


def test_rejects_doctype_and_entity_declarations():
    document = b"""<?xml version="1.0"?>
    <!DOCTYPE rss [<!ENTITY x "blocked">]>
    <rss><channel><item><title>&x;</title></item></channel></rss>"""

    assert parse_feed(document, "XML test") == []


def test_malformed_xml_returns_empty_list():
    assert parse_feed(b"<rss><item>", "XML test") == []
