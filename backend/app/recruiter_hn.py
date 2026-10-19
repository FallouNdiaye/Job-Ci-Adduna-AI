"""Collecteur Hacker News 'Who is hiring?' — simulation sans écriture DB."""
import argparse
import html
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

API = "https://hn.algolia.com/api/v1"
HN_ITEM = "https://news.ycombinator.com/item?id="
TIMEOUT = 20

TECH_TERMS = {
    "Java", "Spring Boot", "Spring", "Python", "Django", "FastAPI",
    "JavaScript", "TypeScript", "React", "Angular", "Vue", "Node.js",
    "PHP", "Laravel", "Symfony", "Flutter", "Dart", "Android", "iOS",
    "PostgreSQL", "MySQL", "SQL", "Docker", "Kubernetes", "AWS",
    "Azure", "GCP", "Kafka", "REST", "GraphQL", "C#", ".NET",
    "Go", "Golang", "Rust", "Ruby", "Rails", "AI", "Machine Learning",
    "DevOps", "Terraform", "Kotlin", "Swift",
}
ROLE_TERMS = (
    "software engineer", "software developer", "software engineers",
    "full stack", "full-stack", "backend engineer", "back-end engineer",
    "frontend engineer", "front-end engineer", "mobile developer",
    "mobile engineer", "web developer", "web engineer",
    "devops engineer", "devsecops engineer", "cloud engineer",
    "platform engineer", "systems engineer", "infrastructure engineer",
    "data engineer", "machine learning engineer", "ml engineer",
    "ai engineer", "security engineer", "site reliability engineer",
    "staff engineer", "principal engineer", "tech lead",
    "product engineer", "android engineer", "android developer",
    "ios engineer", "ios developer", "flutter developer",
    "r&d engineer", "intelligence engineer", "senior swe",
    "swe", "developer", "programmer",
)
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def get_json(client, url, params=None):
    response = client.get(url, params=params)
    response.raise_for_status()
    return response.json()


def fetch_ashby_public_jobs(client):
    """Charge les offres de tableaux Ashby publics connus, sans écriture."""
    boards = {
        "thundercompute": "Thunder Compute",
        "smarkets": "Smarkets",
        "prairielearn": "PrairieLearn",
    }
    indexed_jobs = {}

    for board, employer in boards.items():
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
        try:
            payload = get_json(client, url)
            jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        except (httpx.HTTPError, ValueError):
            continue

        for job in jobs:
            if not isinstance(job, dict) or not job.get("id"):
                continue
            enriched = dict(job)
            enriched["_employer_candidate"] = employer
            indexed_jobs[f"{board}:{job['id']}"] = enriched

    return indexed_jobs


def latest_hiring_threads(client, limit=5):
    data = get_json(client, f"{API}/search_by_date", {
        "query": "Who is hiring",
        "tags": "story",
        "hitsPerPage": max(20, limit * 5),
    })
    hits = [
        hit for hit in data.get("hits", [])
        if re.search(
            r"ask hn:\s*who is hiring",
            hit.get("title") or "",
            re.I,
        )
    ]
    hits.sort(key=lambda item: item.get("created_at_i", 0), reverse=True)
    return hits[:limit]


