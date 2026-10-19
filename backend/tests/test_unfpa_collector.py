import asyncio
from datetime import date, timedelta

from app.main import UNFPA_JOBS_URL, collect_unfpa, source_catalog


class FakeResponse:
    def __init__(self, content):
        self.content = content.encode("utf-8")

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        assert headers and "User-Agent" in headers
        if url not in self.pages:
            raise AssertionError(f"URL inattendue : {url}")
        return FakeResponse(self.pages[url])


def _listing(*links):
    return "<html><body>" + "".join(
        f'<a href="{url}">{title}</a>' for title, url in links
    ) + "</body></html>"


def _detail(title, closing_date, job_id="90001"):
    return f"""
    <html><body>
      <h1>{title}</h1>
      <div><span>Duty station</span><span>Dakar</span></div>
      <div><span>Closing date</span><span>{closing_date}</span></div>
      <div><span>Job ID</span><span>{job_id}</span></div>
      <p>Software development, systems and application support.</p>
      <a href="https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2003/job/{job_id}/">Apply</a>
    </body></html>
    """


def test_unfpa_keeps_open_it_jobs_and_metadata():
    deadline = (date.today() + timedelta(days=10)).strftime("%d %B %Y")
    detail_url = "https://www.unfpa.org/jobs/software-developer-example"
    pages = {
        UNFPA_JOBS_URL: _listing(
            ("Software Developer", detail_url),
            ("Finance Officer", "https://www.unfpa.org/jobs/finance-officer"),
        ),
        detail_url: _detail("Software Developer", deadline),
    }
    client = FakeClient(pages)

    jobs = asyncio.run(collect_unfpa(client))

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Software Developer"
    assert job["source"] == "UNFPA Careers"
    assert job["company"] == "UNFPA"
    assert job["location"] == "Dakar"
    assert job["external_id"] == "90001"
    assert job["url"] == detail_url
    assert "Closing date" in job["description"]
    assert "CandidateExperience" in job["description"]


def test_unfpa_excludes_expired_it_jobs():
    deadline = (date.today() - timedelta(days=10)).strftime("%d %B %Y")
    detail_url = "https://www.unfpa.org/jobs/expired-software-developer"
    client = FakeClient({
        UNFPA_JOBS_URL: _listing(("Software Developer", detail_url)),
        detail_url: _detail("Software Developer", deadline, "90002"),
    })

    assert asyncio.run(collect_unfpa(client)) == []


def test_unfpa_catalog_entry_is_enabled():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["UNFPA Careers"]["enabled"] is True
    assert sources["UNFPA Careers"]["configuration_required"] is False
