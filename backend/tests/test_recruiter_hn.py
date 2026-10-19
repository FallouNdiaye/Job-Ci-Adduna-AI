from app.recruiter_hn import classify_link, extract_individual_offers


def link(url, kind="job_application", text=""):
    return {"url": url, "kind": kind, "text": text}


def test_ashby_careers_page_is_not_an_individual_offer():
    assert classify_link({
        "url": "https://jobs.ashbyhq.com/checkly",
        "text": "",
    }) == "careers_page"


def test_ashby_job_url_is_individual_offer():
    url = (
        "https://jobs.ashbyhq.com/checkly/"
        "12345678-1234-1234-1234-123456789abc"
    )
    assert classify_link({"url": url, "text": ""}) == "job_application"


def test_general_careers_page_is_not_an_individual_offer():
    assert classify_link({
        "url": "https://example.org/careers",
        "text": "Careers",
    }) == "careers_page"


def test_unknown_url_is_not_confirmed_as_an_offer():
    url = "https://example.org/company"
    assert classify_link({"url": url, "text": ""}) == "company_or_other"

    offers = extract_individual_offers([link(url, kind="company_or_other")])
    assert offers == []


def test_pagnos_public_page_metadata_is_used():
    url = (
        "https://germantechjobs.de/jobs/"
        "PAGNOS-GmbH-Cloud-AI-Engineer--AWS-Serverless-mwd"
    )
    offers = extract_individual_offers([link(url)])

    assert len(offers) == 1
    assert offers[0]["title_candidate"] == (
        "Cloud AI Engineer – AWS Serverless (m/w/d)"
    )
    assert offers[0]["employer_candidate"] == "PAGNOS GmbH"
    assert offers[0]["title_status"] == (
        "confirmed_from_public_page_metadata"
    )


def test_opensanctions_public_page_metadata_is_used():
    url = (
        "https://www.opensanctions.org/docs/company/jobs/"
        "2026-09-product-engineer/"
    )
    offers = extract_individual_offers([link(url)])

    assert len(offers) == 1
    assert offers[0]["title_candidate"] == (
        "Freelance: Product Engineer (d/w/m)"
    )
    assert offers[0]["employer_candidate"] == "OpenSanctions"
    assert offers[0]["title_status"] == (
        "confirmed_from_public_page_metadata"
    )


def test_ashby_offer_is_confirmed_from_public_api_data():
    job_id = "2efae53b-817c-43e7-9da3-72694813f608"
    url = f"https://jobs.ashbyhq.com/thundercompute/{job_id}"
    jobs = {
        f"thundercompute:{job_id}": {
            "id": job_id,
            "title": "Software Engineer (C++ Systems)",
            "jobUrl": url,
            "_employer_candidate": "Thunder Compute",
        }
    }

    offers = extract_individual_offers([link(url)], jobs)

    assert len(offers) == 1
    assert offers[0]["title_candidate"] == "Software Engineer (C++ Systems)"
    assert offers[0]["employer_candidate"] == "Thunder Compute"
    assert offers[0]["title_status"] == "confirmed_from_public_api"


def test_unknown_ashby_job_id_is_not_marked_confirmed():
    job_id = "12345678-1234-1234-1234-123456789abc"
    url = f"https://jobs.ashbyhq.com/unknownco/{job_id}"

    offers = extract_individual_offers([link(url)], {})

    assert len(offers) == 1
    assert offers[0]["title_candidate"] is None
    assert offers[0]["title_status"] == "needs_page_fetch"