def extract_mobility_statuses(text):
    """Classe les indices de mobilité sans déduire l'éligibilité du Sénégal."""
    t = re.sub(r"\s+", " ", text or "").lower()

    visa_negative = re.search(
        r"\b(?:no visa sponsorship|no sponsorship|without sponsorship|"
        r"visa sponsorship not available|do not offer visa sponsorship|"
        r"do not provide visa sponsorship|don't offer visa sponsorship|"
        r"not offering visa sponsorship|will not sponsor visas?|"
        r"cannot sponsor visas?|unable to sponsor visas?)\b", t
    )
    visa_positive = re.search(
        r"\b(?:we offer visa sponsorship|we provide visa sponsorship|"
        r"visa sponsorship available|visa sponsorship is available|"
        r"we sponsor visas?|will sponsor visas?)\b", t
    )
    if visa_negative:
        visa = "not_offered"
    elif visa_positive:
        visa = "confirmed"
    elif re.search(r"\b(?:visa sponsorship|sponsor(?:ship)? visas?)\b", t):
        visa = "mentioned"
    else:
        visa = "unknown"

    relocation_negative = re.search(
        r"\b(?:no relocation assistance|no relocation support|"
        r"relocation assistance not available|relocation support not available|"
        r"do not offer relocation|do not provide relocation|"
        r"don't offer relocation|relocation is not provided)\b", t
    )
    relocation_positive = re.search(
        r"\b(?:relocation assistance available|relocation support available|"
        r"we offer relocation assistance|we offer relocation support|"
        r"we provide relocation assistance|we provide relocation support|"
        r"relocation assistance provided|relocation support provided)\b", t
    )
    if relocation_negative:
        relocation = "not_offered"
    elif relocation_positive:
        relocation = "confirmed"
    elif re.search(r"\brelocation (?:assistance|support)\b", t):
        relocation = "mentioned"
    else:
        relocation = "unknown"

    senegal_positive = re.search(
        r"\b(?:hire|hiring|employ|employment|payroll|work)\b"
        r".{0,70}\b(?:in|from|within|based in)\s+senegal\b|"
        r"\bsenegal(?:ese)? candidates (?:are|will be) eligible\b", t
    )
    senegal_negative = re.search(
        r"\b(?:do not|don't|cannot|can't|unable to|not)\s+"
        r"(?:hire|employ|recruit|pay|support employment)\b"
        r".{0,70}\bsenegal\b|"
        r"\bsenegal(?:ese)? candidates (?:are not|aren't) eligible\b", t
    )
    if senegal_negative:
        senegal = "ineligible"
    elif senegal_positive:
        senegal = "eligible"
    else:
        senegal = "unknown"

    return {
        "visa_sponsorship_status": visa,
        "relocation_support_status": relocation,
        "senegal_eligibility_status": senegal,
    }


def classify_location(text):
    t = text.lower()
    restrictions = []

    if re.search(r"\b(us only|usa only|u\.s\. only|must be in the us|"
                 r"only in the united states|us citizens only)\b", t):
        restrictions.append("USA uniquement / éligibilité à vérifier")
    if re.search(r"\b(remote us|remote - us|us time ?zones?|"
                 r"north american time ?zones?)\b", t):
        restrictions.append("Fuseaux horaires nord-américains")
    if re.search(r"\b(eu citizens only|eu only|must be based in europe)\b", t):
        restrictions.append("Europe uniquement / éligibilité à vérifier")
    if re.search(
        r"\b(must be authorized to work|work authorization required|"
        r"no sponsorship|without sponsorship|no visa sponsorship|"
        r"visa sponsorship not available|do not offer visa sponsorship|do not provide visa sponsorship|do not sponsor visas?|"
        r"will not sponsor visas?)\b", t
    ):
        restrictions.append("Autorisation de travail / visa à vérifier")
    negative_visa = re.search(
        r"\b(no sponsorship|without sponsorship|no visa sponsorship|"
        r"visa sponsorship not available|do not offer visa sponsorship|do not provide visa sponsorship|do not sponsor visas?|"
        r"will not sponsor visas?)\b", t
    )
    positive_visa = re.search(
        r"\b(visa sponsorship|sponsor(?:ship)? visas?|"
        r"we sponsor visas?)\b", t
    )
    if positive_visa and not negative_visa:
        restrictions.append("Parrainage de visa mentionné")
    if re.search(r"\b(relocation assistance|relocation support)\b", t):
        restrictions.append("Aide à la mobilité mentionnée")
    if re.search(r"\b(dutch required|german required|french required|"
                 r"must speak german|must speak dutch|fluent in german)\b", t):
        restrictions.append("Langue locale exigée")
    if re.search(r"\b(on[- ]?site|in[- ]office|hybrid)\b", t):
        restrictions.append("Présence sur site ou hybride")
    if re.search(r"\b(work from anywhere|anywhere in the world|"
                 r"worldwide remote|remote worldwide|globally remote|"
                 r"any country)\b", t):
        restrictions.append("Ouverture internationale annoncée — à vérifier")

    return restrictions



