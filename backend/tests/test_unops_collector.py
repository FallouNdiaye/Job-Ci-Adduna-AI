import asyncio
from datetime import date, timedelta
from urllib.parse import quote

from app.main import UNOPS_SEARCH_URL, collect_unops, source_catalog


class FakeResponse:
    def __init__(self, content):
        self.content = content.encode() if isinstance(content, str) else content

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        if url in self.pages:
            return FakeResponse(self.pages[url])
        for key, value in self.pages.items():
            if key in url:
                return FakeResponse(value)
        raise AssertionError(f"URL inattendue dans le test : {url}")


def _search(title, job_id="4650"):
    return f"""
    <html><body>
      <a href="/careersmarketplace/JobDetail/example-job/{job_id}">{title}</a>
    </body></html>
    """


def _detail(title, deadline, job_id="4650"):
    return f"""
    <html><body>
      <h1>{title} - {job_id} - UNOPS</h1>
      <p>Functional area</p><p>Information and Communications Technology</p>
      <p>Duty station</p><p>Home based</p>
      <p>Contract Type</p><p>ICA - LICA - Specialist - Retainer</p>
      <p>Contract Level</p><p>LICA 10</p>
      <p>Seniority</p><p>ICS 10</p>
      <p>Posting Start Date</p><p>13-Oct-2026</p>
      <p>Posting End Date</p><p>{deadline}</p>
      <p>Duration</p><p>12 months</p>
      <p>Develop and maintain information systems and mobile applications.</p>
    </body></html>
    """


def _pages(title, deadline, job_id="4650"):
    pages = {}
    for keyword in ("software", "developer", "ICT", "information technology", "mobile", "digital"):
        search_url = UNOPS_SEARCH_URL.format(keyword=quote(keyword))
        pages[search_url] = (
            _search(title, job_id) if keyword == "software" else "<html></html>"
        )
    detail_url = (
        f"https://careers.unops.org/careersmarketplace/JobDetail/example-job/{job_id}"
    )
    pages[detail_url] = _detail(title, deadline, job_id)
    return pages, detail_url


def test_unops_keeps_open_it_job_and_metadata():
    deadline = (date.today() + timedelta(days=10)).strftime("%d-%b-%Y")
    pages, detail_url = _pages("ICT Specialist", deadline)
    jobs = asyncio.run(collect_unops(FakeClient(pages)))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"].startswith("ICT Specialist")
    assert job["source"] == "UNOPS Careers"
    assert job["external_id"] == "4650"
    assert job["url"] == detail_url
    assert job["location"] == "Home based"
    assert job["contract_type"] == "ICA - LICA - Specialist - Retainer"
    assert "Date limite" in job["description"]
    assert "13-Oct-2026" in job["description"]


def test_unops_excludes_expired_job():
    deadline = (date.today() - timedelta(days=10)).strftime("%d-%b-%Y")
    pages, _ = _pages("ICT Specialist", deadline)
    assert asyncio.run(collect_unops(FakeClient(pages))) == []


def test_unops_excludes_non_it_title():
    deadline = (date.today() + timedelta(days=10)).strftime("%d-%b-%Y")
    pages, _ = _pages("Finance Officer", deadline)
    assert asyncio.run(collect_unops(FakeClient(pages))) == []


def test_unops_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["UNOPS Careers"]["enabled"] is True
    assert sources["UNOPS Careers"]["configuration_required"] is False
