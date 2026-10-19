from app.recruiter_official import (
    PageParser,
    _same_host,
    collect_official_jobpostings,
    extract_jobpostings,
)


def test_extracts_jobposting_from_nested_graph():
    data = [{
        "@graph": [{
            "@type": "JobPosting",
            "title": "Full Stack Engineer",
            "url": "/jobs/123/full-stack",
            "hiringOrganization": {"name": "Example BV"},
            "jobLocation": {
                "address": {
                    "addressLocality": "Amsterdam",
                    "addressCountry": "NL",
                }
            },
            "datePosted": "2026-10-15",
            "skills": ["Java", "Spring Boot"],
        }]
    }]

    offers = extract_jobpostings(
        data,
        "https://www.crossover.com/jobs/123/full-stack",
        "Crossover",
    )

    assert len(offers) == 1
    assert offers[0]["title"] == "Full Stack Engineer"
    assert offers[0]["url"] == "https://www.crossover.com/jobs/123/full-stack"
    assert offers[0]["company"] == "Example BV"
    assert "Amsterdam" in offers[0]["location"]
    assert offers[0]["skills"] == ["Java", "Spring Boot"]
    assert offers[0]["visa_sponsorship_status"] == "unknown"
    assert offers[0]["senegal_eligibility_status"] == "unknown"


def test_rejects_jobposting_with_external_url():
    data = [{
        "@type": "JobPosting",
        "title": "Suspicious external offer",
        "url": "https://evil.example/jobs/123",
    }]

    assert extract_jobpostings(
        data, "https://www.crossover.com/jobs/123", "Crossover"
    ) == []


def test_same_host_requires_https_and_same_hostname():
    assert _same_host(
        "https://www.crossover.com/jobs/1",
        "https://www.crossover.com/",
    )
    assert not _same_host(
        "http://www.crossover.com/jobs/1",
        "https://www.crossover.com/",
    )
    assert not _same_host(
        "https://evil.example/jobs/1",
        "https://www.crossover.com/",
    )


def test_page_parser_reads_jsonld_jobposting():
    html = """
    <html><head>
      <script type="application/ld+json">
      {"@type":"JobPosting","title":"Backend Engineer",
       "url":"https://example.org/jobs/1"}
      </script>
    </head><body><a href="/jobs/1">Offer</a></body></html>
    """

    parser = PageParser()
    parser.feed(html)

    assert len(parser.jsonld) == 1
    assert parser.jsonld[0]["title"] == "Backend Engineer"
    assert "/jobs/1" in parser.links


class FakeResponse:
    def __init__(self, url, status_code=200, text=""):
        self.url = url
        self.status_code = status_code
        self.text = text
        self.content = text.encode()
        self.headers = {"content-type": "text/plain"}


class FakeClient:
    def __init__(self):
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        if url.endswith("/robots.txt"):
            return FakeResponse(
                url,
                text="User-agent: *\nDisallow: /\n",
            )
        raise AssertionError(f"URL interdite ou inattendue : {url}")


def test_does_not_fetch_pages_disallowed_by_robots_txt():
    client = FakeClient()
    sources = [{
        "name": "Test recruiter",
        "website": "https://example.org/",
        "seed": "https://example.org/jobs",
        "country": "Netherlands",
    }]

    result = collect_official_jobpostings(sources=sources, client=client)

    assert result["offers"] == []
    assert client.requested == ["https://example.org/robots.txt"]
    assert result["status"] == "success"


