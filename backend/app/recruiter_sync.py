"""Synchronisation Hacker News vers la base dédiée au module Recruteurs."""
from datetime import datetime, timezone
from urllib.parse import urlparse

from app import recruiters
from app.recruiter_hn import collect_hiring_records


SOURCE = "hackernews_who_is_hiring"
SOURCE_NAME = "Hacker News Who is Hiring"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _valid_http_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _clean(value, limit=2000):
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def sync_hackernews_recruiters(limit=30, thread_limit=3):
    """Collecte puis enregistre les résultats dans les tables Recruteurs."""
    recruiters.init_recruiters_db()
    started_at = _now()

    with recruiters.connect() as db:
        cursor = db.execute(
            """
            INSERT INTO recruiter_sync_runs (source, started_at, status)
            VALUES (?, ?, 'started')
            """,
            (SOURCE, started_at),
        )
        run_id = cursor.lastrowid
        db.commit()

    inserted = 0
    updated = 0

    try:
        result = collect_hiring_records(
            limit=max(1, min(int(limit), 300)),
            thread_limit=max(1, min(int(thread_limit), 12)),
        )
        posts = result.get("posts", [])

        with recruiters.connect() as db:
            for post in posts:
                company = _clean(post.get("company_candidate"), 200)
                comment_url = _clean(post.get("comment_url"), 2000)

                if len(company) < 2 or not _valid_http_url(comment_url):
                    continue

                skills = post.get("skills", [])
                if not isinstance(skills, list):
                    skills = []
                skills = [
                    _clean(skill, 80)
                    for skill in skills
                    if isinstance(skill, str) and _clean(skill, 80)
                ]

                specialties_json = recruiters.json.dumps(
                    skills, ensure_ascii=False
                )
                notes = _clean(post.get("text_preview"), 500)

                existing = db.execute(
                    """
                    SELECT id, notes FROM recruiters
                    WHERE name = ? AND source_name = ?
                    ORDER BY id LIMIT 1
                    """,
                    (company, SOURCE_NAME),
                ).fetchone()

                if existing:
                    recruiter_id = existing["id"]
                    db.execute(
                        """
                        UPDATE recruiters
                        SET specialties = ?,
                            notes = CASE WHEN notes = '' THEN ? ELSE notes END,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            specialties_json,
                            notes,
                            _now(),
                            recruiter_id,
                        ),
                    )
                    updated += 1
                else:
                    cursor = db.execute(
                        """
                        INSERT INTO recruiters (
                            name, specialties, source_url, source_name,
                            notes, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            company,
                            specialties_json,
                            comment_url,
                            SOURCE_NAME,
                            notes,
                            _now(),
                            _now(),
                        ),
                    )
                    recruiter_id = cursor.lastrowid
                    inserted += 1

                for offer in post.get("individual_offers", []):
                    url = _clean(offer.get("url"), 2000)
                    title = _clean(offer.get("title_candidate"), 300)

                    if not _valid_http_url(url) or len(title) < 2:
                        continue

                    title_status = offer.get("title_status", "")
                    verified = title_status in {
                        "confirmed_from_public_page_metadata",
                        "confirmed_from_public_api",
                    }
                    verification_status = "verified" if verified else "needs_review"
                    verified_at = _now() if verified else None

                    location_restrictions = post.get(
                        "location_restrictions", []
                    )
                    if not isinstance(location_restrictions, list):
                        location_restrictions = []
                    eligibility_notes = "; ".join(
                        _clean(item, 200)
                        for item in location_restrictions
                        if isinstance(item, str)
                    )[:1000]

                    mobility = post.get("mobility_statuses", {})
                    if not isinstance(mobility, dict):
                        mobility = {}

                    allowed_statuses = {
                        "visa_sponsorship_status": {
                            "confirmed", "mentioned", "not_offered", "unknown"
                        },
                        "relocation_support_status": {
                            "confirmed", "mentioned", "not_offered", "unknown"
                        },
                        "senegal_eligibility_status": {
                            "eligible", "ineligible", "unclear", "unknown"
                        },
                    }
                    mobility_values = {}
                    for key, allowed in allowed_statuses.items():
                        value = mobility.get(key, "unknown")
                        mobility_values[key] = (
                            value if value in allowed else "unknown"
                        )

                    existing_offer = db.execute(
                        "SELECT id FROM recruiter_offers WHERE url = ?",
                        (url,),
                    ).fetchone()

                    offer_values = (
                        recruiter_id,
                        title,
                        _clean(offer.get("employer_candidate") or company, 200),
                        "",
                        "",
                        "",
                        "",
                        notes,
                        url,
                        comment_url,
                        post.get("published_at"),
                        recruiters.json.dumps(skills, ensure_ascii=False),
                        _now(),
                        _now(),
                        mobility_values["visa_sponsorship_status"],
                        mobility_values["relocation_support_status"],
                        mobility_values["senegal_eligibility_status"],
                        eligibility_notes,
                        comment_url,
                        verification_status,
                        verified_at,
                    )

                    if existing_offer:
                        db.execute(
                            """
                            UPDATE recruiter_offers
                            SET recruiter_id = ?, title = ?, company = ?,
                                location = COALESCE(NULLIF(?, ''), location),
                                country = COALESCE(NULLIF(?, ''), country),
                                work_mode = COALESCE(NULLIF(?, ''), work_mode),
                                contract_type = COALESCE(NULLIF(?, ''), contract_type),
                                description = ?,
                                source_url = ?, published_at = ?, skills = ?,
                                last_checked_at = ?,
                                visa_sponsorship_status =
                                    CASE WHEN visa_sponsorship_status != 'unknown'
                                    THEN visa_sponsorship_status ELSE ? END,
                                relocation_support_status =
                                    CASE WHEN relocation_support_status != 'unknown'
                                    THEN relocation_support_status ELSE ? END,
                                senegal_eligibility_status =
                                    CASE WHEN senegal_eligibility_status != 'unknown'
                                    THEN senegal_eligibility_status ELSE ? END,
                                eligibility_notes =
                                    CASE WHEN eligibility_notes != ''
                                    THEN eligibility_notes ELSE ? END,
                                evidence_url =
                                    CASE WHEN evidence_url != ''
                                    THEN evidence_url ELSE ? END,
                                verification_status =
                                    CASE WHEN verification_status = 'verified'
                                    THEN verification_status ELSE ? END,
                                verified_at =
                                    CASE WHEN verified_at IS NOT NULL
                                    THEN verified_at ELSE ? END
                            WHERE url = ?
                            """,
                            (
                                offer_values[0], offer_values[1],
                                offer_values[2], offer_values[3],
                                offer_values[4], offer_values[5],
                                offer_values[6], offer_values[7],
                                offer_values[9], offer_values[10],
                                offer_values[11], offer_values[13],
                                offer_values[14], offer_values[15],
                                offer_values[16], offer_values[17],
                                offer_values[18], offer_values[19],
                                offer_values[20], url,
                            ),
                        )
                        updated += 1
                    else:
                        db.execute(
                            """
                            INSERT INTO recruiter_offers (
                                recruiter_id, title, company, location, country,
                                work_mode, contract_type, description, url,
                                source_url, published_at, skills, collected_at,
                                last_checked_at, visa_sponsorship_status,
                                relocation_support_status,
                                senegal_eligibility_status, eligibility_notes,
                                evidence_url, verification_status, verified_at
                            ) VALUES (
                                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?
                            )
                            """,
                            offer_values,
                        )
                        inserted += 1

            db.execute(
                """
                UPDATE recruiter_sync_runs
                SET finished_at = ?, status = 'success',
                    inserted = ?, updated = ?, error = ''
                WHERE id = ?
                """,
                (_now(), inserted, updated, run_id),
            )
            db.commit()

        return {
            "status": "success",
            "posts_seen": len(posts),
            "inserted": inserted,
            "updated": updated,
        }

    except Exception as exc:
        with recruiters.connect() as db:
            db.execute(
                """
                UPDATE recruiter_sync_runs
                SET finished_at = ?, status = 'failed', inserted = ?,
                    updated = ?, error = ?
                WHERE id = ?
                """,
                (_now(), inserted, updated, str(exc)[:2000], run_id),
            )
            db.commit()
        raise