def extract_title_candidate(text, fallback_roles):
    """Privilégie les titres d'en-tête et les marqueurs explicites."""
    roles = sorted(ROLE_TERMS, key=len, reverse=True)

    def has_role(value):
        return any(
            re.search(
                r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])",
                value, re.I,
            )
            for term in roles
        )

    # Les marqueurs explicites dans le corps passent en premier.
    markers = (
        "currently looking for:",
        "currently hiring for:",
        "featured role this month:",
        "featured role:",
        "we're hiring:",
        "we are hiring:",
        "open position:",
        "open role:",
    )
    lower = text.lower()
    for marker in markers:
        pos = lower.find(marker)
        if pos < 0:
            continue
        tail = text[pos + len(marker):].strip()
        candidate = re.split(
            r"\s+-\s+|\s+[—–|]\s+|\.\s+",
            tail, maxsplit=1,
        )[0].strip(" :|-")
        candidate = re.sub(r"\s+", " ", candidate).strip()
        candidate = re.sub(r"\s*[-–—]\s*(details|learn more|apply here)\s*$",
                           "", candidate, flags=re.I).strip()
        if candidate and len(candidate) <= 180 and has_role(candidate):
            if not re.search(
                r"\b(you will|you'll|we are|we're|our team|"
                r"responsibilities include)\b", candidate, re.I
            ):
                return candidate

    # En-têtes HN courants : Entreprise | titre | lieu/contrat.
    parts = re.split(r"\s*\|\s*|\s+[—–]\s+", text)
    for part in parts[1:5]:
        candidate = re.sub(r"\s+", " ", part).strip(" :|-")
        if not candidate or len(candidate) > 160 or not has_role(candidate):
            continue

        # Ne pas prendre une localisation suivie d'une description
        # pour un titre uniquement parce qu'elle mentionne un rôle.
        if re.search(
            r"\b(?:CA|California|NY|New York|San Francisco)\b.*"
            r"\b(?:we are|we're|our team|building|looking for|hiring)\b",
            candidate, re.I,
        ):
            continue
        if re.search(
            r"\b(remote|onsite|on-site|hybrid|full-time|part-time|"
            r"salary|compensation)\b|[$€£]\s?[\d,]",
            candidate, re.I,
        ):
            continue
        # Plusieurs postes peuvent être regroupés dans un même en-tête.
        # On conserve le premier intitulé reconnu.
        # Ne raccourcit un segment que si plusieurs morceaux sont des rôles.
        items = [item.strip() for item in re.split(r",\s*(?![^()]*\))", candidate)]
        role_items = [item for item in items if item and has_role(item)]
        if len(role_items) >= 2:
            return role_items[0]
        return candidate

    # Un rôle générique trouvé dans la description n'est pas un titre confirmé.
    return "Intitulé à vérifier"


def classify_link(link):
    """Classe un lien public sans confondre page carrières et offre directe."""
    parsed = urlparse(link.get("url", ""))
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    path = parsed.path.lower().rstrip("/")
    label = link.get("text", "").lower()
    query = parsed.query.lower()

    # Identifiant de poste explicitement présent dans l'URL.
    if re.search(r"(?:^|&)(?:ashby_jid|gh_jid|job_id|jobid)=[^&]+", query):
        return "job_application"

    # URL Ashby : /entreprise = liste des postes ; /entreprise/UUID = offre.
    if host == "jobs.ashbyhq.com" or host.endswith(".ashbyhq.com"):
        segments = [part for part in path.split("/") if part]
        if len(segments) >= 2:
            return "job_application"
        return "careers_page"

    # URL d'une offre individuelle sous /jobs/<slug> ou /job/<slug>.
    if re.search(r"/(?:jobs|job)/[^/]+$", path):
        slug = path.rsplit("/", 1)[-1]
        if slug not in {"jobs", "job", "careers", "career", "open-positions"}:
            return "job_application"

    # Pages générales de recrutement.
    if (
        re.search(r"/(?:careers?|jobs?|open-positions|join-our-team)$", path)
        or re.search(r"\b(careers page|career page|view all jobs|all positions)\b", label)
    ):
        return "careers_page"

    # Indice de candidature sans preuve suffisante d'une offre individuelle.
    if any(term in path or term in label for term in (
        "career", "careers", "jobs", "job/", "apply", "application",
        "ashby", "greenhouse", "lever.co", "workday",
    )):
        return "career_or_application"

    return "company_or_other"