def test_official_sync_preserves_existing_mobility_data(tmp_path, monkeypatch):
    from app import recruiters
    from app import recruiter_official
    from app.recruiter_sync import sync_official_recruiters

    monkeypatch.setattr(recruiters, "DB_PATH", tmp_path / "test.db")
    recruiters.init_recruiters_db()

    with recruiters.connect() as db:
        cursor = db.execute(
            """
            INSERT INTO recruiters (
                name, website_url, country, source_url, source_name,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Crossover", "https://www.crossover.com/",
                "International / Remote", "https://www.crossover.com/",
                "Site officiel Crossover", "2026-01-01", "2026-01-01",
            ),
        )
        recruiter_id = cursor.lastrowid

        db.execute(
            """
            INSERT INTO recruiter_offers (
                recruiter_id, title, company, location, country,
                work_mode, contract_type, description, url, source_url,
                deadline, skills, collected_at, last_checked_at,
                visa_sponsorship_status, relocation_support_status,
                senegal_eligibility_status, eligibility_notes, evidence_url,
                verification_status, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recruiter_id, "Full Stack Engineer", "Crossover",
                "Amsterdam", "Netherlands", "remote", "Full-time",
                "Existing description", "https://www.crossover.com/jobs/123",
                "https://www.crossover.com/jobs/123", "2026-12-31", '["Java"]',
                "2026-01-01", "2026-01-01", "confirmed", "confirmed",
                "eligible", "Visa and relocation confirmed in prior review",
                "https://evidence.example/offer", "verified", "2026-01-01",
            ),
        )
        db.commit()

    monkeypatch.setattr(
        recruiter_official,
        "collect_official_jobpostings",
        lambda: {
            "status": "success",
            "offers": [{
                "recruiter": {
                    "name": "Crossover",
                    "website": "https://www.crossover.com/",
                    "country": "International / Remote",
                },
                "title": "Full Stack Engineer",
                "url": "https://www.crossover.com/jobs/123",
                "company": "Crossover",
                "location": "",
                "description": "",
                "source_url": "https://www.crossover.com/jobs/123",
                "published_at": "",
                "deadline": "",
                "skills": [],
                "verification_status": "verified",
                "visa_sponsorship_status": "unknown",
                "relocation_support_status": "unknown",
                "senegal_eligibility_status": "unknown",
                "evidence_url": "https://www.crossover.com/jobs/123",
            }],
            "errors": [],
        },
    )

    result = sync_official_recruiters()
    assert result["status"] == "success"
    assert result["inserted"] == 0
    assert result["updated"] == 1

    with recruiters.connect() as db:
        row = db.execute(
            "SELECT * FROM recruiter_offers WHERE url = ?",
            ("https://www.crossover.com/jobs/123",),
        ).fetchone()

    assert row["visa_sponsorship_status"] == "confirmed"
    assert row["relocation_support_status"] == "confirmed"
    assert row["senegal_eligibility_status"] == "eligible"
    assert row["eligibility_notes"] == "Visa and relocation confirmed in prior review"
    assert row["deadline"] == "2026-12-31"
    assert row["location"] == "Amsterdam"
    assert row["verification_status"] == "verified"


def test_official_sync_inserts_new_offer_into_temporary_database(
    tmp_path, monkeypatch
):
    from app import recruiters
    from app import recruiter_official
    from app.recruiter_sync import sync_official_recruiters

    monkeypatch.setattr(recruiters, "DB_PATH", tmp_path / "new-test.db")
    recruiters.init_recruiters_db()

    monkeypatch.setattr(
        recruiter_official,
        "collect_official_jobpostings",
        lambda: {
            "status": "success",
            "offers": [{
                "recruiter": {
                    "name": "ITSync",
                    "website": "https://www.itsync.nl/",
                    "country": "Pays-Bas",
                },
                "title": "Backend Engineer",
                "url": "https://www.itsync.nl/jobs/backend-engineer-test",
                "company": "ITSync",
                "location": "Netherlands",
                "description": "Java and Spring Boot",
                "source_url": "https://www.itsync.nl/jobs",
                "published_at": "2026-10-15",
                "deadline": "2026-12-01",
                "skills": ["Java", "Spring Boot"],
                "employment_type": "FULL_TIME",
                "verification_status": "verified",
                "visa_sponsorship_status": "unknown",
                "relocation_support_status": "unknown",
                "senegal_eligibility_status": "unknown",
                "evidence_url": "https://www.itsync.nl/jobs/backend-engineer-test",
            }],
            "errors": [],
        },
    )

    result = sync_official_recruiters()
    assert result["status"] == "success"
    assert result["offers_seen"] == 1
    assert result["inserted"] == 1

    with recruiters.connect() as db:
        row = db.execute(
            "SELECT * FROM recruiter_offers WHERE url = ?",
            ("https://www.itsync.nl/jobs/backend-engineer-test",),
        ).fetchone()
        recruiter = db.execute(
            "SELECT * FROM recruiters WHERE name = ?", ("ITSync",)
        ).fetchone()

    assert row is not None
    assert row["title"] == "Backend Engineer"
    assert row["country"] == "Pays-Bas"
    assert row["deadline"] == "2026-12-01"
    assert row["visa_sponsorship_status"] == "unknown"
    assert recruiter is not None


def test_official_sync_creates_recruiter_without_any_job_offer(
    tmp_path, monkeypatch
):
    from app import recruiters, recruiter_official
    from app.recruiter_sync import sync_official_recruiters

    monkeypatch.setattr(recruiters, "DB_PATH", tmp_path / "profiles-only.db")
    recruiters.init_recruiters_db()

    monkeypatch.setattr(
        recruiter_official,
        "collect_official_jobpostings",
        lambda: {
            "status": "success",
            "offers": [],
            "errors": [],
            "pages_discovered": 2,
            "recruiters": [{
                "name": "Cabinet Exemple",
                "website": "https://example.org/",
                "country": "Pays-Bas",
                "specialties": ["Java", "Recrutement IT"],
                "contact_email": "jobs@example.org",
                "contact_phone": "+31 20 123 4567",
                "linkedin_url": "https://www.linkedin.com/company/example/",
                "contact_url": "https://example.org/contact",
                "source_url": "https://example.org/",
            }],
        },
    )

    result = sync_official_recruiters()

    assert result["status"] == "success"
    with recruiters.connect() as db:
        row = db.execute(
            "SELECT * FROM recruiters WHERE name = ?",
            ("Cabinet Exemple",),
        ).fetchone()

    assert row is not None
    assert row["website_url"] == "https://example.org/"
    assert row["country"] == "Pays-Bas"
    assert row["contact_email"] == "jobs@example.org"
    assert row["contact_phone"] == "+31 20 123 4567"
    assert row["linkedin_url"] == "https://www.linkedin.com/company/example/"
    assert row["contact_url"] == "https://example.org/contact"