def sync_official_recruiters():
    """Synchronise les offres structurées des sites officiels autorisés."""
    from app.recruiter_official import collect_official_jobpostings

    source = "official_recruiter_jobposting"
    recruiters.init_recruiters_db()
    started_at = _now()

    with recruiters.connect() as db:
        cursor = db.execute(
            """
            INSERT INTO recruiter_sync_runs (source, started_at, status)
            VALUES (?, ?, 'started')
            """,
            (source, started_at),
        )
        run_id = cursor.lastrowid
        db.commit()

    inserted = updated = 0
    try:
        result = collect_official_jobpostings()
        offers = result.get("offers", [])

        profiles = result.get("recruiters", [])
        if not isinstance(profiles, list):
            profiles = []

        with recruiters.connect() as db:
            # Enregistrer les profils officiels même si aucune offre n'est trouvée.
            for profile in profiles:
                if not isinstance(profile, dict):
                    continue

                name = _clean(profile.get("name"), 200)
                website = _clean(profile.get("website"), 1000)
                country = _clean(profile.get("country"), 200)
                source_url = _clean(profile.get("source_url"), 2000) or website

                if not name or not _valid_http_url(website):
                    continue

                contact_name = _clean(profile.get("contact_name"), 200)
                contact_role = _clean(profile.get("contact_role"), 200)
                contact_email = _clean(profile.get("contact_email"), 320)
                contact_phone = _clean(profile.get("contact_phone"), 100)
                linkedin_url = _clean(profile.get("linkedin_url"), 1000)
                contact_url = _clean(profile.get("contact_url"), 1000)

                specialties = profile.get("specialties", [])
                if not isinstance(specialties, list):
                    specialties = []
                specialties_json = recruiters.json.dumps(
                    [
                        _clean(item, 100)
                        for item in specialties
                        if isinstance(item, str) and _clean(item, 100)
                    ],
                    ensure_ascii=False,
                )

                now = _now()
                existing_profile = db.execute(
                    """
                    SELECT id FROM recruiters
                    WHERE name = ?
                    ORDER BY
                        CASE WHEN source_name LIKE 'Site officiel%' THEN 0 ELSE 1 END,
                        id
                    LIMIT 1
                    """,
                    (name,),
                ).fetchone()

                if existing_profile:
                    db.execute(
                        """
                        UPDATE recruiters SET
                            website_url = CASE WHEN website_url = '' THEN ?
                                               ELSE website_url END,
                            country = CASE WHEN country = '' THEN ?
                                           ELSE country END,
                            specialties = CASE WHEN ? NOT IN ('', '[]')
                                               AND specialties IN ('', '[]')
                                               THEN ? ELSE specialties END,
                            contact_name = CASE WHEN contact_name = '' THEN ?
                                                 ELSE contact_name END,
                            contact_role = CASE WHEN contact_role = '' THEN ?
                                                 ELSE contact_role END,
                            contact_email = CASE WHEN contact_email = '' THEN ?
                                                  ELSE contact_email END,
                            contact_phone = CASE WHEN contact_phone = '' THEN ?
                                                  ELSE contact_phone END,
                            linkedin_url = CASE WHEN linkedin_url = '' THEN ?
                                                 ELSE linkedin_url END,
                            contact_url = CASE WHEN contact_url = '' THEN ?
                                                ELSE contact_url END,
                            source_url = CASE WHEN source_url = '' THEN ?
                                               ELSE source_url END,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            website, country,
                            specialties_json, specialties_json,
                            contact_name, contact_role, contact_email,
                            contact_phone, linkedin_url, contact_url,
                            source_url, now, existing_profile["id"],
                        ),
                    )
                else:
                    db.execute(
                        """
                        INSERT INTO recruiters (
                            name, website_url, country, specialties,
                            contact_name, contact_role, contact_email,
                            contact_phone, linkedin_url, contact_url,
                            source_url, source_name, notes, verified_at,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)
                        """,
                        (
                            name, website, country, specialties_json,
                            contact_name, contact_role, contact_email,
                            contact_phone, linkedin_url, contact_url,
                            source_url, f"Site officiel {name}", now, now, now,
                        ),
                    )

            for offer in offers:
                profile = offer.get("recruiter", {})
                name = _clean(profile.get("name"), 200)
                website = _clean(profile.get("website"), 1000)
                country = _clean(profile.get("country"), 200)
                url = _clean(offer.get("url"), 2000)
                title = _clean(offer.get("title"), 300)

                if not name or not _valid_http_url(website):
                    continue
                if not _valid_http_url(url) or len(title) < 2:
                    continue

                # Réutiliser la fiche existante si elle a déjà été importée.
                recruiter = db.execute(
                    """
                    SELECT id FROM recruiters
                    WHERE name = ?
                    ORDER BY
                        CASE WHEN source_name LIKE 'Site officiel%' THEN 0 ELSE 1 END,
                        id
                    LIMIT 1
                    """,
                    (name,),
                ).fetchone()

                now = _now()
                if recruiter:
                    recruiter_id = recruiter["id"]
                    db.execute(
                        """
                        UPDATE recruiters
                        SET website_url = CASE WHEN website_url = ''
                                               THEN ? ELSE website_url END,
                            country = CASE WHEN country = ''
                                           THEN ? ELSE country END,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (website, country, now, recruiter_id),
                    )
                else:
                    cursor = db.execute(
                        """
                        INSERT INTO recruiters (
                            name, website_url, country, source_url, source_name,
                            notes, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, '', ?, ?)
                        """,
                        (
                            name, website, country, website,
                            f"Site officiel {name}", now, now,
                        ),
                    )
                    recruiter_id = cursor.lastrowid

                skills = offer.get("skills", [])
                if not isinstance(skills, list):
                    skills = []
                skills_json = recruiters.json.dumps(
                    [_clean(item, 80) for item in skills if isinstance(item, str)],
                    ensure_ascii=False,
                )
                location = _clean(offer.get("location"), 500)
                description = _clean(offer.get("description"), 8000)
                source_url = _clean(offer.get("source_url"), 2000)
                published_at = _clean(offer.get("published_at"), 100) or None
                deadline = _clean(offer.get("deadline"), 100) or None
                work_mode = (
                    "remote"
                    if "remote" in (title + " " + description).lower()
                    else ""
                )
                contract_type = _clean(offer.get("employment_type"), 100)
                evidence_url = _clean(offer.get("evidence_url"), 2000)
                verification = (
                    "verified"
                    if offer.get("verification_status") == "verified"
                    else "needs_review"
                )

                existing = db.execute(
                    "SELECT * FROM recruiter_offers WHERE url = ?",
                    (url,),
                ).fetchone()

                if existing:
                    # Ne pas effacer une valeur connue par une valeur inconnue.
                    db.execute(
                        """
                        UPDATE recruiter_offers
                        SET recruiter_id = ?,
                            title = ?, company = ?,
                            location = CASE WHEN ? != '' THEN ? ELSE location END,
                            country = CASE WHEN ? != '' THEN ? ELSE country END,
                            work_mode = CASE WHEN ? != '' THEN ? ELSE work_mode END,
                            contract_type = CASE WHEN ? != '' THEN ? ELSE contract_type END,
                            description = CASE WHEN ? != '' THEN ? ELSE description END,
                            source_url = CASE WHEN ? != '' THEN ? ELSE source_url END,
                            published_at = COALESCE(?, published_at),
                            deadline = COALESCE(?, deadline),
                            skills = CASE WHEN ? != '[]' THEN ? ELSE skills END,
                            last_checked_at = ?,
                            visa_sponsorship_status =
                                CASE WHEN visa_sponsorship_status != 'unknown'
                                     THEN visa_sponsorship_status ELSE ? END,
                            relocation_support_status =
                                CASE WHEN relocation_support_status != 'unknown'
                                     THEN relocation_support_status ELSE ? END,
                            senegal_eligibility_status =
                                CASE WHEN senegal_eligibility_status != 'unknown'
                                     THEN senegal_eligibility_status ELSE ? END,
                            eligibility_notes =
                                CASE WHEN eligibility_notes != ''
                                     THEN eligibility_notes ELSE ? END,
                            evidence_url =
                                CASE WHEN evidence_url != ''
                                     THEN evidence_url ELSE ? END,
                            verification_status =
                                CASE WHEN verification_status = 'verified'
                                     THEN verification_status ELSE ? END,
                            verified_at =
                                CASE WHEN verified_at IS NOT NULL
                                     THEN verified_at ELSE ? END
                        WHERE url = ?
                        """,
                        (
                            recruiter_id, title, name,
                            location, location, country, country,
                            work_mode, work_mode, contract_type, contract_type,
                            description, description, source_url, source_url,
                            published_at, deadline, skills_json, skills_json, now,
                            offer.get("visa_sponsorship_status", "unknown"),
                            offer.get("relocation_support_status", "unknown"),
                            offer.get("senegal_eligibility_status", "unknown"),
                            _clean(offer.get("eligibility_notes"), 1000),
                            evidence_url,
                            verification, now if verification == "verified" else None,
                            url,
                        ),
                    )
                    updated += 1
                else:
                    db.execute(
                        """
                        INSERT INTO recruiter_offers (
                            recruiter_id, title, company, location, country,
                            work_mode, contract_type, description, url, source_url,
                            published_at, deadline, skills, collected_at,
                            last_checked_at, visa_sponsorship_status,
                            relocation_support_status, senegal_eligibility_status,
                            eligibility_notes, evidence_url, verification_status,
                            verified_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            recruiter_id, title, name, location, country,
                            work_mode, contract_type, description, url, source_url,
                            published_at, deadline, skills_json, now, now,
                            offer.get("visa_sponsorship_status", "unknown"),
                            offer.get("relocation_support_status", "unknown"),
                            offer.get("senegal_eligibility_status", "unknown"),
                            _clean(offer.get("eligibility_notes"), 1000),
                            evidence_url, verification,
                            now if verification == "verified" else None,
                        ),
                    )
                    inserted += 1

            db.execute(
                """
                UPDATE recruiter_sync_runs
                SET finished_at = ?, status = 'success',
                    inserted = ?, updated = ?, error = ''
                WHERE id = ?
                """,
                (_now(), inserted, updated, run_id),
            )
            db.commit()

        return {
            "status": "success",
            "offers_seen": len(offers),
            "inserted": inserted,
            "updated": updated,
            "errors": result.get("errors", []),
        }

    except Exception as exc:
        with recruiters.connect() as db:
            db.execute(
                """
                UPDATE recruiter_sync_runs
                SET finished_at = ?, status = 'failed',
                    inserted = ?, updated = ?, error = ?
                WHERE id = ?
                """,
                (_now(), inserted, updated, str(exc)[:2000], run_id),
            )
            db.commit()
        raise
