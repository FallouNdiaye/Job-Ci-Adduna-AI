import asyncio
import json

from app.main import LIGGEY_CATEGORY_URL, collect_liggey, source_catalog


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


def posting_page(title, description, company="Entreprise Test"):
    data = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": description,
        "datePosted": "2026-10-08T00:00:00Z",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {"@type": "Organization", "name": company},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Dakar",
                "addressCountry": "Sénégal",
            },
        },
    }
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps(data)
        + "</script></head><body></body></html>"
    ).encode()


def category_page(*urls):
    links = "".join(f'<a href="{url}">Annonce</a>' for url in urls)
    return f"<html><body>{links}</body></html>".encode()


def test_liggey_collects_cloud_and_developer_jobs():
    cloud = "https://liggey.com/missions/ingenieur-cloud-red-tic-2"
    developer = "https://liggey.com/missions/developpeur-solutions-informatiques"
    client = FakeClient({
        LIGGEY_CATEGORY_URL: category_page(cloud, developer),
        cloud: posting_page("Ingénieur Cloud", "Administration cloud et infrastructure."),
        developer: posting_page("Développeur", "Développement de solutions informatiques."),
    })

    jobs = asyncio.run(collect_liggey(client))

    assert len(jobs) == 2
    assert {job["title"] for job in jobs} == {"Ingénieur Cloud", "Développeur"}
    assert all(job["source"] == "Liggey" for job in jobs)
    assert all(job["country"] == "Sénégal" for job in jobs)
    assert all(job["url"].startswith("https://liggey.com/missions/") for job in jobs)


def test_liggey_keeps_relevant_data_architect_but_rejects_non_it_titles():
    data = "https://liggey.com/missions/data-architect-baamtu"
    sales = "https://liggey.com/missions/apporteur-d-affaires-dakar-bluepinksecurity"
    accounting = "https://liggey.com/missions/comptable-odoo-important-cabinet-de-la-place"
    client = FakeClient({
        LIGGEY_CATEGORY_URL: category_page(data, sales, accounting),
        data: posting_page("Data Architect", "Architecture de données et systèmes."),
        sales: posting_page("Apporteur d’Affaires - Dakar", "Développement commercial."),
        accounting: posting_page("Comptable Odoo", "Gestion comptable sur Odoo."),
    })

    jobs = asyncio.run(collect_liggey(client))

    assert [job["title"] for job in jobs] == ["Data Architect"]


def test_liggey_never_requests_external_or_non_mission_urls():
    external = "https://example.com/missions/developpeur"
    wrong_path = "https://liggey.com/emplois/developpement-it/dakar"
    client = FakeClient({
        LIGGEY_CATEGORY_URL: category_page(
            external,
            wrong_path,
            "http://liggey.com/missions/developpeur",
            "https://liggey.com.evil.example/missions/developpeur",
        ),
    })

    assert asyncio.run(collect_liggey(client)) == []
    assert client.calls == [LIGGEY_CATEGORY_URL]


def test_liggey_is_registered_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["Liggey"]["enabled"] is True
    assert sources["Liggey"]["configuration_required"] is False
