import asyncio
from datetime import date, timedelta

from app.main import (
    WFP_API_BASE,
    _wfp_is_relevant,
    _wfp_parse_deadline,
    collect_wfp,
    source_catalog,
)


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.content = b"{}"

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeClient:
    def __init__(self, title, deadline, can_apply=True):
        self.calls = []
        self.title = title
        self.deadline = deadline
        self.can_apply = can_apply
        self.path = f"/job/Dakar-Senegal/{title.replace(' ', '-')}_JR999999"

    async def post(self, url, json, headers=None):
        self.calls.append(("POST", url))
        if json["offset"] > 0:
            return FakeResponse({"total": 1, "jobPostings": []})
        return FakeResponse({
            "total": 1,
            "jobPostings": [{
                "title": self.title,
                "externalPath": self.path,
                "locationsText": "Dakar, Senegal",
                "postedOn": "Posted today",
                "bulletFields": ["JR999999"],
            }],
        })

    async def get(self, url, headers=None):
        self.calls.append(("GET", url))
        return FakeResponse({
            "jobPostingInfo": {
                "title": self.title,
                "jobReqId": "JR999999",
                "jobDescription": (
                    "<p><b>DEADLINE FOR APPLICATIONS</b></p>"
                    + self.deadline
                    + "<p>Software systems and application development.</p>"
                ),
                "location": "Dakar, Senegal",
                "postedOn": "Posted today",
                "startDate": date.today().isoformat(),
                "endDate": (date.today() + timedelta(days=30)).isoformat(),
                "timeType": "Full time",
                "externalUrl": (
                    "https://wd3.myworkdaysite.com/recruiting/wfp/job_openings"
                    + self.path
                ),
                "canApply": self.can_apply,
            }
        })


def _future_deadline():
    return (date.today() + timedelta(days=10)).strftime("%d %B %Y")


def _past_deadline():
    return (date.today() - timedelta(days=10)).strftime("%d %B %Y")


def test_wfp_keeps_open_it_job_and_official_link():
    client = FakeClient("IT Solutions Associate", _future_deadline())
    jobs = asyncio.run(collect_wfp(client))
    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "WFP Careers"
    assert job["company"] == "World Food Programme (WFP/PAM)"
    assert job["external_id"] == "JR999999"
    assert "DEADLINE FOR APPLICATIONS" in job["description"]
    assert "Date limite" in job["description"]
    assert "wd3.myworkdaysite.com" in job["url"]


def test_wfp_excludes_expired_deadline():
    client = FakeClient("IT Solutions Associate", _past_deadline())
    assert asyncio.run(collect_wfp(client)) == []


def test_wfp_excludes_non_it_title():
    assert not _wfp_is_relevant("Partnerships Officer")
    client = FakeClient("Partnerships Officer", _future_deadline())
    assert asyncio.run(collect_wfp(client)) == []


def test_wfp_excludes_non_applicable_posting():
    client = FakeClient(
        "IT Solutions Associate", _future_deadline(), can_apply=False
    )
    assert asyncio.run(collect_wfp(client)) == []


def test_wfp_parses_deadline_before_workday_end_date():
    deadline = _wfp_parse_deadline(
        "<p>DEADLINE FOR APPLICATIONS</p>20 October 2026-23:59-GMT+03:00",
        "2026-10-21",
    )
    assert deadline == date(2026, 10, 20)


def test_wfp_is_enabled_in_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["WFP Careers"]["enabled"] is True
    assert sources["WFP Careers"]["configuration_required"] is False
