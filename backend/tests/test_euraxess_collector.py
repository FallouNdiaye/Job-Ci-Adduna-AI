import asyncio

from app.main import collect_euraxess, source_catalog


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
        self.calls.append((url, params))
        page = (params or {}).get("page", 0)
        return FakeResponse(self.pages.get(page, b"<html><body>No results</body></html>"))


def test_euraxess_keeps_it_job_and_rejects_irrelevant_and_external_links():
    html = b"""
    <ul>
      <li>
        <span class="ecl-label--highlight">Portugal</span>
        <div class="ecl-content-item__content-block">
          University of Aveiro Posted on: 16 October 2026
          <h3 class="ecl-content-block__title">
            <a href="/jobs/473443">Software Developer for Research Project</a>
          </h3>
          <div class="ecl-content-block__description">Build Python software and data tools.</div>
          <div class="id-Work-Locations"><div class="ecl-text-standard">Aveiro, Portugal</div></div>
          <div class="id-Department"><div class="ecl-text-standard">CICECO</div></div>
        </div>
      </li>
      <li>
        <div class="ecl-content-item__content-block">
          <h3 class="ecl-content-block__title"><a href="/jobs/473444">Clinical Psychology Lecturer</a></h3>
          <div class="ecl-content-block__description">Clinical psychology and teaching.</div>
        </div>
      </li>
      <li>
        <div class="ecl-content-item__content-block">
          <h3 class="ecl-content-block__title"><a href="https://example.com/jobs/9">Java Developer</a></h3>
          <div class="ecl-content-block__description">External link must be rejected.</div>
        </div>
      </li>
    </ul>
    """
    client = FakeClient({0: html})
    jobs = asyncio.run(collect_euraxess(client))
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Software Developer for Research Project"
    assert jobs[0]["source"] == "EURAXESS"
    assert jobs[0]["external_id"] == "473443"
    assert jobs[0]["url"] == "https://euraxess.ec.europa.eu/jobs/473443"
    assert jobs[0]["country"] == "Portugal"


def test_euraxess_limits_pagination_to_three_pages():
    client = FakeClient({})
    assert asyncio.run(collect_euraxess(client)) == []
    assert len(client.calls) == 3


def test_euraxess_is_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["EURAXESS"]["enabled"] is False
    assert sources["EURAXESS"]["configuration_required"] is False
