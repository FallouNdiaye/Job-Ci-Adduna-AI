import asyncio
from app.main import (
    SENJOB_CATEGORY_URL,
    collect_senjob,
    source_catalog,
)


class FakeResponse:
    def __init__(self, content, url=None):
        self.content = content
        self.url = url

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params))
        key = url
        if params:
            key = f"{url}?Category={params['Category']}&page={params['page']}"
        if key in self.responses:
            return self.responses[key]
        if url in self.responses:
            return self.responses[url]
        raise AssertionError(f"URL inattendue : {key}")


def test_collects_it_offer_when_jsonld_is_malformed():
    category = (
        '<html><a href="/sn/jobseekers/'
        'developpeur-full-stack_e_164192.html">Offre</a></html>'
    ).encode()
    detail_url = (
        "https://senjob.com/sn/jobseekers/"
        "developpeur-full-stack_e_164192.html"
    )
    detail = """<html><head>
    <script type="application/ld+json">{"@type":"JobPosting","description":"broken
    JSON"}</script>
    <meta property="og:title" content="Développeur Full Stack PHP">
    <meta property="og:description" content="Développement logiciel PHP, JavaScript et MySQL à Dakar.">
    </head><body></body></html>""".encode("utf-8")
    client = FakeClient({
        f"{SENJOB_CATEGORY_URL}?Category=8&page=1": FakeResponse(category),
        f"{SENJOB_CATEGORY_URL}?Category=8&page=2": FakeResponse(b"<html></html>"),
        detail_url: FakeResponse(detail, url=detail_url),
    })

    jobs = asyncio.run(collect_senjob(client))

    assert len(jobs) == 1
    assert jobs[0]["source"] == "Senjob"
    assert "Full Stack" in jobs[0]["title"]
    assert jobs[0]["country"] == "Sénégal"
    assert jobs[0]["external_id"] == "164192"
    assert "PHP" in jobs[0]["description"]


def test_rejects_non_it_and_forbidden_cv_urls():
    category = b"""<html>
    <a href="/sn/jobseekers/comptable_e_164193.html">Comptable</a>
    <a href="/sn/cvs/private-profile.html">CV</a>
    <a href="https://example.com/sn/jobseekers/java_e_164194.html">External</a>
    </html>"""
    comptable_url = (
        "https://senjob.com/sn/jobseekers/comptable_e_164193.html"
    )
    client = FakeClient({
        f"{SENJOB_CATEGORY_URL}?Category=8&page=1": FakeResponse(category),
        f"{SENJOB_CATEGORY_URL}?Category=8&page=2": FakeResponse(b"<html></html>"),
        comptable_url: FakeResponse(
            b'<html><head><meta property="og:title" content="Comptable">'
            b'<meta property="og:description" content="Comptabilite et finance.">'
            b'</head></html>',
            url=comptable_url,
        ),
    })

    assert asyncio.run(collect_senjob(client)) == []
    assert all("/cvs/" not in url for url, _ in client.calls)
    assert all("example.com" not in url for url, _ in client.calls)


def test_rejects_external_redirect_for_detail():
    category = b'<a href="/sn/jobseekers/java-developer_e_164195.html">IT</a>'
    detail_url = (
        "https://senjob.com/sn/jobseekers/java-developer_e_164195.html"
    )
    client = FakeClient({
        f"{SENJOB_CATEGORY_URL}?Category=8&page=1": FakeResponse(category),
        f"{SENJOB_CATEGORY_URL}?Category=8&page=2": FakeResponse(b"<html></html>"),
        detail_url: FakeResponse(
            b'<html><head><meta property="og:title" content="Java Developer">'
            b'<meta property="og:description" content="Java software developer.">'
            b'</head></html>',
            url="https://example.com/redirected",
        ),
    })

    assert asyncio.run(collect_senjob(client)) == []


def test_senjob_is_registered_in_catalog():
    sources = {item["name"]: item for item in source_catalog()["sources"]}
    assert sources["Senjob"]["enabled"] is True
    assert sources["Senjob"]["configuration_required"] is False