def extract_link_context_title(context):
    """Extrait prudemment un titre situé juste avant un lien public."""
    context = re.sub(r"\s+", " ", context or "").strip()
    if not context:
        return None

    lowered = context.lower()
    for phrase in ("open roles:", "we are currently looking for:"):
        pos = lowered.rfind(phrase)
        if pos >= 0:
            context = context[pos + len(phrase):].strip()
            break
    else:
        # Sans marqueur explicite, n'accepte que les segments proches
        # d'un lien qui se terminent comme une entrée de liste.
        if not (
            re.search(r"\([^)]{1,100}\)", context)
            or re.search(r"[-–—:|]\s*$", context)
        ):
            return None

    context = context.strip(" \t\r\n-–—:|")
    if not context:
        return None

    # Les annonces ciblées placent le salaire/détail entre parenthèses.
    if "(" in context:
        context = context.split("(", 1)[0].strip()

    context = re.sub(r"\s+", " ", context).strip(" .,:;—–-|")
    if not context or len(context) > 120:
        return None

    # Évite de prendre un paragraphe descriptif pour un intitulé.
    if len(context.split()) > 12:
        return None

    return context


def extract_individual_offers(application_links, ashby_jobs=None, company_candidate=None):
    """Construit des offres candidates à partir des liens directs, sans réseau."""
    import re
    from urllib.parse import unquote

    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{12}$", re.I
    )
    known_employers = {
        "shinvestmentsllc": "SH Investments",
        "bree": "Bree",
        "emergent software": "Emergent Software",
        "leadership connect": "Leadership Connect",
        "match group": "Match Group",
        "samsara": "Samsara",
        "spacex": "SpaceX",
        "truetandem": "True Tandem",
    }

    offers = []
    for link in application_links:
        if link.get("kind") != "job_application":
            continue

        parsed = urlparse(link.get("url", ""))
        slug = unquote(parsed.path).rstrip("/").split("/")[-1]

        from urllib.parse import parse_qs
        query_params = parse_qs(parsed.query)
        query_job_id = next(
            (
                query_params[key][0]
                for key in ("ashby_jid", "gh_jid", "job_id", "jobid")
                if query_params.get(key)
            ),
            None,
        )
        candidate_job_id = query_job_id or slug

        offer = {
            "url": link.get("url"),
            "title_candidate": None,
            "employer_candidate": None,
            "title_status": "needs_verification",
        }

        # Instantané de métadonnées publiques vérifiées le 2026-10-18.
        # Ce n'est pas une nouvelle vérification réseau pendant la collecte.
        host = (parsed.hostname or "").lower()
        page_path = parsed.path.rstrip("/") or "/"

        verified_page_metadata = {
            (
                "germantechjobs.de",
                "/jobs/PAGNOS-GmbH-Cloud-AI-Engineer--AWS-Serverless-mwd",
            ): {
                "title": "Cloud AI Engineer – AWS Serverless (m/w/d)",
                "employer": "PAGNOS GmbH",
            },
            (
                "www.opensanctions.org",
                "/docs/company/jobs/2026-09-product-engineer",
            ): {
                "title": "Freelance: Product Engineer (d/w/m)",
                "employer": "OpenSanctions",
            },
            (
                "opensanctions.org",
                "/docs/company/jobs/2026-09-product-engineer",
            ): {
                "title": "Freelance: Product Engineer (d/w/m)",
                "employer": "OpenSanctions",
            },
        }

        page_metadata = verified_page_metadata.get((host, page_path))
        if page_metadata:
            offer["title_candidate"] = page_metadata["title"]
            offer["employer_candidate"] = page_metadata["employer"]
            offer["title_status"] = "confirmed_from_public_page_metadata"
            offer["title_source"] = "public_page_metadata_snapshot"
            offers.append(offer)
            continue

        if uuid_pattern.fullmatch(candidate_job_id):
            path_parts = parsed.path.strip("/").split("/")
            host = (parsed.hostname or "").lower()
            board = None

            if host == "jobs.ashbyhq.com" and len(path_parts) >= 2:
                board = path_parts[0].lower()
            elif query_job_id and host.endswith("prairielearn.com"):
                board = "prairielearn"

            job = (
                (ashby_jobs or {}).get(f"{board}:{candidate_job_id}")
                if board else None
            )

            if job and job.get("title"):
                offer["title_candidate"] = job["title"]
                offer["employer_candidate"] = job.get("_employer_candidate")
                offer["title_status"] = "confirmed_from_public_api"
                offer["url"] = job.get("jobUrl") or offer["url"]
                if job.get("department"):
                    offer["department_candidate"] = job["department"]
            else:
                context_title = link.get("title_context_candidate")
                if context_title:
                    offer["title_candidate"] = context_title
                    if company_candidate and company_candidate != "Entreprise non identifiée":
                        offer["employer_candidate"] = company_candidate
                    offer["title_status"] = "candidate_from_public_comment"
                    offer["title_source"] = "hacker_news_comment_text"
                else:
                    offer["title_status"] = "needs_page_fetch"

            offers.append(offer)
            continue

        # Les règles employeur sont limitées au domaine CareerJumpShip.
        if parsed.hostname and parsed.hostname.lower() == "www.careerjumpship.com":
            slug = re.sub(r"-[0-9a-f]{8}$", "", slug, flags=re.I)
            normalized = re.sub(r"-+", " ", slug).strip()

            for suffix, employer in sorted(
                known_employers.items(),
                key=lambda item: len(item[0]),
                reverse=True,
            ):
                if normalized.lower().endswith(" " + suffix.lower()):
                    title = normalized[:-(len(suffix))].strip()
                    if title:
                        formatted_title = title.title()
                        acronym_map = {
                            "Ai": "AI",
                            "Ii": "II",
                            "Iii": "III",
                            "Iv": "IV",
                            "Api": "API",
                            "Aws": "AWS",
                            "Qa": "QA",
                            "Ui": "UI",
                            "Ux": "UX",
                            "Sre": "SRE",
                            "Sql": "SQL",
                            "Iot": "IoT",
                            "Devops": "DevOps",
                            "Javascript": "JavaScript",
                            "Typescript": "TypeScript",
                        }
                        formatted_title = re.sub(
                            r"\b[A-Za-z][A-Za-z0-9+.-]*\b",
                            lambda match: acronym_map.get(
                                match.group(0), match.group(0)
                            ),
                            formatted_title,
                        )
                        offer["title_candidate"] = formatted_title
                        offer["employer_candidate"] = employer
                        offer["title_status"] = "candidate_from_url"
                    break

        offers.append(offer)

    return offers


