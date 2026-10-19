from app.main import score_job

def test_relevant_java_job_scores_higher():
    relevant = {"title":"Développeur Java Spring Boot", "description":"API REST PostgreSQL Docker", "country":"France", "location":"Paris", "skills":["Java", "Spring Boot"]}
    irrelevant = {"title":"Vendeur boutique", "description":"Accueil et caisse", "country":"Inconnu", "location":"", "skills":[]}
    assert score_job(relevant) > score_job(irrelevant)
    assert 0 <= score_job(relevant) <= 100

def test_score_explains_relevant_skills():
    from app.main import score_details
    score, reasons, missing = score_details({
        "title": "Java Spring Boot Developer",
        "description": "Build REST APIs with PostgreSQL and Docker",
        "country": "France", "location": "Remote", "skills": ["Java", "Spring Boot"]
    })
    assert score >= 70
    assert any("Java" in reason or "Spring Boot" in reason for reason in reasons)
    assert "Angular" in missing


def test_normalize_real_job_payload():
    from app.main import normalize_job
    item = normalize_job({
        "id": "job-123", "title": "Java Developer", "company_name": "Example Corp",
        "url": "https://example.com/jobs/123", "publication_date": "2026-10-10",
        "candidate_required_location": "Worldwide", "description": "Build Java and Spring Boot APIs"
    }, "Test API")
    assert item is not None
    assert item["source"] == "Test API"
    assert item["published_at"] == "2026-10-10"
    assert "Java" in item["skills"]


def test_jobicy_payload_normalizes_to_common_schema():
    from app.main import normalize_job
    item = normalize_job({
        "id": 99, "title": "Full Stack Developer", "company": "Example",
        "url": "https://example.com/careers/99", "location": "Worldwide",
        "description": "React, Java and Spring Boot", "publication_date": "2026-10-10",
        "job_type": "Full-time"
    }, "Jobicy API")
    assert item["source"] == "Jobicy API"
    assert item["url"].endswith("/99")
    assert "Java" in item["skills"]


def test_optional_collectors_are_off_by_default(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "JOBSPY_ENABLED", False)
    monkeypatch.setattr(main, "HIREHUNT_ENABLED", False)
    monkeypatch.setattr(main, "CRAWL4AI_ENABLED", False)
    monkeypatch.setattr(main, "SCRAPEGRAPHAI_ENABLED", False)
    import asyncio
    assert asyncio.run(main.collect_jobspy()) == []
    assert asyncio.run(main.collect_hirehunt()) == []
    assert asyncio.run(main.collect_crawl4ai()) == []
    assert asyncio.run(main.collect_scrapegraphai()) == []


def test_source_catalog_marks_optional_collectors_disabled_by_default(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "REMOTE_JOBS_API_URL", "")
    monkeypatch.setattr(main, "JOBSPY_ENABLED", False)
    monkeypatch.setattr(main, "HIREHUNT_ENABLED", False)
    monkeypatch.setattr(main, "CRAWL4AI_ENABLED", False)
    monkeypatch.setattr(main, "SCRAPEGRAPHAI_ENABLED", False)
    catalog = main.source_catalog()["sources"]
    by_name = {item["name"]: item for item in catalog}
    assert by_name["Arbeitnow API"]["enabled"] is True
    assert by_name["JobSpy"]["enabled"] is False
    assert by_name["Hirehunt"]["enabled"] is False
    assert by_name["Crawl4AI"]["enabled"] is False
    assert by_name["ScrapeGraphAI"]["enabled"] is False

def test_mobile_roles_are_classified_without_false_positive():
    from app.main import classify_job

    for title in (
        "Flutter Developer", "React Native Engineer", "Android Developer",
        "iOS Engineer", "Kotlin Developer", "Swift Developer",
        "Développeur d’application mobile",
    ):
        assert classify_job({"title": title, "description": ""})["role_category"] == "Mobile", title

    assert classify_job({"title": "Flutter Sales Representative", "description": ""})["role_category"] == "Autre"


def test_foreign_location_does_not_prove_international_recruitment():
    from app.main import classify_job

    local_evidence = classify_job({
        "title": "Java Developer", "country": "France",
        "description": "Build Spring Boot APIs",
    })
    assert local_evidence["international_recruitment"] is False
    assert local_evidence["relocation_supported"] is False

    explicit_evidence = classify_job({
        "title": "Java Developer", "country": "France",
        "description": "International applicants welcome. Visa sponsorship available.",
    })
    assert explicit_evidence["international_recruitment"] is True
    assert explicit_evidence["relocation_supported"] is True

def test_backend_scoring_prioritizes_java_skills():
    from app.main import score_details

    score, reasons, _ = score_details({
        "title": "Java Backend Developer",
        "description": "Java Spring Boot Spring Batch PostgreSQL Docker REST Kafka",
        "country": "France",
        "location": "Paris",
        "skills": ["Java", "Spring Boot", "Spring Batch", "PostgreSQL", "Docker"],
    })
    assert score >= 70
    assert any("pondérées selon le poste" in reason for reason in reasons)


def test_mobile_sales_title_does_not_receive_developer_role_points():
    from app.main import score_details

    sales_score, sales_reasons, _ = score_details({
        "title": "Flutter Sales Representative",
        "description": "Promote Flutter products and meet customers",
        "country": "Inconnu",
        "location": "",
        "skills": [],
    })
    developer_score = score_details({
        "title": "Flutter Developer",
        "description": "Build mobile apps with Flutter and Dart",
        "country": "France",
        "location": "Remote",
        "skills": ["Flutter", "Dart"],
    })[0]

    assert developer_score > sales_score
    assert not any("Intitulé proche du métier cible" in reason for reason in sales_reasons)
