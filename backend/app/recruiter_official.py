"""Collecteur prudent d'offres publiées sur les sites officiels de recruteurs.

Ne contourne pas les protections, respecte robots.txt et ne considère pas
une page de recrutement générique comme une offre d'emploi.
"""
from __future__ import annotations

import json
import re
import time
import urllib.robotparser
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urldefrag
from xml.etree import ElementTree

import httpx

from app.recruiter_hn import extract_mobility_statuses


USER_AGENT = "JobHunterAI/1.0 (public job discovery)"
MAX_BYTES = 2_000_000
MAX_PAGES_PER_SOURCE = 15
REQUEST_DELAY_SECONDS = 0.4

SOURCES = [
    {
        "name": "Crossover",
        "website": "https://www.crossover.com/",
        "seed": "https://www.crossover.com/",
        "country": "International / Remote",
    },
    {
        "name": "ITSync",
        "website": "https://www.itsync.nl/",
        "seed": "https://www.itsync.nl/jobs",
        "country": "Pays-Bas",
    },
    {
        "name": "First Point Group",
        "website": "https://www.firstpointgroup.com/",
        "seed": "https://www.firstpointgroup.com/job-search/",
        "country": "International",
    },
    {
        "name": "Trinamics",
        "website": "https://www.trinamics.nl/",
        "seed": "https://www.trinamics.nl/en/expats/",
        "country": "Pays-Bas / International",
    },
    {
        "name": "X-Team",
        "website": "https://x-team.com/",
        "seed": "https://x-team.com/careers",
        "country": "International / Remote",
    },
]


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.jsonld = []
        self.text_parts = []
        self._script_type = ""
        self._script_chunks = []
        self._in_script = False
        self._ignored_depth = 0

    @property
    def visible_text(self):
        return re.sub(r"\\s+", " ", " ".join(self.text_parts)).strip()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        tag = tag.lower()
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "script":
            self._in_script = True
            self._script_type = attrs.get("type", "").lower()
            self._script_chunks = []
        elif tag in ("style", "noscript"):
            self._ignored_depth += 1

    def handle_data(self, data):
        if self._in_script:
            if self._script_type == "application/ld+json":
                self._script_chunks.append(data)
        elif self._ignored_depth == 0:
            self.text_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "script":
            if self._script_type == "application/ld+json":
                raw = "".join(self._script_chunks).strip()
                if raw:
                    try:
                        self.jsonld.append(json.loads(raw))
                    except (ValueError, TypeError):
                        pass
            self._in_script = False
            self._script_type = ""
            self._script_chunks = []
        elif tag in ("style", "noscript") and self._ignored_depth:
            self._ignored_depth -= 1


def _same_host(url, base):
    try:
        a, b = urlparse(url), urlparse(base)
        return (
            a.scheme == "https"
            and b.scheme == "https"
            and a.hostname == b.hostname
            and a.username is None
            and a.password is None
        )
    except ValueError:
        return False


def _jobposting_nodes(value):
    """Yield JSON-LD JobPosting objects, including nested @graph objects."""
    if isinstance(value, list):
        for item in value:
            yield from _jobposting_nodes(item)
    elif isinstance(value, dict):
        kind = value.get("@type", [])
        if isinstance(kind, str):
            kind = [kind]
        if any(str(item).lower() == "jobposting" for item in kind):
            yield value
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in value:
                yield from _jobposting_nodes(value[key])


