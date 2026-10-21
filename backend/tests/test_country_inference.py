from app.main import infer_country, normalize_job


def test_recognizes_australia_and_major_cities():
    for location in (
        "Australia",
        "Australian Capital Territory",
        "Sydney, NSW",
        "Melbourne, VIC",
        "Brisbane, Queensland",
        "Perth, WA",
        "Adelaide, Australia",
        "Canberra",
        "Hobart",
        "Darwin",
        "Gold Coast",
        "Newcastle, Australia",
        "Software Engineer, AU",
    ):
        assert infer_country(location) == "Australie", location


def test_keeps_existing_country_classification():
    assert infer_country("Dakar, Senegal") == "Sénégal"
    assert infer_country("Paris, France") == "France"
    assert infer_country("Toronto, Canada") == "Canada"
    assert infer_country("Quebec, Canada") == "Québec"
    assert infer_country("Casablanca, Maroc") == "Maroc"
    assert infer_country("Luxembourg") == "Luxembourg"


def test_keeps_remote_classification_when_no_country_is_given():
    assert infer_country("Remote - Worldwide") == "Remote"


def test_normalized_australian_job_keeps_original_job_data():
    job = normalize_job(
        {
            "title": "Full Stack Developer",
            "company": "Example Australia Pty Ltd",
            "location": "Sydney, Australia",
            "url": "https://example.test/careers/full-stack-developer",
            "description": "Java, Spring Boot and React",
            "publication_date": "2026-10-20",
        },
        "Test",
    )

    assert job is not None
    assert job["country"] == "Australie"
    assert job["title"] == "Full Stack Developer"
    assert job["company"] == "Example Australia Pty Ltd"
    assert job["published_at"] == "2026-10-20"
    assert job["content_hash"]

def test_melbourne_florida_is_not_classified_as_australia():
    assert infer_country("Melbourne, FL, US") != "Australie"


def test_unknown_saved_country_is_inferred_in_api_response():
    from app.main import row_to_job

    job = {
        "country": "Non précisé",
        "location": "Sydney, Australia",
        "skills": "",
        "match_reasons": "[]",
        "missing_skills": "[]",
    }
    result = row_to_job(job)
    assert result["country"] == "Australie"


def test_existing_country_is_preserved_in_api_response():
    from app.main import row_to_job

    job = {
        "country": "France",
        "location": "Australia; France; Canada",
        "skills": "",
        "match_reasons": "[]",
        "missing_skills": "[]",
    }
    result = row_to_job(job)
    assert result["country"] == "France"