def parse_comment(comment, thread, ashby_jobs=None):
    raw = comment.get("text") or ""
    if not raw.strip():
        return None

    soup = BeautifulSoup(raw, "html.parser")

    # Une copie du HTML permet d'isoler le texte qui précède chaque lien,
    # sans modifier le contenu utilisé pour analyser le commentaire.
    context_soup = BeautifulSoup(raw, "html.parser")
    context_anchors = context_soup.find_all("a", href=True)
    markers = []
    for index, anchor in enumerate(context_anchors):
        marker_text = f" JH_LINK_CONTEXT_{index}_END "
        markers.append(marker_text.strip())
        anchor.replace_with(marker_text)
    context_segments = re.sub(
        r"\s+", " ", context_soup.get_text(" ", strip=True)
    ).split()
    context_text = " ".join(context_segments)

    # Reconstruit les segments par marqueurs, dans l'ordre des liens.
    marker_segments = []
    remaining = context_text
    for marker_text in markers:
        before, separator, remaining = remaining.partition(marker_text)
        marker_segments.append(before if separator else "")
    links = []
    for index, anchor in enumerate(soup.find_all("a", href=True)):
        href = html.unescape(anchor["href"]).strip()
        if urlparse(href).scheme in ("http", "https"):
            links.append({
                "text": anchor.get_text(" ", strip=True),
                "url": href,
                "host": urlparse(href).netloc.lower(),
                "title_context_candidate": extract_link_context_title(
                    marker_segments[index] if index < len(marker_segments) else ""
                ),
            })

    text = html.unescape(soup.get_text(" ", strip=True))
    text = re.sub(r"\s+", " ", text).strip()
    lowered = text.lower()

    matched_roles = [term for term in ROLE_TERMS if term in lowered]
    if not matched_roles:
        return None

    matched_skills = [
        term for term in sorted(TECH_TERMS, key=str.lower)
        if re.search(
            r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])",
            lowered,
        )
    ]
    emails = sorted(set(EMAIL_RE.findall(text)), key=str.lower)

    # Conserve les liens explicites. Ne fabrique jamais d'adresse de candidature.
    application_links = []
    for link in links:
        if link["host"].lower().endswith("ycombinator.com"):
            continue
        link["kind"] = classify_link(link)
        application_links.append(link)

    first_segment = re.split(
        r"\s+[—–|]\s+|\s+-\s+", text, maxsplit=1
    )[0]
    company = re.sub(r"https?://\S+", "", first_segment, flags=re.I)
    company = re.sub(r"\s*\(\s*\)", "", company)
    company = re.sub(
        r"\s*\((?:remote|onsite|on-site|hybrid|full remote|"
        r"remote us|remote eu)[^)]*\)",
        "", company, flags=re.I,
    )
    company = company[:160].strip(" \t:|—–-")
    if not company:
        company = "Entreprise non identifiée"

    created = comment.get("created_at")
    return {
        "company_candidate": company,
        "title_candidate": extract_title_candidate(text, matched_roles),
        "matched_roles": matched_roles,
        "skills": matched_skills,
        "public_emails": emails,
        "application_links": application_links,
        "individual_offers": extract_individual_offers(application_links, ashby_jobs, company),
        "location_restrictions": classify_location(text),
        "mobility_statuses": extract_mobility_statuses(text),
        "comment_url": HN_ITEM + str(comment.get("id", "")),
        "thread_title": thread.get("title", ""),
        "thread_url": HN_ITEM + str(thread.get("objectID", "")),
        "published_at": created,
        "text_preview": text[:500],
    }