class _DescriptionTextParser(HTMLParser):
    """Convertit une description HTML en texte sans ses balises."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain_text(value, limit=8000):
    if not isinstance(value, str):
        return _text(value, limit)

    parser = _DescriptionTextParser()
    try:
        parser.feed(value)
        parser.close()
        content = " ".join(parser.parts)
    except Exception:
        content = re.sub(r"<[^>]*>", " ", value)

    content = unescape(content)
    return re.sub(r"\s+", " ", content).strip()[:limit]


def _text(value, limit=2000):
    if isinstance(value, str):
        return re.sub(r"\s+", " ", unescape(value)).strip()[:limit]
    if isinstance(value, dict):
        return _text(value.get("name", ""), limit)
    return ""


def _location(job):
    locations = job.get("jobLocation", [])
    if isinstance(locations, dict):
        locations = [locations]
    parts = []
    for entry in locations if isinstance(locations, list) else []:
        if not isinstance(entry, dict):
            continue
        address = entry.get("address", {})
        if isinstance(address, str):
            parts.append(address)
        elif isinstance(address, dict):
            value = ", ".join(
                _text(address.get(key), 120)
                for key in ("addressLocality", "addressRegion", "addressCountry")
                if _text(address.get(key), 120)
            )
            if value:
                parts.append(value)
    return "; ".join(dict.fromkeys(parts))[:500]


def extract_jobpostings(jsonld, page_url, company):
    """Normalise explicit JobPosting metadata; do not infer mobility."""
    offers = []
    for root in jsonld:
        for job in _jobposting_nodes(root):
            title = _text(job.get("title"), 300)
            url = urljoin(page_url, _text(job.get("url"), 1000) or page_url)
            if not title or not _same_host(url, page_url):
                continue
            description = _plain_text(job.get("description"), 8000)
            mobility = extract_mobility_statuses(description)
            identifier = job.get("identifier")
            skills = job.get("skills", [])
            if isinstance(skills, str):
                skills = [s.strip() for s in re.split(r"[,;\n]", skills) if s.strip()]
            elif not isinstance(skills, list):
                skills = []
            offers.append({
                "title": title,
                "url": urldefrag(url)[0],
                "company": _text(job.get("hiringOrganization"), 200) or company,
                "location": _location(job),
                "description": description,
                "published_at": _text(job.get("datePosted"), 100),
                "deadline": _text(job.get("validThrough"), 100),
                "skills": [_text(s, 80) for s in skills if _text(s, 80)][:40],
                "employment_type": _text(job.get("employmentType"), 100),
                "source_url": page_url,
                "verification_status": "verified",
                "visa_sponsorship_status": mobility["visa_sponsorship_status"],
                "relocation_support_status": mobility["relocation_support_status"],
                "senegal_eligibility_status": mobility["senegal_eligibility_status"],
                "evidence_url": page_url,
            })
    return offers


def extract_recruiter_profile(source, page_url, parser):
    """Extrait les coordonnées explicitement publiées sur une page autorisée."""
    website = _text(source.get("website"), 1000)
    name = _text(source.get("name"), 200)
    country = _text(source.get("country"), 200)
    visible_text = getattr(parser, "visible_text", "")

    emails = []
    phones = []
    linkedin_url = ""
    contact_url = ""

    for href in getattr(parser, "links", []):
        href = href.strip()
        lower = href.lower()

        if lower.startswith("mailto:"):
            candidate = href[7:].split("?", 1)[0].strip()
            if re.fullmatch(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", candidate, re.I):
                emails.append(candidate)

        elif lower.startswith("tel:"):
            candidate = href[4:].split("?", 1)[0].strip()
            normalized = re.sub(r"[^\d+]", "", candidate)
            if re.fullmatch(r"\+?\d{7,15}", normalized):
                phones.append(normalized)

        else:
            absolute = urljoin(page_url, href)
            parsed = urlparse(absolute)

            if (
                parsed.scheme == "https"
                and parsed.hostname
                and (
                    parsed.hostname.lower() == "linkedin.com"
                    or parsed.hostname.lower().endswith(".linkedin.com")
                )
                and parsed.username is None
                and parsed.password is None
                and not linkedin_url
            ):
                linkedin_url = urldefrag(absolute)[0]

            if _same_host(absolute, website):
                path = parsed.path.lower()
                if any(token in path for token in (
                    "contact", "about-us", "about", "team",
                    "recruitment", "recruiter",
                )):
                    if not contact_url or "contact" in path:
                        contact_url = urldefrag(absolute)[0]

    # Ne retenir qu'une adresse e-mail plausible affichée sur la page.
    email_pattern = r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
    for candidate in re.findall(email_pattern, visible_text, re.I):
        if candidate not in emails:
            emails.append(candidate)

    specialties = []
    known_terms = [
        ("Java", r"\bjava\b"),
        ("Spring Boot", r"\bspring\s*boot\b"),
        ("Software Engineering", r"software engineering"),
        ("IT Recruitment", r"\bit recruitment\b"),
        ("Technology Recruitment", r"technology recruitment"),
        ("Technology", r"\btechnology\b"),
        ("Telecommunications", r"\btelecommunications?\b|\btelecoms?\b"),
        ("Engineering", r"\bengineering\b"),
        ("Remote", r"\bremote\b"),
        ("Flutter", r"\bflutter\b"),
        ("React", r"\breact(?:\.js)?\b"),
        ("Python", r"\bpython\b"),
    ]
    for label, pattern in known_terms:
        if re.search(pattern, visible_text, re.I) and label not in specialties:
            specialties.append(label)

    return {
        "name": name,
        "website": website,
        "country": country,
        "specialties": specialties,
        "contact_name": "",
        "contact_role": "",
        "contact_email": emails[0] if emails else "",
        "contact_phone": phones[0] if phones else "",
        "linkedin_url": linkedin_url,
        "contact_url": contact_url,
        "source_url": page_url,
    }


def _robots(client, origin):
    url = origin.rstrip("/") + "/robots.txt"
    try:
        response = client.get(url, follow_redirects=False)
        if response.status_code != 200 or len(response.content) > 200_000:
            # If robots.txt cannot be checked, do not crawl that host.
            return None
        lines = response.text.splitlines()
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(url)
        parser.parse(lines)
        # Conserver les directives Sitemap déjà récupérées, sans relire robots.txt.
        parser.sitemaps = [
            line.split(":", 1)[1].strip()
            for line in lines
            if line.lower().startswith("sitemap:")
            and line.split(":", 1)[1].strip()
        ]
        return parser
    except (httpx.HTTPError, ValueError):
        return None


def _fetch(client, url, robots):
    if robots is None or not robots.can_fetch(USER_AGENT, url):
        return None
    try:
        response = client.get(url, follow_redirects=False)
        if response.status_code != 200 or len(response.content) > MAX_BYTES:
            return None
        if not _same_host(str(response.url), url):
            return None
        time.sleep(REQUEST_DELAY_SECONDS)
        return response
    except (httpx.HTTPError, ValueError):
        return None


def _sitemap_urls(client, origin, robots, seed):
    """Read sitemap locations declared in robots.txt, then common sitemap paths."""
    candidates = list(getattr(robots, "sitemaps", []))
    candidates.extend([
        origin.rstrip("/") + "/sitemap.xml",
        origin.rstrip("/") + "/sitemap_index.xml",
    ])

    urls = []
    for sitemap in dict.fromkeys(candidates):
        if not _same_host(sitemap, seed):
            continue
        response = _fetch(client, sitemap, robots)
        if not response or not response.text.lstrip().startswith("<"):
            continue
        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError:
            continue
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] == "loc" and node.text:
                item = node.text.strip()
                if _same_host(item, seed):
                    path = urlparse(item).path.lower()
                    looks_like_job = any(token in path for token in (
                        "/jobs/", "/job/", "/vacature/", "/vacatures/",
                        "/careers/jobs/", "/positions/",
                    ))
                    if looks_like_job:
                        urls.append(item)
    return urls


def collect_official_jobpostings(sources=None, client=None):
    """Collecte bornée des offres structurées accessibles publiquement."""
    sources = SOURCES if sources is None else sources
    owns_client = client is None
    if owns_client:
        client = httpx.Client(
            timeout=12,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml"},
            follow_redirects=False,
        )

    results = []
    profiles_by_website = {}
    errors = []
    total_pages_discovered = 0
    try:
        for source in sources:
            seed = source["seed"]
            origin = f"https://{urlparse(seed).hostname}"
            if not _same_host(seed, source["website"]):
                errors.append(f'{source["name"]}: URL hors domaine autorisé')
                continue

            robots = _robots(client, origin)
            if robots is None:
                errors.append(f'{source["name"]}: robots.txt inaccessible, collecte ignorée')
                continue

            # Traiter d'abord la page de départ et ses liens directs.
            # Les URL de sitemap sont ajoutées ensuite, pour ne pas saturer
            # la limite de pages avec des pages sans rapport avec des offres.
            candidates = [seed]
            sitemap_candidates = _sitemap_urls(client, origin, robots, seed)
            visited = set()

            for url in candidates:
                url = urldefrag(url)[0]
                if url in visited or len(visited) >= MAX_PAGES_PER_SOURCE:
                    continue
                if not _same_host(url, seed):
                    continue
                visited.add(url)
                total_pages_discovered += 1

                response = _fetch(client, url, robots)
                if not response:
                    continue
                content_type = response.headers.get("content-type", "").lower()
                if "html" not in content_type and "<html" not in response.text[:1000].lower():
                    continue

                parser = PageParser()
                try:
                    parser.feed(response.text)
                except Exception:
                    continue

                # Le profil est collecté même si la page ne contient aucune offre.
                profile = extract_recruiter_profile(source, url, parser)
                profile_key = profile["website"].rstrip("/").lower()
                if profile_key:
                    previous = profiles_by_website.get(profile_key, {})
                    merged = dict(previous)
                    for key, value in profile.items():
                        if key == "specialties":
                            merged[key] = list(dict.fromkeys(
                                (previous.get(key, []) or []) + (value or [])
                            ))
                        elif value and (not merged.get(key) or key == "source_url"):
                            merged[key] = value
                    profiles_by_website[profile_key] = merged

                results.extend(
                    {**offer, "recruiter": source}
                    for offer in extract_jobpostings(
                        parser.jsonld, url, source["name"]
                    )
                )

                # Follow only links explicitly resembling individual job pages.
                for href in parser.links:
                    link = urldefrag(urljoin(url, href))[0]
                    path = urlparse(link).path.lower()
                    looks_like_job = (
                        _same_host(link, seed)
                        and any(token in path for token in (
                            "/jobs/", "/job/", "/vacature/", "/vacatures/",
                            "/careers/jobs/", "/positions/",
                        ))
                    )
                    if looks_like_job and link not in visited and link not in candidates:
                        candidates.append(link)

                if url == seed:
                    for sitemap_url in sitemap_candidates:
                        if sitemap_url not in visited and sitemap_url not in candidates:
                            candidates.append(sitemap_url)
    finally:
        if owns_client:
            client.close()

    unique = {}
    for offer in results:
        unique[offer["url"]] = offer
    return {
        "status": "success",
        "offers": list(unique.values()),
        "recruiters": list(profiles_by_website.values()),
        "pages_discovered": total_pages_discovered,
        "errors": errors,
    }
