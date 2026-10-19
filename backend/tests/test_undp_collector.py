import asyncio
from datetime import datetime, timedelta, timezone

from app.main import UNDP_JOBS_URL, collect_undp, source_catalog


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append((url, headers))
        return FakeResponse(self.content)


def _row(title, grade="NPSA-8", deadline="Dec-31-30",
         agency="UNDP", location="Dakar, Senegal", url_id="37363"):
    url = (
        "https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/"
        f"en/sites/CX_1/requisitions/job/{url_id}"
    )
    return f"""
    <a href="{url}" class="vacanciesTableLink vacanciesTable__row">
      <div class="vacanciesTable__cell"><span>Job Title</span><span>{title}</span></div>
      <div class="vacanciesTable__cell"><span>Post level</span><span>{grade}</span></div>
      <div class="vacanciesTable__cell"><span>Apply by</span><span>{deadline}</span></div>
      <div class="vacanciesTable__cell"><span>Agency</span><span>{agency}</span></div>
      <div class="vacanciesTable__cell"><span>Location</span><span>{location}</span></div>
    </a>
    """


def test_undp_keeps_open_it_jobs_and_preserves_metadata():
    html = (
        "<html><body>"
        + _row("Software Developer", url_id="37363")
        + _row("ICT Analyst", grade="IPSA-9", url_id="37364")
        + _row("Finance Officer", url_id="37365")
        + _row("Data Engineer", deadline="Jan-01-20", url_id="37366")
        + "</body></html>"
    ).encode()
    client = FakeClient(html)

    jobs = asyncio.run(collect_undp(client))

    assert len(client.calls) == 1
    assert client.calls[0][0] == UNDP_JOBS_URL
    assert {job["title"] for job in jobs} == {"Software Developer", "ICT Analyst"}

    software = next(job for job in jobs if job["title"] == "Software Developer")
    assert software["source"] == "UNDP Careers"
    assert software["external_id"] == "37363"
    assert software["url"].endswith("/requisitions/job/37363")
    assert "NPSA-8" in software["description"]
    assert "Dec-31-30" in software["description"]
    assert "Dakar, Senegal" in software["description"]


def test_undp_rejects_non_oracle_urls_and_unreadable_deadlines():
    html = b"""
    <a href="https://example.com/requisitions/job/1"
       class="vacanciesTableLink vacanciesTable__row">
      <div class="vacanciesTable__cell">Software Developer</div>
      <div class="vacanciesTable__cell">NPSA-8</div>
      <div class="vacanciesTable__cell">Dec-31-30</div>
      <div class="vacanciesTable__cell">UNDP</div>
      <div class="vacanciesTable__cell">Remote</div>
    </a>
    """ + _row("Software Developer", deadline="date inconnue", url_id="37367").encode()

    jobs = asyncio.run(collect_undp(FakeClient(html)))
    assert jobs == []


def test_undp_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["UNDP Careers"]["enabled"] is True
    assert sources["UNDP Careers"]["configuration_required"] is False