def test_ashby_unknown_jobs_get_title_from_public_comment():
    from app.recruiter_hn import parse_comment

    html = """
    Thunder Compute is hiring. Open roles:
    - Software Engineer, C++ Systems ($215K-$325K + equity):
    <a href="https://jobs.ashbyhq.com/thundercompute/2efae53b-817c-43e7-9da3-72694813f608">apply</a>
    - Software Engineer, Infrastructure ($150K-$250K + equity). Go, Kubernetes:
    <a href="https://jobs.ashbyhq.com/thundercompute/927a922b-c607-4b0e-a6f2-451571a537f4">apply</a>
    - Business Operations Lead ($150K-$225K + equity):
    <a href="https://jobs.ashbyhq.com/thundercompute/4f28e418-b77b-446e-a30e-6b5bed36c093">apply</a>
    """
    record = parse_comment(
        {"id": "test-thunder", "text": html},
        {"title": "Who is hiring", "objectID": "test-thread"},
        {},
    )

    assert record is not None
    offers = {offer["url"].rsplit("/", 1)[-1]: offer
              for offer in record["individual_offers"]}

    assert offers["927a922b-c607-4b0e-a6f2-451571a537f4"]["title_candidate"] == (
        "Software Engineer, Infrastructure"
    )
    assert offers["4f28e418-b77b-446e-a30e-6b5bed36c093"]["title_candidate"] == (
        "Business Operations Lead"
    )
    for offer in offers.values():
        assert offer["title_status"] == "candidate_from_public_comment"
        assert offer["title_source"] == "hacker_news_comment_text"


def test_smarkets_frontend_title_is_extracted_from_comment():
    from app.recruiter_hn import parse_comment

    job_id = "d24b8384-0894-46b3-834c-eeeba59274fd"
    record = parse_comment(
        {
            "id": "test-smarkets",
            "text": (
                "Smarkets is hiring. We are currently looking for: "
                "Senior DevSecOps Engineer - "
                '<a href="https://jobs.ashbyhq.com/smarkets/'
                '97b041b6-489c-4148-8e2c-2d5a14264fcb">apply</a> '
                "Front End Engineer - "
                f'<a href="https://jobs.ashbyhq.com/smarkets/{job_id}">apply</a>'
            ),
        },
        {"title": "Who is hiring", "objectID": "test-thread"},
        {},
    )

    assert record is not None
    offer = next(o for o in record["individual_offers"] if o["url"].endswith(job_id))
    assert offer["title_candidate"] == "Front End Engineer"
    assert offer["title_status"] == "candidate_from_public_comment"


def test_public_api_title_takes_priority_over_comment_candidate():
    from app.recruiter_hn import parse_comment

    job_id = "2efae53b-817c-43e7-9da3-72694813f608"
    url = f"https://jobs.ashbyhq.com/thundercompute/{job_id}"
    record = parse_comment(
        {
            "id": "test-priority",
            "text": (
                "Thunder Compute hiring. Open roles: "
                "Software Engineer, C++ Systems ($215K): "
                f'<a href="{url}">apply</a>'
            ),
        },
        {"title": "Who is hiring", "objectID": "test-thread"},
        {
            f"thundercompute:{job_id}": {
                "id": job_id,
                "title": "API-confirmed title",
                "jobUrl": url,
                "_employer_candidate": "Thunder Compute",
            }
        },
    )

    assert record is not None
    offer = record["individual_offers"][0]
    assert offer["title_candidate"] == "API-confirmed title"
    assert offer["title_status"] == "confirmed_from_public_api"

def test_non_job_link_is_ignored_by_offer_extractor():
    offers = extract_individual_offers([
        link("https://example.org/careers", kind="careers_page"),
        link("https://example.org/company", kind="company_or_other"),
    ])
    assert offers == []


def test_careers_page_does_not_become_an_individual_job_offer():
    from app.recruiter_hn import parse_comment

    record = parse_comment(
        {
            "id": "test-shepherd-careers",
            "text": (
                "Shepherd (Series B) | ONSITE | San Francisco, CA "
                "& New York City, NY "
                "We are hiring a Software Engineer. "
                "We are building an AI-native insurance platform. "
                '<a href="https://shepherdinsurance.com/careers">'
                "Careers</a>"
            ),
        },
        {"title": "Who is hiring", "objectID": "test-thread"},
        {},
    )

    assert record is not None
    assert record["company_candidate"] == "Shepherd (Series B)"
    assert record["title_candidate"] == "Intitulé à vérifier"
    assert record["individual_offers"] == []
    assert any(
        link["kind"] == "careers_page"
        for link in record["application_links"]
    )


