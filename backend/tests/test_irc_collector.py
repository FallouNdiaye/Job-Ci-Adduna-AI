import asyncio
from datetime import date, timedelta

from app.main import (
    IRC_API_BASE,
    _irc_is_relevant,
    _irc_parse_deadline,
    collect_irc,
    source_catalog,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, title="Software Engineer", can_apply=True, description="<p>Build APIs.</p>"):
        self.title = title
        self.can_apply = can_apply
        self.description = description
        self.calls = []

    async def post(self, url, json, headers=None):
        self.calls.append(("POST", url, json["offset"], json["searchText"]))
        if json["offset"] > 0:
            return FakeResponse({"total": 1, "jobPostings": []})
        if json["searchText"] != "software":
            return FakeResponse({"total": 0, "jobPostings": []})
        return FakeResponse({
            "total": 1,
            "jobPostings": [{
                "title": self.title,
                "externalPath": "/job/Nairobi-Kenya/Software-Engineer_JR00005527",
                "locationsText": "Nairobi, Kenya",
                "postedOn": "Posted Yesterday",
            }],
        })

    async def get(self, url, headers=None):
        self.calls.append(("GET", url))
        return FakeResponse({
            "title": self.title,
            "jobReqId": "JR00005527",
            "jobDescription": self.description,
            "location": "Nairobi, Kenya",
            "postedOn": "Posted Yesterday",
            "startDate": date.today().isoformat(),
            "timeType": "Full time",
            "canApply": self.can_apply,
            "externalUrl": (
                "https://theirc.wd1.myworkdayjobs.com/External_Careers/job/"
                "Nairobi-Kenya/Software-Engineer_JR00005527"
            ),
        })


def test_irc_keeps_relevant_job_with_official_url_and_unknown_deadline():
    client = FakeClient()
    jobs = asyncio.run(collect_irc(client))
    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "IRC Careers"
    assert job["company"] == "International Rescue Committee (IRC)"
    assert job["external_id"] == "JR00005527"
    assert job["url"].startswith("https://theirc.wd1.myworkdayjobs.com/")
    assert "date limite : non confirmée" in job["description"].lower()
    assert len([c for c in client.calls if c[0] == "GET"]) == 1


def test_irc_excludes_non_it_titles():
    assert not _irc_is_relevant("Finance Assistant")
    assert asyncio.run(collect_irc(FakeClient(title="Finance Assistant"))) == []


def test_irc_excludes_closed_posting():
    assert asyncio.run(collect_irc(FakeClient(can_apply=False))) == []


def test_irc_excludes_explicitly_expired_deadline():
    expired = (date.today() - timedelta(days=5)).strftime("%d %B %Y")
    description = f"<p>Application deadline: {expired}</p><p>Software development</p>"
    assert asyncio.run(collect_irc(FakeClient(description=description))) == []


def test_irc_parses_explicit_deadline_but_does_not_invent_one():
    assert _irc_parse_deadline("<p>Closing Date: 2026-12-15</p>") == date(2026, 12, 15)
    assert _irc_parse_deadline("<p>Applications are welcome.</p>") is None


def test_irc_is_enabled_in_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["IRC Careers"]["enabled"] is True
    assert sources["IRC Careers"]["configuration_required"] is False
