import asyncio

from app.main import CNRS_RSS_URL, collect_cnrs, source_catalog


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
        self.calls.append((url, headers))
        return FakeResponse(self.content)


def rss_item(title, url, category, description="Annonce de recrutement"):
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<link>{url}</link>"
        f"<category>{category}</category>"
        f"<description><![CDATA[{description}]]></description>"
        "<pubDate>Sat, 17 Oct 2026 10:00:00 GMT</pubDate>"
        "</item>"
    )


def rss(*items):
    return (
        "<rss version='2.0'><channel>"
        + "".join(items)
        + "</channel></rss>"
    ).encode("utf-8")


def test_collects_relevant_cnrs_it_job():
    url = "https://emploi.cnrs.fr/Offres/2026/IT-123"
    client = FakeClient(rss(rss_item(
        "Développeur logiciel",
        url,
        "IT en contrat à durée déterminée",
        "Développement logiciel et API.",
    )))

    jobs = asyncio.run(collect_cnrs(client))

    assert len(jobs) == 1
    assert jobs[0]["title"]
    assert jobs[0]["country"] == "France"
    assert jobs[0]["source"] == "CNRS"
    assert jobs[0]["url"] == url
    assert client.calls[0][0] == CNRS_RSS_URL


def test_accepts_it_title_in_researcher_category():
    client = FakeClient(rss(rss_item(
        "Développeur logiciel",
        "https://emploi.cnrs.fr/Offres/2026/IT-124",
        "Chercheur en contrat à durée déterminée",
    )))

    jobs = asyncio.run(collect_cnrs(client))
    assert len(jobs) == 1
    assert jobs[0]["country"] == "France"


def test_rejects_doctorate_and_internship():
    client = FakeClient(rss(
        rss_item(
            "Doctorant en informatique",
            "https://emploi.cnrs.fr/Offres/2026/IT-125",
            "IT en contrat doctoral",
        ),
        rss_item(
            "Stage développement logiciel",
            "https://emploi.cnrs.fr/Offres/2026/IT-126",
            "IT en contrat de stage",
        ),
    ))

    assert asyncio.run(collect_cnrs(client)) == []


def test_rejects_external_url():
    client = FakeClient(rss(rss_item(
        "Développeur logiciel",
        "https://example.com/Offres/2026/IT-127",
        "IT en contrat à durée déterminée",
    )))

    assert asyncio.run(collect_cnrs(client)) == []


def test_rejects_doctype():
    client = FakeClient(
        b'<!DOCTYPE rss [<!ENTITY x "test">]><rss><channel/></rss>'
    )

    try:
        asyncio.run(collect_cnrs(client))
    except ValueError as exc:
        assert "DOCTYPE/ENTITY" in str(exc)
    else:
        raise AssertionError("Le flux contenant DOCTYPE aurait dû être refusé.")


def test_rejects_oversized_feed():
    client = FakeClient(b" " * (5 * 1024 * 1024 + 1))

    try:
        asyncio.run(collect_cnrs(client))
    except ValueError as exc:
        assert "5 Mo" in str(exc)
    else:
        raise AssertionError("Le flux trop volumineux aurait dû être refusé.")


def test_cnrs_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}

    assert sources["CNRS"]["enabled"] is True
    assert sources["CNRS"]["configuration_required"] is False
