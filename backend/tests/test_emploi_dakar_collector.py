import asyncio
import json

from app.main import (
    EMPLOI_DAKAR_SITEMAP_URL,
    collect_emploi_dakar,
    source_catalog,
)


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append(url)
        if url not in self.responses:
            raise AssertionError(f"URL inattendue : {url}")
        return FakeResponse(self.responses[url])


def detail(title, description, company="ALTEN Sénégal"):
    posting = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": description,
        "datePosted": "2026-09-24T14:44:25+00:00",
        "validThrough": "2026-10-24T23:59:59+00:00",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {"@type": "Organization", "name": company},
        "jobLocation": {
            "@type": "Place",
            "address": "Dakar, Sénégal",
        },
    }
    return (
        "<html><head><script type='application/ld+json'>"
        + json.dumps(posting)
        + "</script></head><body></body></html>"
    ).encode()


def sitemap(*urls):
    return (
        "<urlset>"
        + "".join(f"<url><loc>{url}</loc></url>" for url in urls)
        + "</urlset>"
    ).encode()


def test_collects_it_job_from_public_sitemap():
    url = (
        "https://www.emploidakar.com/offre-demploi/"
        "alten-developpeur-fullstack-java-angular/"
    )
    client = FakeClient({
        EMPLOI_DAKAR_SITEMAP_URL: sitemap(url),
        url: detail(
            "Développeur FullStack Sénior – Java / Angular",
            "<p>Développer des applications Java et Angular.</p>",
        ),
    })

    jobs = asyncio.run(collect_emploi_dakar(client))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "Emploi Dakar"
    assert job["title"].startswith("Développeur FullStack")
    assert job["company"] == "ALTEN Sénégal"
    assert job["country"] == "Sénégal"
    assert job["published_at"].startswith("2026-09-24")
    assert "Java" in job["description"]
    assert job["url"] == url
    assert client.calls[0] == EMPLOI_DAKAR_SITEMAP_URL


def test_rejects_non_it_and_external_urls():
    it_url = (
        "https://www.emploidakar.com/offre-demploi/"
        "comptable-senior/"
    )
    external_url = "https://example.com/offre-demploi/java-developer/"
    client = FakeClient({
        EMPLOI_DAKAR_SITEMAP_URL: sitemap(it_url, external_url),
        it_url: detail("Comptable senior", "Comptabilité et finance."),
    })

    assert asyncio.run(collect_emploi_dakar(client)) == []
    assert external_url not in client.calls


def test_rejects_sitemap_with_doctype():
    client = FakeClient({
        EMPLOI_DAKAR_SITEMAP_URL:
            b'<!DOCTYPE urlset [<!ENTITY x "test">]><urlset/>',
    })
    try:
        asyncio.run(collect_emploi_dakar(client))
    except ValueError as exc:
        assert "DOCTYPE/ENTITY" in str(exc)
    else:
        raise AssertionError("Le sitemap avec DOCTYPE aurait dû être refusé.")


def test_emploi_dakar_is_registered_in_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["Emploi Dakar"]["enabled"] is True
    assert sources["Emploi Dakar"]["configuration_required"] is False
