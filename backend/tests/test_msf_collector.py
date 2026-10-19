import asyncio
from datetime import date, timedelta

from app.main import MSF_JOBS_URL, collect_msf


class FakeResponse:
    def __init__(self, html):
        self.content = html.encode()

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError(f"URL inattendue : {url}")
        return FakeResponse(self.pages[url])


def test_msf_collects_relevant_it_job_and_deadline():
    detail_url = (
        "https://www.msf.fr/agir/rejoindre-nos-equipes/"
        "toutes-nos-offres-emploi/ingenieur-logiciel"
    )
    deadline = (date.today() + timedelta(days=20)).isoformat()
    listing = f'<a href="{detail_url}">Ingénieur logiciel</a>'
    detail = f"""
    <html><head>
      <script type="application/ld+json">{{
        "@context":"https://schema.org","@type":"JobPosting",
        "title":"Ingénieur logiciel","datePosted":"2026-10-14",
        "validThrough":"{deadline}",
        "identifier":{{"value":"MSF-123"}},
        "hiringOrganization":{{"name":"Médecins Sans Frontières"}},
        "description":"Développement logiciel et API."
      }}</script>
    </head><body><h1>Ingénieur logiciel</h1>
    <p>Développement logiciel et API.</p></body></html>
    """
    client = FakeClient({MSF_JOBS_URL: listing, detail_url: detail})

    jobs = asyncio.run(collect_msf(client))

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Ingénieur logiciel"
    assert jobs[0]["company"] == "Médecins Sans Frontières (MSF)"
    assert jobs[0]["source"] == "MSF Careers"
    assert jobs[0]["external_id"] == "MSF-123"
    assert f"Date limite publiée par MSF : {deadline}" in jobs[0]["description"]
    assert len(client.calls) == 2


def test_msf_excludes_expired_jobs():
    detail_url = (
        "https://www.msf.fr/agir/rejoindre-nos-equipes/"
        "toutes-nos-offres-emploi/ingenieur-logiciel"
    )
    expired = (date.today() - timedelta(days=1)).isoformat()
    listing = f'<a href="{detail_url}">Ingénieur logiciel</a>'
    detail = f"""
    <h1>Ingénieur logiciel</h1>
    <script type="application/ld+json">{{
      "@type":"JobPosting","title":"Ingénieur logiciel",
      "validThrough":"{expired}"
    }}</script>
    """
    client = FakeClient({MSF_JOBS_URL: listing, detail_url: detail})

    assert asyncio.run(collect_msf(client)) == []


def test_msf_ignores_non_it_and_external_links():
    listing = """
    <a href="https://www.msf.fr/agir/rejoindre-nos-equipes/"
       >Responsable logistique</a>
    <a href="https://example.com/agir/rejoindre-nos-equipes/"
       >Développeur logiciel</a>
    """
    client = FakeClient({MSF_JOBS_URL: listing})

    assert asyncio.run(collect_msf(client)) == []
    assert client.calls == [MSF_JOBS_URL]
