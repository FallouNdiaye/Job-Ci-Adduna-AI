import asyncio
from datetime import date, timedelta
from urllib.parse import quote

from app.main import (
    UNICEF_SEARCH_URL,
    collect_unicef,
    source_catalog,
)


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        if url in self.pages:
            return FakeResponse(self.pages[url].encode())
        for key, value in self.pages.items():
            if key in url:
                return FakeResponse(value.encode())
        raise AssertionError(f"URL inattendue dans le test : {url}")


def _search(title, job_id="596999"):
    return f'''
    <html><body>
      <a href="/en-us/job/{job_id}/example-vacancy">{title}</a>
    </body></html>
    '''


def _detail(title, deadline, job_id="596999"):
    return f'''
    <html><body>
      <h1>{title}</h1>
      <p>Job no: {job_id}</p>
      <p>Location: Dakar, Senegal</p>
      <p>Contract type: Consultancy</p>
      <p>Deadline: {deadline}</p>
      <p>Eligibility: Check the official vacancy for national eligibility.</p>
    </body></html>
    '''


def test_unicef_keeps_open_it_jobs_and_preserves_source_metadata():
    future = (date.today() + timedelta(days=10)).strftime("%d %b %Y")
    search_url = UNICEF_SEARCH_URL.format(keyword=quote("software"))
    detail_url = "https://jobs.unicef.org/en-us/job/596999/example-vacancy"
    pages = {
        search_url: _search("Software Developer", "596999"),
        detail_url: _detail("Software Developer", future, "596999"),
    }
    # Les autres recherches sont valides mais ne renvoient aucun résultat.
    for keyword in ("developer", "ICT", "information technology", "digital"):
        pages[UNICEF_SEARCH_URL.format(keyword=quote(keyword))] = "<html></html>"

    jobs = asyncio.run(collect_unicef(FakeClient(pages)))
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Software Developer"
    assert job["source"] == "UNICEF Careers"
    assert job["external_id"] == "596999"
    assert job["url"] == detail_url
    assert "Deadline" in job["description"]
    assert "national eligibility" in job["description"]


def test_unicef_excludes_expired_and_non_it_titles():
    expired = (date.today() - timedelta(days=10)).strftime("%d %b %Y")
    search_url = UNICEF_SEARCH_URL.format(keyword=quote("software"))
    detail_url = "https://jobs.unicef.org/en-us/job/596998/example-vacancy"
    pages = {
        search_url: (
            _search("Software Engineer", "596998")
            + _search("Finance Officer", "596997")
        ),
        detail_url: _detail("Software Engineer", expired, "596998"),
    }
    for keyword in ("developer", "ICT", "information technology", "digital"):
        pages[UNICEF_SEARCH_URL.format(keyword=quote(keyword))] = "<html></html>"

    jobs = asyncio.run(collect_unicef(FakeClient(pages)))
    assert jobs == []


def test_unicef_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["UNICEF Careers"]["enabled"] is True
    assert sources["UNICEF Careers"]["configuration_required"] is False