def test_classify_location_distinguishes_visa_sponsorship():
    from app.recruiter_hn import classify_location

    positive = classify_location(
        "We offer visa sponsorship for qualified international candidates."
    )
    negative = classify_location(
        "We do not offer visa sponsorship."
    )
    unknown = classify_location(
        "We are hiring software engineers."
    )

    assert any("visa" in item.lower() or "parrainage" in item.lower()
               for item in positive)
    assert any("visa" in item.lower() or "autorisation" in item.lower()
               for item in negative)
    assert not any("Parrainage de visa mentionné" == item for item in negative)
    assert not any("Parrainage de visa mentionné" == item for item in unknown)


def test_classify_location_detects_international_remote_and_relocation():
    from app.recruiter_hn import classify_location

    result = classify_location(
        "Remote worldwide. Relocation assistance available."
    )

    assert any("internationale" in item.lower() for item in result)
    assert any("mobilité" in item.lower() for item in result)


def test_classify_location_does_not_infer_senegal_eligibility():
    from app.recruiter_hn import classify_location

    result = classify_location("Remote worldwide")

    # Le collecteur ne doit pas déduire à lui seul un statut d'éligibilité.
    assert isinstance(result, list)
    assert any("internationale" in item.lower() for item in result)


def test_classify_location_distinguishes_visa_sponsorship():
    from app.recruiter_hn import classify_location

    positive = classify_location(
        "We offer visa sponsorship for qualified international candidates."
    )
    negative = classify_location(
        "We do not offer visa sponsorship."
    )
    unknown = classify_location(
        "We are hiring software engineers."
    )

    assert any("visa" in item.lower() or "parrainage" in item.lower()
               for item in positive)
    assert any("visa" in item.lower() or "autorisation" in item.lower()
               for item in negative)
    assert not any("Parrainage de visa mentionné" == item for item in negative)
    assert not any("Parrainage de visa mentionné" == item for item in unknown)


def test_classify_location_detects_international_remote_and_relocation():
    from app.recruiter_hn import classify_location

    result = classify_location(
        "Remote worldwide. Relocation assistance available."
    )

    assert any("internationale" in item.lower() for item in result)
    assert any("mobilité" in item.lower() for item in result)


def test_classify_location_does_not_infer_senegal_eligibility():
    from app.recruiter_hn import classify_location

    result = classify_location("Remote worldwide")

    # Le collecteur ne doit pas déduire à lui seul un statut d'éligibilité.
    assert isinstance(result, list)
    assert any("internationale" in item.lower() for item in result)


def test_extract_mobility_statuses_distinguishes_visa_polarity():
    from app.recruiter_hn import extract_mobility_statuses

    assert extract_mobility_statuses(
        "We offer visa sponsorship."
    )["visa_sponsorship_status"] == "confirmed"

    assert extract_mobility_statuses(
        "We do not offer visa sponsorship."
    )["visa_sponsorship_status"] == "not_offered"

    assert extract_mobility_statuses(
        "Visa sponsorship may be discussed."
    )["visa_sponsorship_status"] == "mentioned"

    assert extract_mobility_statuses(
        "We are hiring software engineers."
    )["visa_sponsorship_status"] == "unknown"


def test_extract_mobility_statuses_distinguishes_relocation():
    from app.recruiter_hn import extract_mobility_statuses

    assert extract_mobility_statuses(
        "Relocation assistance available."
    )["relocation_support_status"] == "confirmed"

    assert extract_mobility_statuses(
        "We do not offer relocation assistance."
    )["relocation_support_status"] == "not_offered"

    assert extract_mobility_statuses(
        "Relocation assistance may be discussed."
    )["relocation_support_status"] == "mentioned"


def test_extract_mobility_statuses_does_not_infer_senegal_from_worldwide():
    from app.recruiter_hn import extract_mobility_statuses

    assert extract_mobility_statuses(
        "Remote worldwide. Any country."
    )["senegal_eligibility_status"] == "unknown"

    assert extract_mobility_statuses(
        "We hire employees based in Senegal."
    )["senegal_eligibility_status"] == "eligible"

    assert extract_mobility_statuses(
        "We cannot hire employees in Senegal."
    )["senegal_eligibility_status"] == "ineligible"