def test_official_sync_never_overwrites_existing_contact_with_empty_values(
    tmp_path, monkeypatch
):
    from app import recruiters, recruiter_official
    from app.recruiter_sync import sync_official_recruiters

    monkeypatch.setattr(recruiters, "DB_PATH", tmp_path / "preserve-contacts.db")
    recruiters.init_recruiters_db()

    with recruiters.connect() as db:
        db.execute(
            """
            INSERT INTO recruiters (
                name, website_url, country, contact_email, contact_phone,
                linkedin_url, contact_url, source_url, source_name,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Cabinet Exemple", "https://example.org/", "Pays-Bas",
                "existing@example.org", "+31 20 000 0000",
                "https://www.linkedin.com/company/example/",
                "https://example.org/contact", "https://example.org/",
                "Site officiel Cabinet Exemple",
                "2026-01-01", "2026-01-01",
            ),
        )
        db.commit()

    monkeypatch.setattr(
        recruiter_official,
        "collect_official_jobpostings",
        lambda: {
            "status": "success",
            "offers": [],
            "errors": [],
            "recruiters": [{
                "name": "Cabinet Exemple",
                "website": "https://example.org/",
                "country": "",
                "specialties": [],
                "contact_email": "",
                "contact_phone": "",
                "linkedin_url": "",
                "contact_url": "",
                "source_url": "https://example.org/",
            }],
        },
    )

    sync_official_recruiters()

    with recruiters.connect() as db:
        row = db.execute(
            "SELECT * FROM recruiters WHERE name = ?",
            ("Cabinet Exemple",),
        ).fetchone()

    assert row["contact_email"] == "existing@example.org"
    assert row["contact_phone"] == "+31 20 000 0000"
    assert row["linkedin_url"] == "https://www.linkedin.com/company/example/"
    assert row["contact_url"] == "https://example.org/contact"


def test_extracts_public_recruiter_contacts_from_official_page():
    from app.recruiter_official import extract_recruiter_profile

    html = """
    <html><body>
      <h1>Example Technology Recruitment</h1>
      <p>We recruit Java and software engineering specialists.</p>
      <a href="mailto:jobs@example.org">Contact recruitment</a>
      <a href="tel:+31201234567">Call our team</a>
      <a href="https://www.linkedin.com/company/example-tech/">LinkedIn</a>
      <a href="/contact-us">Contact us</a>
    </body></html>
    """
    parser = PageParser()
    parser.feed(html)

    profile = extract_recruiter_profile(
        {
            "name": "Example Recruitment",
            "website": "https://example.org/",
            "seed": "https://example.org/careers",
            "country": "Pays-Bas",
        },
        "https://example.org/careers",
        parser,
    )

    assert profile["name"] == "Example Recruitment"
    assert profile["contact_email"] == "jobs@example.org"
    assert profile["contact_phone"] == "+31201234567"
    assert profile["linkedin_url"] == "https://www.linkedin.com/company/example-tech/"
    assert profile["contact_url"] == "https://example.org/contact-us"
    assert "Java" in profile["specialties"]


def test_official_collector_returns_profile_without_job_postings():
    class AllowedFakeClient:
        def __init__(self):
            self.requested = []

        def get(self, url, **kwargs):
            self.requested.append(url)
            if url.endswith("/robots.txt"):
                return FakeResponse(url, text="User-agent: *\nAllow: /\n")
            if url.endswith("/sitemap.xml") or url.endswith("/sitemap_index.xml"):
                return FakeResponse(url, status_code=404, text="")
            if url == "https://example.org/careers":
                return FakeResponse(
                    url,
                    text="""
                    <html><body>
                      <h1>Example Recruitment</h1>
                      <a href="mailto:jobs@example.org">Email</a>
                      <a href="/contact">Contact</a>
                    </body></html>
                    """,
                )
            raise AssertionError(f"Requête inattendue : {url}")

    client = AllowedFakeClient()
    result = collect_official_jobpostings(
        sources=[{
            "name": "Example Recruitment",
            "website": "https://example.org/",
            "seed": "https://example.org/careers",
            "country": "Pays-Bas",
        }],
        client=client,
    )

    assert result["offers"] == []
    assert len(result["recruiters"]) == 1
    assert result["recruiters"][0]["name"] == "Example Recruitment"
    assert result["recruiters"][0]["contact_email"] == "jobs@example.org"
