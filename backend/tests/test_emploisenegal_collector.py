import asyncio
from email.utils import formatdate

from app.main import (
    collect_emploisenegal,
    source_catalog,
    EMPLOISENEGAL_RSS_URL,
)


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append(url)
        return FakeResponse(self.content)


def rss_item(title, url, description, guid="1085931"):
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<link>{url}</link>"
        f"<description><![CDATA[{description}]]></description>"
        f"<pubDate>{formatdate(1790674328, usegmt=True)}</pubDate>"
        f"<guid>{guid} at {url}</guid>"
        "</item>"
    )


def rss(*items):
    return ("<rss version='2.0'><channel>" + "".join(items)
            + "</channel></rss>").encode()


def test_collects_it_job_from_official_rss():
    url = "https://www.emploisenegal.com/offre-emploi-senegal/java-developer-1085931"
    xml = rss(rss_item(
        "JAVA Developer (M/F)", url,
        "<p>Develop Java applications with Spring Boot and REST APIs.</p>",
    ))
    jobs = asyncio.run(collect_emploisenegal(FakeClient(xml)))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "JAVA Developer (M/F)"
    assert job["source"] == "EmploiSenegal"
    assert job["country"] == "Sénégal"
    assert job["external_id"] == "1085931"
    assert job["published_at"]
    assert "Spring Boot" in job["description"]
    assert "non précisé" in job["company"].lower()


def test_rejects_external_urls_and_non_it_jobs():
    external = "https://example.com/offre-emploi-senegal/java-1085932"
    irrelevant = "https://www.emploisenegal.com/offre-emploi-senegal/accountant-1085933"
    xml = rss(
        rss_item("Java Developer", external, "Java Spring Boot"),
        rss_item("Accountant", irrelevant, "Accounting and finance", "1085933"),
    )
    client = FakeClient(xml)
    assert asyncio.run(collect_emploisenegal(client)) == []
    assert client.calls == [EMPLOISENEGAL_RSS_URL]


def test_rejects_candidate_request():
    url = "https://www.emploisenegal.com/offre-emploi-senegal/demande-emploi-1085934"
    xml = rss(rss_item(
        "Demande d'emploi développeur",
        url,
        "Je recherche un emploi informatique.",
        "1085934",
    ))
    assert asyncio.run(collect_emploisenegal(FakeClient(xml))) == []


def test_rejects_doctype():
    xml = b'<!DOCTYPE rss [<!ENTITY x "test">]><rss><channel/></rss>'
    try:
        asyncio.run(collect_emploisenegal(FakeClient(xml)))
    except ValueError as exc:
        assert "DOCTYPE/ENTITY" in str(exc)
    else:
        raise AssertionError("Le flux avec DOCTYPE aurait dû être refusé.")


def test_emploisenegal_is_registered_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["EmploiSenegal"]["enabled"] is True
    assert sources["EmploiSenegal"]["configuration_required"] is False
