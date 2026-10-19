import asyncio
from urllib.parse import urlparse

from app.main import collect_expat_dakar, source_catalog, EXPAT_DAKAR_SITEMAPS


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append(url)
        return FakeResponse(self.pages.get(url, b"<html></html>"))


def sitemap(*urls):
    entries = "".join(f"<url><loc>{url}</loc></url>" for url in urls)
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'.encode()


def job_page(title, description, company="Entreprise Test"):
    import json

    data = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": description,
        "datePosted": "2026-10-01",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {"@type": "Organization", "name": company},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Dakar",
                "addressCountry": "SN",
            },
        },
    }
    return (
        "<html><head><title>Annonce | Expat-Dakar</title>"
        '<meta name="description" content="Offre d’emploi informatique">'
        '<script type="application/ld+json">'
        + json.dumps(data)
        + "</script></head><body></body></html>"
    ).encode()


def test_expat_dakar_extracts_it_job_from_official_announcement():
    url = "https://www.expat-dakar.com/annonce/developpeur-java-1234567"
    pages = {
        EXPAT_DAKAR_SITEMAPS[0]: sitemap(url),
        EXPAT_DAKAR_SITEMAPS[1]: sitemap(),
        url: job_page("Développeur Java", "Développement Java et Spring Boot."),
    }
    jobs = asyncio.run(collect_expat_dakar(FakeClient(pages)))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Développeur Java"
    assert job["company"] == "Entreprise Test"
    assert job["source"] == "Expat-Dakar"
    assert job["country"] == "Sénégal"
    assert job["external_id"] == "1234567"
    assert job["published_at"] == "2026-10-01"


def test_expat_dakar_rejects_candidate_requests_and_non_it_jobs():
    candidate = "https://www.expat-dakar.com/annonce/demande-emploi-developpeur-1234567"
    irrelevant = "https://www.expat-dakar.com/annonce/commercial-1234568"
    pages = {
        EXPAT_DAKAR_SITEMAPS[0]: sitemap(candidate, irrelevant),
        EXPAT_DAKAR_SITEMAPS[1]: sitemap(),
        candidate: job_page("Demande d'emploi développeur", "Je recherche un emploi informatique."),
        irrelevant: job_page("Commercial", "Recrutement commercial et vente."),
    }
    assert asyncio.run(collect_expat_dakar(FakeClient(pages))) == []


def test_expat_dakar_rejects_external_urls():
    external = "https://example.com/annonce/developpeur-java-1234567"
    pages = {
        EXPAT_DAKAR_SITEMAPS[0]: sitemap(external),
        EXPAT_DAKAR_SITEMAPS[1]: sitemap(),
    }
    client = FakeClient(pages)
    assert asyncio.run(collect_expat_dakar(client)) == []
    assert all(url in EXPAT_DAKAR_SITEMAPS for url in client.calls)


def test_expat_dakar_is_registered_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["Expat-Dakar"]["enabled"] is True
    assert sources["Expat-Dakar"]["configuration_required"] is False