def collect_hiring_records(limit=30, thread_limit=3):
    """Collecte les annonces publiques en mémoire, sans écrire en base."""
    now = datetime.now(timezone.utc).isoformat()
    with httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=False,
        headers={"User-Agent": "JobCiAddunaAI-public-recruiter-collector/1.0"},
    ) as client:
        ashby_jobs = fetch_ashby_public_jobs(client)
        threads = latest_hiring_threads(client, thread_limit)
        records = []
        checked_comments = 0

        for thread in threads:
            thread_id = thread.get("objectID")
            if not thread_id:
                continue
            item = get_json(client, f"{API}/items/{thread_id}")
            for comment in item.get("children", []):
                checked_comments += 1
                record = parse_comment(comment, thread, ashby_jobs)
                if record:
                    records.append(record)
                if checked_comments >= limit:
                    break
            if checked_comments >= limit:
                break

    return {
        "mode": "COLLECT_READ_ONLY",
        "generated_at": now,
        "threads_found": len(threads),
        "comments_checked": checked_comments,
        "technical_posts_detected": len(records),
        "posts_with_public_email": sum(bool(r["public_emails"]) for r in records),
        "posts_with_application_link": sum(bool(r["application_links"]) for r in records),
        "posts_with_location_constraints": sum(
            bool(r["location_restrictions"]) for r in records
        ),
        "database_written": False,
        "posts": records,
    }


def run_dry_run(limit=30, thread_limit=3):
    """Simulation affichée à l'écran ; aucune écriture en base."""
    result = collect_hiring_records(limit=limit, thread_limit=thread_limit)
    result["mode"] = "DRY_RUN_READ_ONLY"
    result["posts"] = result["posts"][:15]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--threads", type=int, default=3)
    args = parser.parse_args()
    run_dry_run(limit=max(1, min(args.limit, 300)),
                thread_limit=max(1, min(args.threads, 12)))
