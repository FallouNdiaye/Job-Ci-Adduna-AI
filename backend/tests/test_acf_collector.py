import asyncio
from datetime import date, timedelta

from app.main import _acf_is_relevant, _acf_parse_date, collect_acf, source_catalog


BASE = "https://recrutement.actioncontrelafaim.org"


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, title="Software Engineer", deadline=None, fail=False):
        self.title = title
        self.deadline = deadline or (date.today() + timedelta(days=10)).strftime("%d %b %Y")
        self.fail = fail
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        if self.fail:
            raise RuntimeError("simulated network failure")
        if url == BASE + "/en/our-offers/":
            return FakeResponse(f"""
                <html><body>
                  <a href="/en/our-offers/2026-2630/"><span class="crd__title">{self.title}</span></a>
                  <a href="/en/our-offers/2026-2652/"><span class="crd__title">Regional Operations Manager</span></a>
                  <a href="https://evil.example/en/our-offers/2026-9999/">Software Engineer</a>
                </body></html>
            """)
        if url == BASE + "/en/our-offers/2026-2630":
            return FakeResponse(f"""
                <html><body><main>
                  <h1>{self.title}</h1>
                  <p>Location: Montreuil, France</p>
                  <p>Published 16 Oct 2026</p>
                  <p>Application deadline: {self.deadline}</p>
                  <p>Develop and maintain software applications.</p>
                  <a href="https://actioncontrelafaim-career.talent-soft.com/job/example.aspx">Apply</a>
                </main></body></html>
            """)
        raise AssertionError(f"Unexpected URL: {url}")


def test_acf_keeps_relevant_job_and_official_links():
    client = FakeClient()
    jobs = asyncio.run(collect_acf(client))
    assert len(jobs) == 1
    assert jobs[0]["source"] == "Action contre la Faim (ACF)"
    assert jobs[0]["company"] == "Action contre la Faim (ACF)"
    assert jobs[0]["url"] == BASE + "/en/our-offers/2026-2630"
    assert "talent-soft.com/job/example.aspx" in jobs[0]["description"]
    assert "date limite" in jobs[0]["description"].lower()
    assert all("evil.example" not in url for url in client.calls)


def test_acf_rejects_non_it_titles():
    assert not _acf_is_relevant("Regional Operations Manager")
    assert not _acf_is_relevant("Finance Assistant")
    assert not _acf_is_relevant("CHEFFE OU CHEF DE PROJET FINANCE SI")
    assert _acf_is_relevant("Software Engineer")
    assert _acf_is_relevant("Développeur web")


def test_acf_excludes_expired_deadlines():
    expired = (date.today() - timedelta(days=5)).strftime("%d %b %Y")
    assert asyncio.run(collect_acf(FakeClient(deadline=expired))) == []


def test_acf_handles_listing_network_failure():
    assert asyncio.run(collect_acf(FakeClient(fail=True))) == []


def test_acf_parses_explicit_dates():
    assert _acf_parse_date("Deadline: 2026-12-15") == date(2026, 12, 15)
    assert _acf_parse_date("26 Oct 2026") == date(2026, 10, 26)
    assert _acf_parse_date("15/12/2026") == date(2026, 12, 15)
    assert _acf_parse_date("No date announced") is None


def test_acf_is_enabled_in_source_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["Action contre la Faim (ACF)"]["enabled"] is True
    assert sources["Action contre la Faim (ACF)"]["configuration_required"] is False
