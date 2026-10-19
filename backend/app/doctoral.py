"""Collecte prudente et suivi des offres doctorales."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import os
import re
import sqlite3
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv(
    "JOBHUNTER_DB",
    str(Path(__file__).resolve().parents[1] / "jobhunter.db"),
))

router = APIRouter(prefix="/api/doctorates", tags=["Doctorats"])

FUNDING_STATUSES = {
    "CONFIRMED_FULL", "PARTIAL", "UNCONFIRMED", "UNKNOWN"
}
APPLICATION_STATUSES = {
    "À examiner", "Favori", "Candidature préparée",
    "Candidature envoyée", "Entretien", "Refus", "Acceptée",
}


ACADEMIC_CATEGORIES = {
    "doctorats", "masters", "aides", "recherche", "uncategorized",
}


def infer_academic_category(title, description=""):
    """Classe une opportunité selon des indices explicites."""
    title_text = re.sub(r"\s+", " ", str(title or "")).strip().lower()
    description_text = re.sub(
        r"\s+", " ", str(description or "")
    ).strip().lower()
    combined = title_text + " " + description_text

    if re.search(
        r"\b(postdoc|post-doc|postdoctoral|post-doctoral|"
        r"assistant professor|associate professor|full professor|"
        r"lecturer|faculty position|professor position|research fellow|"
        r"researcher position|research scientist|pre-doc)\b",
        title_text,
    ):
        return "recherche"

    if re.search(
        r"\b(master'?s?|msc|m\.sc\.?|ma degree|m\.a\.? degree|"
        r"mba|graduate master)\b",
        title_text,
    ):
        return "masters"

    if re.search(
        r"\b(ph\.?d\.?|phd|doctoral|doctorate|doctorat|doctorant|"
        r"doctorante|thesis|theses|thèse|thèses|studentship)\b",
        title_text,
    ):
        return "doctorats"

    if re.search(
        r"\b(postdoc|post-doc|postdoctoral|post-doctoral|"
        r"assistant professor|associate professor|full professor|"
        r"lecturer|faculty position|research fellow|researcher position|"
        r"research scientist|pre-doc)\b",
        combined,
    ):
        return "recherche"

    if re.search(
        r"\b(master'?s?|msc|m\.sc\.?|ma degree|m\.a\.? degree|"
        r"mba|graduate master)\b",
        combined,
    ):
        return "masters"

    if re.search(
        r"\b(ph\.?d\.?|phd|doctoral|doctorate|doctorat|doctorant|"
        r"doctorante|thesis|theses|thèse|thèses|doctoral programme|"
        r"doctoral program|studentship)\b",
        combined,
    ):
        return "doctorats"

    if re.search(
        r"\b(scholarship|scholarships|fellowship|fellowships|bourse|"
        r"bourses|grant|grants|financial aid|financial support|"
        r"mobility grant|travel grant|stipend|tuition waiver|student aid|"
        r"award|bursary)\b",
        combined,
    ):
        return "aides"

    return "uncategorized"

def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    return db


def init_doctoral_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS doctoral_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                institution TEXT NOT NULL DEFAULT 'Non précisée',
                country TEXT NOT NULL DEFAULT 'Non précisé',
                location TEXT NOT NULL DEFAULT '',
                field TEXT NOT NULL DEFAULT 'Non précisé',
                description TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'Ajout manuel',
                funding_status TEXT NOT NULL DEFAULT 'UNKNOWN',
                funding_type TEXT NOT NULL DEFAULT '',
                salary_amount REAL,
                salary_currency TEXT NOT NULL DEFAULT '',
                salary_period TEXT NOT NULL DEFAULT '',
                duration_months INTEGER,
                tuition_status TEXT NOT NULL DEFAULT 'Inconnu',
                eligibility TEXT NOT NULL DEFAULT '',
                deadline TEXT,
                published_at TEXT,
                collected_at TEXT NOT NULL,
                last_checked_at TEXT,
                application_status TEXT NOT NULL DEFAULT 'À examiner',
                funding_evidence TEXT NOT NULL DEFAULT '',
                is_favorite INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
        """)
        columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(doctoral_offers)")
        }
        if "opportunity_type" not in columns:
            db.execute(
                "ALTER TABLE doctoral_offers "
                "ADD COLUMN opportunity_type TEXT NOT NULL "
                "DEFAULT 'uncategorized'"
            )
            rows = db.execute(
                "SELECT id, title, description FROM doctoral_offers"
            ).fetchall()
            for row in rows:
                category = infer_academic_category(
                    row["title"], row["description"]
                )
                db.execute(
                    "UPDATE doctoral_offers SET opportunity_type=? WHERE id=?",
                    (category, row["id"]),
                )

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_doctoral_collected
            ON doctoral_offers(collected_at)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_doctoral_funding
            ON doctoral_offers(funding_status)
        """)
        db.commit()



def classify_funding(text):
    """Classe prudemment le financement à partir d'indices explicites."""
    value = re.sub(r"\s+", " ", (text or "").lower()).strip()

    # Cette mention concerne le programme européen, pas le financement
    # du doctorant : elle ne doit pas annuler les autres indices.
    value = re.sub(
        r"not funded by (?:a|an|the) eu programme",
        "",
        value,
    )
    value = value.replace("not funded by the eu", "")

    partial = (
        "partially funded", "partially-funded",
        "partial funding", "funding is partial",
        "financement partiel", "partiellement financé",
        "partiellement financée",
        "tuition fees only",
        "only tuition fees are covered",
        "only covers tuition fees",
        "tuition fees are covered only",
        "frais de scolarité uniquement",
    )
    full = (
        "fully funded", "fully-funded",
        "all tuition fees and living costs",
        "entièrement financé", "entièrement financée",
        "financement intégral", "financement complet",
        "salaire et frais de scolarité pris en charge",
    )
    uncertain = (
        "scholarship", "studentship", "stipend",
        "funding available", "bourse disponible",
        "annual salary", "salary of", "gross salary",
        "yearly salary", "monthly salary", "paid position",
        "remuneration", "salaire annuel", "salaire mensuel",
        "contrat doctoral", "doctorat financé",
        "financement disponible", "funded phd",
        "funded studentship", "salary",
    )

    # Une négation explicite interdit de conclure à un financement intégral.
    full_negations = (
        r"\bnot\s+(?:fully|entirely|completely)\s+funded\b",
        r"\bnot\s+fully-funded\b",
        r"\bnot\s+fully\s+financed\b",
        r"\bno\s+full\s+funding\b",
        r"\bfinancement\s+intégral\s+non\s+garanti\b",
        r"\bpas\s+entièrement\s+financé[e]?\b",
        r"\bnon\s+entièrement\s+financé[e]?\b",
    )
    if any(re.search(pattern, value) for pattern in full_negations):
        return "UNCONFIRMED"

    if any(term in value for term in partial):
        return "PARTIAL"

    if any(term in value for term in full):
        return "CONFIRMED_FULL"

    if any(term in value for term in uncertain):
        return "UNCONFIRMED"

    return "UNKNOWN"

def funding_evidence_excerpt(text):
    """Extrait un indice pertinent sans confondre programme UE et financement doctoral."""
    import re

    value = re.sub(r"\s+", " ", text or "").strip()

    # Ce libellé concerne le programme européen, pas le financement du candidat.
    value = re.sub(
        r"(?:funding\s+programme\s*:\s*)?"
        r"not funded by (?:a|an|the) eu programme",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"not funded by the eu",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+", " ", value).strip(" :-|")

    terms = (
        "partially funded", "partial funding", "fully funded",
        "fully-funded", "all tuition fees and living costs",
        "entièrement financé", "entièrement financée",
        "financement intégral", "financement complet",
        "tuition fees only", "frais de scolarité uniquement",
        "salary of", "annual salary", "yearly salary",
        "monthly salary", "gross salary", "paid position",
        "remuneration", "salaire annuel", "salaire mensuel",
        "contrat doctoral", "doctorat financé",
        "scholarship", "studentship", "stipend",
        "funding available", "funded phd",
        "bourse disponible", "bourse doctorale",
        "financement disponible",
    )

    lower = value.lower()
    positions = [
        (lower.find(term), term)
        for term in terms
        if lower.find(term) >= 0
    ]
    if not positions:
        return ""

    position, _ = min(positions)
    return value[max(0, position - 100):position + 220].strip()

def configured_feeds():
    """Format : Nom=https://flux ; autre nom=https://autre-flux"""
    raw = os.getenv("DOCTORAL_FEEDS", "")
    result = []
    for item in raw.split(";"):
        if "=" not in item:
            continue
        name, url = item.split("=", 1)
        name, url = name.strip(), url.strip()
        if name and url:
            result.append({"name": name[:150], "url": url})
    return result


def validate_feed_url(url):
    """Valide une URL HTTPS dont le domaine est explicitement autorisé."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL de flux absente ou invalide.")

    parsed = urlparse(url.strip())

    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Le flux doit utiliser HTTPS avec un domaine valide.")

    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Les identifiants intégrés dans l'URL sont refusés.")

    if parsed.fragment:
        raise ValueError("Les fragments d'URL sont refusés.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Port URL invalide.") from exc

    if port not in (None, 443):
        raise ValueError("Seul le port HTTPS standard 443 est autorisé.")

    host = parsed.hostname.lower().rstrip(".")

    if not host or host == "localhost" or host.endswith(
        (".localhost", ".local", ".internal", ".test")
    ):
        raise ValueError("Hôte local ou réservé refusé.")

    # Les adresses IP littérales sont refusées : seuls les domaines
    # explicitement approuvés peuvent être utilisés comme sources.
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Les adresses IP littérales sont refusées.")

    allowed_hosts = {
        item.strip().lower().rstrip(".")
        for item in re.split(
            r"[,;]", os.getenv("DOCTORAL_ALLOWED_FEED_HOSTS", "")
        )
        if item.strip()
    }

    if not allowed_hosts:
        raise ValueError(
            "Aucun domaine autorisé : configurez "
            "DOCTORAL_ALLOWED_FEED_HOSTS."
        )

    if host not in allowed_hosts:
        raise ValueError("Domaine absent de la liste des sources autorisées.")

    return url.strip()

def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element, *names):
    wanted = set(names)
    for child in element.iter():
        if local_name(child.tag) in wanted:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def is_doctoral_offer(title, description=""):
    """Filtre les offres doctorales et exclut les emplois postdoctoraux."""
    title_text = re.sub(r"\s+", " ", title or "").strip().casefold()
    text = re.sub(
        r"\s+", " ", f"{title or ''} {description or ''}"
    ).casefold()

    # Les postes postdoctoraux ne sont pas des offres de doctorat.
    if re.search(r"\bpost[- ]?doc(?:toral)?\b|\bpost-doctorate\b",
                 title_text):
        return False

    # Exclure les postes d'enseignement ordinaires.
    if re.search(
        r"^(?:(?:assistant|associate|full|adjunct|visiting|senior)\s+)?"
        r"(?:professor|lecturer)\b",
        title_text,
    ):
        return False

    doctoral_terms = (
        "phd", "ph.d", "doctoral position", "doctoral researcher",
        "doctoral student", "doctoral candidate", "doctorate",
        "doctorant", "doctorat", "thèse de doctorat",
        "doctoral fellowship", "phd position", "phd opportunity",
        "pursue a phd", "position is for a phd",
    )
    return any(term in text for term in doctoral_terms)


def extract_deadline(text):
    """Extrait uniquement une date précédée d'un libellé d'échéance."""
    if not text:
        return None

    value = re.sub(r"<[^>]*>", " ", str(text))
    value = re.sub(r"\s+", " ", value).strip()

    label = re.compile(
        r"(?:application\s+deadline|application\s+closing\s+date|"
        r"closing\s+date|deadline\s+for\s+applications|"
        r"deadline|date\s+limite\s+de\s+candidature|"
        r"date\s+limite|date\s+de\s+clôture)"
        r"\s*:?\s*",
        re.IGNORECASE,
    )
    match = label.search(value)
    if not match:
        return None

    candidate = value[match.end():match.end() + 100].strip()
    candidate = re.split(
        r"[\n;|]|(?:\s{2,})|(?:\s+(?:please|applications?\s+must|"
        r"for\s+more\s+information)\b)",
        candidate,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .,:-")

    # Formats numériques non ambigus et mois écrits en anglais.
    formats = (
        "%Y-%m-%d", "%d %B %Y", "%d %b %Y",
        "%B %d, %Y", "%b %d, %Y",
        "%d/%m/%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # ISO datetime : ne conserver que la date validée.
    iso = re.match(r"(\d{4}-\d{2}-\d{2})(?:[T ]|$)", candidate)
    if iso:
        try:
            return datetime.strptime(iso.group(1), "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def parse_feed(xml_text, source):
    """Lit les flux RSS/Atom en refusant les déclarations XML dangereuses."""
    if isinstance(xml_text, str):
        xml_bytes = xml_text.encode("utf-8")
    elif isinstance(xml_text, bytes):
        xml_bytes = xml_text
    else:
        return []

    # Les flux RSS/Atom n'ont pas besoin de DTD ni d'entités déclarées.
    # Le contrôle est volontairement conservateur et indépendant de la casse.
    if re.search(
        rb"<!\s*(?:DOCTYPE|ENTITY)\b",
        xml_bytes,
        flags=re.IGNORECASE,
    ):
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except (ET.ParseError, ValueError):
        return []

    entries = [
        element for element in root.iter()
        if local_name(element.tag) in {"item", "entry"}
    ]
    results = []

    for entry in entries:
        title = child_text(entry, "title")
        description = child_text(
            entry, "description", "summary", "content", "encoded"
        )
        link = ""
        for element in entry.iter():
            if local_name(element.tag) == "link":
                href = element.attrib.get("href", "").strip()
                rel = element.attrib.get("rel", "alternate")
                if href and rel == "alternate":
                    link = href
                    break
                if href and not link:
                    link = href
                if element.text and element.text.strip():
                    link = element.text.strip()
                    break

        published = child_text(
            entry, "pubdate", "published", "updated", "date"
        )
        if published:
            try:
                published = parsedate_to_datetime(published).isoformat()
            except (TypeError, ValueError, OverflowError):
                try:
                    published = datetime.fromisoformat(
                        published.replace("Z", "+00:00")
                    ).isoformat()
                except ValueError:
                    pass

        if not title:
            continue

        combined = f"{title}\n{description}"
        results.append({
            "title": title[:500],
            "institution": "Non précisée",
            "country": "Non précisé",
            "location": "",
            "field": infer_field(combined),
            "description": description[:12000],
            "url": link[:2000],
            "source": source[:150],
            "funding_status": classify_funding(combined),
            "funding_evidence": evidence_excerpt(combined),
            "deadline": extract_deadline(description),
            "published_at": published or None,
        })

    return results


def infer_field(text):
    value = (text or "").lower()
    areas = [
        ("IA / Machine Learning", ("artificial intelligence", "machine learning", "intelligence artificielle", "apprentissage automatique", "deep learning", "llm", "natural language processing", "rag ")),
        ("Informatique / Génie logiciel", ("computer science", "software engineering", "informatique", "génie logiciel", "distributed systems", "cybersecurity", "cybersécurité")),
        ("Mathématiques / Optimisation / Quantique", ("quantum", "quantique", "optimization", "optimisation", "algorithms", "algorithmes")),
    ]
    for label, terms in areas:
        if any(term in value for term in terms):
            return label
    return "Autre / À classifier"


def evidence_excerpt(text):
    value = re.sub(r"\s+", " ", text or "").strip()
    patterns = (
        "fully funded", "fully-funded", "full funding",
        "entièrement financé", "entièrement financée",
        "financement intégral", "financement complet",
        "partially funded", "financement partiel",
    )
    lower = value.lower()
    for term in patterns:
        position = lower.find(term)
        if position >= 0:
            return value[max(0, position - 100):position + 250]
    return ""


class DoctorateIn(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    institution: str = Field(default="Non précisée", max_length=250)
    country: str = Field(default="Non précisé", max_length=150)
    location: str = Field(default="", max_length=250)
    field: str = Field(default="Non précisé", max_length=200)
    description: str = Field(default="", max_length=20000)
    url: str = Field(default="", max_length=2000)
    source: str = Field(default="Ajout manuel", max_length=150)
    funding_status: str = "UNKNOWN"
    funding_type: str = ""
    salary_amount: float | None = None
    salary_currency: str = ""
    salary_period: str = ""
    duration_months: int | None = None
    tuition_status: str = "Inconnu"
    eligibility: str = ""
    deadline: str | None = None
    published_at: str | None = None
    funding_evidence: str = ""
    opportunity_type: str | None = None


class DoctorateUpdate(BaseModel):
    application_status: str | None = None
    is_favorite: bool | None = None
    opportunity_type: str | None = None


def save_offer(offer):
    title = str(offer.get("title") or "").strip()
    if not title:
        raise ValueError("Titre de l'offre obligatoire")

    # Aligner les données collectées sur les contraintes NOT NULL
    # de la base existante, sans inventer de salaire ni de devise.
    defaults = {
        "institution": "Non précisée",
        "country": "Non précisé",
        "location": "",
        "field": "Non précisé",
        "description": "",
        "url": "",
        "source": "Ajout manuel",
        "funding_status": "UNKNOWN",
        "funding_type": "",
        "salary_amount": None,
        "salary_currency": "",
        "salary_period": "",
        "duration_months": None,
        "tuition_status": "Inconnu",
        "eligibility": "",
        "deadline": None,
        "published_at": None,
        "funding_evidence": "",
        "opportunity_type": None,
    }
    normalized = dict(defaults)
    normalized.update(offer)
    normalized["title"] = title

    category = normalized.get("opportunity_type")
    if category not in ACADEMIC_CATEGORIES:
        category = infer_academic_category(
            normalized["title"], normalized.get("description", "")
        )
    normalized["opportunity_type"] = category

    # Les colonnes textuelles obligatoires ne doivent jamais recevoir None.
    for key in (
        "institution", "country", "location", "field", "description",
        "url", "source", "funding_status", "funding_type",
        "salary_currency", "salary_period", "tuition_status",
        "eligibility", "funding_evidence",
    ):
        if normalized.get(key) is None:
            normalized[key] = defaults[key]

    url = str(normalized.get("url") or "").strip()
    identity = url.lower() if url else (
        title.lower() + "|" + str(normalized.get("institution") or "").lower()
        + "|" + str(normalized.get("country") or "").lower()
    )
    digest = sha256(identity.encode("utf-8")).hexdigest()
    timestamp = now()

    columns = [
        "title", "institution", "country", "location", "field",
        "description", "url", "source", "funding_status", "funding_type",
        "salary_amount", "salary_currency", "salary_period",
        "duration_months", "tuition_status", "eligibility", "deadline",
        "published_at", "collected_at", "last_checked_at",
        "funding_evidence", "opportunity_type",
        "content_hash", "created_at",
    ]
    values = [normalized.get(key) for key in columns]
    values[columns.index("collected_at")] = timestamp
    values[columns.index("last_checked_at")] = timestamp
    values[columns.index("content_hash")] = digest
    values[columns.index("created_at")] = timestamp

    with connect() as db:
        existing = db.execute(
            "SELECT id, description FROM doctoral_offers WHERE content_hash=?",
            (digest,),
        ).fetchone()
        if existing:
            # Actualiser les doublons sans effacer les données existantes
            # lorsqu'une collecte ne fournit pas de nouvelle valeur.
            db.execute(
                """UPDATE doctoral_offers
                   SET last_checked_at=?, source=?
                   WHERE id=?""",
                (timestamp, normalized.get("source", ""), existing["id"]),
            )

            refresh_fields = (
                "institution", "country", "location", "field",
                "description", "funding_type", "eligibility",
                "deadline", "published_at",
            )
            assignments = []
            params = []

            # Actualiser les champs descriptifs uniquement si la collecte
            # apporte une valeur exploitable.
            for field_name in refresh_fields:
                value = normalized.get(field_name)
                if value is None or value == "":
                    continue

                # Ne pas remplacer une description détaillée
                # par une carte de recherche plus courte.
                if field_name == "description":
                    previous = existing["description"] or ""
                    if len(str(value)) < len(previous):
                        continue

                assignments.append(f"{field_name}=?")
                params.append(value)

            # Enrichir les informations financières sans effacer
            # les valeurs déjà présentes lorsqu'elles sont absentes.
            for field_name in (
                "salary_amount", "salary_currency",
                "salary_period", "duration_months",
            ):
                value = normalized.get(field_name)
                if value is not None and value != "":
                    assignments.append(f"{field_name}=?")
                    params.append(value)

            # Une valeur inconnue ne remplace pas une information connue.
            tuition_value = normalized.get("tuition_status")
            if tuition_value and str(tuition_value).strip().casefold() not in (
                "inconnu", "unknown", "non précisé", "not specified",
            ):
                assignments.append("tuition_status=?")
                params.append(tuition_value)

            # UNKNOWN et une preuve vide ne doivent pas écraser
            # une information de financement déjà plus précise.
            new_status = normalized.get("funding_status")
            new_evidence = normalized.get("funding_evidence")
            if new_status in ("CONFIRMED_FULL", "PARTIAL"):
                assignments.append("funding_status=?")
                params.append(new_status)
            elif new_status == "UNCONFIRMED":
                assignments.append(
                    "funding_status=CASE "
                    "WHEN funding_status IN ('CONFIRMED_FULL','PARTIAL') "
                    "THEN funding_status ELSE ? END"
                )
                params.append(new_status)

            if new_evidence:
                assignments.append("funding_evidence=?")
                params.append(new_evidence)

            if assignments:
                params.append(existing["id"])
                db.execute(
                    "UPDATE doctoral_offers SET "
                    + ", ".join(assignments)
                    + " WHERE id=?",
                    params,
                )

            db.commit()
            return False

        placeholders = ",".join("?" for _ in columns)
        db.execute(
            f"INSERT INTO doctoral_offers ({','.join(columns)}) "
            f"VALUES ({placeholders})", values
        )
        db.commit()
    return True


@router.get("/sources")
def list_sources():
    # Collecteur EURAXESS désactivé : robots.txt interdit les chemins
    # de recherche et les fiches utilisés par l'ancien collecteur.
    sources = [{
        "name": "EURAXESS (historique — collecte suspendue)",
        "url": EURAXESS_SEARCH_URL,
        "configured": False,
        "type": "Historique conservé — collecte non active (robots.txt)",
    }]

    sources.append({
        "name": CAMPUS_FRANCE_SOURCE,
        "url": "https://doctorat.campusfrance.org/fr/phd/offers",
        "configured": True,
        "type": "API JSON + fiches officielles",
    })

    sources.extend([
        {
            "name": "France Excellence Eiffel — Campus France",
            "url": EIFFEL_CAMPUS_FRANCE_URL,
            "configured": True,
            "type": "Page officielle de campagne — bourse",
        },
        {
            "name": "France Excellence Eiffel — Université Paris-Saclay",
            "url": EIFFEL_PARIS_SACLAY_URL,
            "configured": True,
            "type": "Page officielle universitaire — bourse",
        },
    ])

    sources.extend(
        {
            "name": feed["name"],
            "url": feed["url"],
            "configured": True,
            "type": "RSS/Atom",
        }
        for feed in configured_feeds()
    )
    return sources


@router.get("")
def list_doctorates(
    q: str = Query(default="", max_length=300),
    country: str = Query(default="", max_length=150),
    field: str = Query(default="", max_length=200),
    funding_status: str = "",
    application_status: str = "",
    recent_days: int = Query(default=0, ge=0, le=3650),
    favorites_only: bool = False,
):
    if funding_status and funding_status not in FUNDING_STATUSES:
        raise HTTPException(400, "Statut de financement invalide.")
    if application_status and application_status not in APPLICATION_STATUSES:
        raise HTTPException(400, "Statut de candidature invalide.")

    with connect() as db:
        rows = db.execute(
            "SELECT * FROM doctoral_offers ORDER BY collected_at DESC, id DESC"
        ).fetchall()

    offers = [dict(row) for row in rows]

    # Conserver toutes les opportunités enregistrées, y compris les
    # annonces historiques qui ne sont pas des doctorats explicites.
    if q:
        needle = q.casefold()
        offers = [
            item for item in offers
            if needle in " ".join(str(item.get(key) or "") for key in (
                "title", "institution", "country", "field",
                "description", "funding_evidence"
            )).casefold()
        ]
    if country:
        offers = [o for o in offers if country.casefold() in
                  (o.get("country") or "").casefold()]
    if field:
        offers = [o for o in offers if field.casefold() in
                  (o.get("field") or "").casefold()]
    if funding_status:
        offers = [o for o in offers if o["funding_status"] == funding_status]
    if application_status:
        offers = [o for o in offers if o["application_status"] == application_status]
    if favorites_only:
        offers = [o for o in offers if o["is_favorite"]]
    if recent_days:
        cutoff = datetime.now(timezone.utc).timestamp() - recent_days * 86400
        filtered = []
        for offer in offers:
            try:
                stamp = datetime.fromisoformat(
                    (offer.get("collected_at") or "").replace("Z", "+00:00")
                ).timestamp()
                if stamp >= cutoff:
                    filtered.append(offer)
            except (ValueError, TypeError, OverflowError):
                continue
        offers = filtered
    return offers


@router.post("", status_code=201)
def create_doctorate(offer: DoctorateIn):
    payload = offer.model_dump()
    payload["title"] = payload["title"].strip()
    if payload["funding_status"] not in FUNDING_STATUSES:
        raise HTTPException(400, "Statut de financement invalide.")
    if payload["url"]:
        parsed = urlparse(payload["url"])
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise HTTPException(400, "URL invalide.")
    try:
        inserted = save_offer(payload)
    except sqlite3.IntegrityError:
        inserted = False
    with connect() as db:
        identity = payload["url"].lower() if payload["url"] else (
            payload["title"].lower() + "|" +
            payload["institution"].lower() + "|" + payload["country"].lower()
        )
        digest = sha256(identity.encode("utf-8")).hexdigest()
        row = db.execute(
            "SELECT * FROM doctoral_offers WHERE content_hash=?", (digest,)
        ).fetchone()
    return {"inserted": inserted, "offer": dict(row) if row else None}


@router.patch("/{doctorate_id}")
def update_doctorate(doctorate_id: int, update: DoctorateUpdate):
    changes = update.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(400, "Aucune modification fournie.")
    if "application_status" in changes and changes["application_status"] not in APPLICATION_STATUSES:
        raise HTTPException(400, "Statut de candidature invalide.")
    if (
        "opportunity_type" in changes
        and changes["opportunity_type"] not in ACADEMIC_CATEGORIES
    ):
        raise HTTPException(400, "Catégorie académique invalide.")
    with connect() as db:
        row = db.execute(
            "SELECT id FROM doctoral_offers WHERE id=?", (doctorate_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Doctorat introuvable.")
        for key, value in changes.items():
            if key == "is_favorite":
                value = int(value)
            db.execute(
                f"UPDATE doctoral_offers SET {key}=? WHERE id=?",
                (value, doctorate_id),
            )
        db.commit()
        result = db.execute(
            "SELECT * FROM doctoral_offers WHERE id=?", (doctorate_id,)
        ).fetchone()
    return dict(result)


EURAXESS_SEARCH_URL = "https://euraxess.ec.europa.eu/jobs/search"
EURAXESS_BASE_URL = "https://euraxess.ec.europa.eu"
EURAXESS_MAX_DETAILS = 12


def euraxess_field(lines, label):
    """Extrait prudemment une valeur affichée après un libellé."""
    wanted = re.sub(r"\s+", " ", label).strip().lower().rstrip(":")
    for index, line in enumerate(lines):
        current = re.sub(r"\s+", " ", line).strip().lower().rstrip(":")
        if current == wanted and index + 1 < len(lines):
            value = lines[index + 1].strip()
            if value and len(value) < 1000:
                return value
    return ""



def euraxess_is_doctoral(title, text):
    """Filtre prudemment les offres de doctorat EURAXESS."""
    import re

    value = re.sub(r"\s+", " ", (title or "").lower()).strip()

    excluded = (
        r"^(?:(?:assistant|associate|full|adjunct|visiting)\s+)?professor\b",
        r"^(?:senior\s+)?lecturer\b",
        r"\bpost[- ]?doc(?:toral)?\b",
        r"\bpost-doctorate\b",
    )
    if any(re.search(pattern, value) for pattern in excluded):
        return False

    explicit_doctoral_terms = (
        "phd", "ph.d", "doctoral", "doctorate", "doctorant", "doctorat",
    )
    if any(term in value for term in explicit_doctoral_terms):
        return True

    # « pre-doc » seul est ambigu : ne pas le traiter comme un doctorat.
    if re.search(r"\bpre[- ]?doc(?:toral)?\b", value):
        return False

    return False

def euraxess_date(value):
    """Normalise les dates courantes sans inventer de date ni de fuseau."""
    import re
    from datetime import datetime
    from email.utils import parsedate_to_datetime

    if not value:
        return None

    raw = re.sub(r"\s+", " ", str(value)).strip()

    # Exemples : 28 Oct 2026 - 23:59 (Europe/Lisbon)
    match = re.search(
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"
        r"(?:\s*[-–,]?\s*(\d{1,2}:\d{2}))?"
        r"(?:\s*\(([^)]+)\))?",
        raw,
    )
    if match:
        date_text, time_text, timezone_text = match.groups()
        parsed = None
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                parsed = datetime.strptime(date_text, fmt)
                break
            except ValueError:
                continue

        if parsed:
            result = parsed.strftime("%Y-%m-%d")
            if time_text:
                result += "T" + time_text
            if timezone_text:
                result += f" ({timezone_text})"
            return result

    try:
        return datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        ).isoformat()
    except ValueError:
        pass

    try:
        return parsedate_to_datetime(raw).isoformat()
    except (TypeError, ValueError, OverflowError):
        return raw[:200]


async def sync_euraxess(client):
    """Collecte les annonces EURAXESS et enrichit les fiches accessibles."""
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup
    import httpx

    inserted = duplicates = skipped = 0
    errors = []

    def value_after_label(text, label, stop_labels):
        pattern = re.escape(label) + r"\s*:?\s*"
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None

        remainder = text[match.end():]
        if stop_labels:
            stops = [
                re.escape(item) + r"\s*:"
                for item in stop_labels
            ]
            stop = re.search(
                r"\s+(?:" + "|".join(stops) + r")",
                remainder,
                re.IGNORECASE,
            )
            if stop:
                remainder = remainder[:stop.start()]

        result = remainder.strip(" :-|")
        return result or None

    def extract_salary(text):
        """Retourne un montant uniquement si un montant et une devise sont visibles."""
        patterns = (
            r"(?:salary|stipend|allowance|remuneration|remuneration amount|"
            r"monthly maintenance allowance)"
            r"\s*[:\-]?\s*(€|EUR|£|GBP|NOK|SEK|DKK|CHF|USD)\s*"
            r"([\d][\d\s.,]*)",
            r"(?:salary|stipend|allowance|remuneration|"
            r"monthly maintenance allowance)"
            r"\s*[:\-]?\s*([\d][\d\s.,]*)\s*"
            r"(EUR|GBP|NOK|SEK|DKK|CHF|USD)",
        )

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue

            first, second = match.groups()
            if first.upper() in {
                "EUR", "GBP", "NOK", "SEK", "DKK", "CHF", "USD"
            }:
                currency, raw_amount = first.upper(), second
            elif first in {"€", "£"}:
                currency = {"€": "EUR", "£": "GBP"}[first]
                raw_amount = second
            else:
                raw_amount, currency = first, second.upper()

            normalized = raw_amount.replace(" ", "")
            if "," in normalized and "." in normalized:
                if normalized.rfind(",") > normalized.rfind("."):
                    normalized = normalized.replace(".", "").replace(",", ".")
                else:
                    normalized = normalized.replace(",", "")
            elif "," in normalized:
                tail = normalized.rsplit(",", 1)[-1]
                normalized = (
                    normalized.replace(",", ".")
                    if len(tail) in (1, 2)
                    else normalized.replace(",", "")
                )

            try:
                amount = float(normalized)
            except ValueError:
                continue

            context = text[max(0, match.start() - 100):match.end() + 100].lower()
            if "monthly" in context or "per month" in context:
                period = "month"
            elif "annual" in context or "yearly" in context or "per year" in context:
                period = "year"
            else:
                period = ""

            return amount, currency, period

        return None, "", ""

    def extract_duration(text):
        match = re.search(
            r"\b(?:duration|for a period of|period of)\s*[:\-]?\s*"
            r"(\d{1,2})\s*(months?|years?)\b",
            text,
            re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r"\b(\d{1,2})\s*(months?|years?)\s+"
                r"(?:duration|contract|scholarship)\b",
                text,
                re.IGNORECASE,
            )
        if not match:
            match = re.search(
                r"\b(?:lasts?|duration is|runs for)\s*"
                r"(\d{1,2})\s*(months?|years?)\b",
                text,
                re.IGNORECASE,
            )
        if not match:
            return None

        amount = int(match.group(1))
        return amount * 12 if match.group(2).lower().startswith("year") else amount

    try:
        response = await client.get(EURAXESS_SEARCH_URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        offers = []
        seen_urls = set()

        for anchor in soup.find_all("a", href=True):
            url = urljoin(EURAXESS_BASE_URL, anchor["href"]).rstrip("/")
            if not re.fullmatch(r"https://euraxess\.ec\.europa\.eu/jobs/\d+", url):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = anchor.get_text(" ", strip=True)
            if len(title) < 8:
                continue

            # Extraire uniquement la carte de cette annonce.
            card_node = anchor.find_parent(
                "article", class_="ecl-content-item"
            )
            if card_node is None:
                continue

            card = " ".join(card_node.stripped_strings)
            lower = card.lower()

            if (
                title.lower() in lower
                and "posted on:" in lower
                and (
                    "research field:" in lower
                    or "application deadline:" in lower
                )
            ):
                offers.append((url, title, card))

        for url, title, card in offers:
            try:
                if not euraxess_is_doctoral(title, card):
                    skipped += 1
                    continue

                # Une fiche lente ou inaccessible ne bloque pas les suivantes.
                detail_text = ""
                try:
                    detail_response = await client.get(url, timeout=8)
                    detail_response.raise_for_status()

                    # Ne jamais analyser une page de recherche comme une fiche.
                    expected_url = url.rstrip("/")
                    final_url = str(detail_response.url).rstrip("/")
                    detail_soup = BeautifulSoup(
                        detail_response.text, "html.parser"
                    )

                    canonical_tag = detail_soup.find(
                        "link", rel="canonical"
                    )
                    canonical_url = ""
                    if canonical_tag and canonical_tag.get("href"):
                        canonical_url = urljoin(
                            EURAXESS_BASE_URL,
                            canonical_tag["href"]
                        ).rstrip("/")

                    expected_path = urlparse(expected_url).path
                    final_path = urlparse(final_url).path
                    canonical_path = (
                        urlparse(canonical_url).path
                        if canonical_url else ""
                    )

                    valid_detail = (
                        final_path == expected_path
                        and re.fullmatch(r"/jobs/\d+", final_path)
                        and (
                            not canonical_path
                            or canonical_path == expected_path
                        )
                    )

                    if not valid_detail:
                        # La carte reste exploitable même si la fiche
                        # détaillée est inaccessible ou redirigée.
                        errors.append(
                            f"{url}: fiche détaillée indisponible "
                            f"(URL finale: {final_url}; "
                            f"canonique: {canonical_url or 'absente'}). "
                            "Annonce conservée à partir de la carte."
                        )
                    else:
                        # Extraire uniquement les sections de cette fiche.
                        section_ids = (
                            "job-information",
                            "offer-description",
                            "requirements",
                            "additional-information",
                            "work-locations",
                        )
                        sections = []
                        for section_id in section_ids:
                            heading = detail_soup.find(id=section_id)
                            if heading is None:
                                continue

                            container = heading.find_parent(
                                "div", class_="ecl-u-mb-2xl"
                            )
                            if container is None:
                                continue

                            section_text = " ".join(
                                container.stripped_strings
                            )
                            if (
                                section_text
                                and section_text not in sections
                            ):
                                sections.append(section_text)

                        detail_text = "\n\n".join(sections)
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append(
                        f"{url}: détails indisponibles ({str(exc)[:160]})"
                    )

                full_text = " ".join(part for part in (card, detail_text) if part)
                # Les champs de financement concernent l'offre, pas seulement
                # le programme de financement de l'Union européenne.
                funding_status = classify_funding(full_text)
                evidence = funding_evidence_excerpt(full_text)

                published_match = re.search(
                    r"Posted on\s*:\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
                    card,
                    re.IGNORECASE,
                )
                published_raw = published_match.group(1) if published_match else None

                deadline_raw = value_after_label(card, "Application Deadline", [])
                research_field = value_after_label(
                    card, "Research Field",
                    ["Researcher Profile", "Funding Programme", "Application Deadline"],
                )
                funding_programme = value_after_label(
                    card, "Funding Programme", ["Application Deadline"]
                )
                location_raw = value_after_label(
                    card, "Work Locations",
                    ["Research Field", "Researcher Profile",
                     "Funding Programme", "Application Deadline"],
                )
                posted_match = re.search(r"\bPosted on\s*:", card, re.IGNORECASE)
                institution = (
                    card[:posted_match.start()].strip(" :-|")
                    if posted_match else None
                ) or "Non précisée"

                country = "Non précisé"
                if location_raw:
                    location_match = re.search(
                        r"Number of offers:\s*\d+\s*,\s*([^,]+)",
                        location_raw, re.IGNORECASE,
                    )
                    if location_match:
                        country = location_match.group(1).strip()

                salary_amount, salary_currency, salary_period = extract_salary(
                    detail_text or card
                )
                duration_months = extract_duration(detail_text or card)

                # Conserver les détails accessibles, sinon le résumé d'origine.
                description = detail_text or card
                title_position = description.lower().find(title.lower())
                if title_position > 0:
                    description = description[title_position:]

                department = value_after_label(
                    card, "Department",
                    ["Work Locations", "Research Field", "Researcher Profile",
                     "Funding Programme", "Application Deadline"],
                )
                profile = value_after_label(
                    card, "Researcher Profile",
                    ["Funding Programme", "Application Deadline"],
                )

                offer = {
                    "title": title,
                    "institution": institution,
                    "country": country,
                    "location": location_raw,
                    "field": research_field or infer_field(title + " " + full_text),
                    "description": description[:12000],
                    "url": url,
                    "source": "EURAXESS",
                    "funding_status": funding_status,
                    "funding_type": funding_programme,
                    "salary_amount": salary_amount,
                    "salary_currency": salary_currency,
                    "salary_period": salary_period,
                    "duration_months": duration_months,
                    "tuition_status": None,
                    "eligibility": profile,
                    "deadline": euraxess_date(deadline_raw) if deadline_raw else None,
                    "published_at": euraxess_date(published_raw) if published_raw else None,
                    "funding_evidence": evidence,
                }

                if save_offer(offer):
                    inserted += 1
                else:
                    duplicates += 1

            except Exception as exc:
                skipped += 1
                errors.append(f"{url}: {str(exc)[:250]}")

    except Exception as exc:
        errors.append(f"EURAXESS: {str(exc)[:500]}")

    return {
        "inserted": inserted,
        "duplicates": duplicates,
        "skipped": skipped,
        "sources_scanned": 1,
        "errors": errors[:20],
    }



# EIFFEL_COLLECTOR_V1
EIFFEL_CAMPUS_FRANCE_URL = (
    "https://www.campusfrance.org/fr/actu/"
    "appel-a-candidatures-france-excellence-eiffel-2027"
)
EIFFEL_PARIS_SACLAY_URL = (
    "https://www.universite-paris-saclay.fr/en/admission/"
    "bourses-et-aides-financieres/france-excellence-eiffel-scholarship"
)
EIFFEL_SOURCE = "France Excellence Eiffel — campagne 2027-2028"


def parse_eiffel_page(html, source_kind):
    """Normalise une page officielle Eiffel sans inventer de date interne."""
    sources = {
        "campus_france": (
            EIFFEL_CAMPUS_FRANCE_URL,
            "Établissements d'enseignement supérieur français",
            "France Excellence Eiffel — Campus France",
        ),
        "paris_saclay": (
            EIFFEL_PARIS_SACLAY_URL,
            "Université Paris-Saclay",
            "France Excellence Eiffel — Université Paris-Saclay",
        ),
    }
    if source_kind not in sources:
        raise ValueError("Source Eiffel inconnue.")

    url, institution, source_name = sources[source_kind]
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()

    title_node = soup.find("h1") or soup.find("title")
    title = " ".join(title_node.get_text(" ", strip=True).split()) if title_node else ""
    description = " ".join(soup.get_text(" ", strip=True).split())
    combined = f"{title} {description}"
    normalized = combined.casefold()

    if "eiffel" not in normalized or not re.search(r"\b2027(?:\s*[-–/]\s*2028)?\b", normalized):
        raise ValueError("La page ne confirme pas la campagne Eiffel 2027-2028.")
    if not title:
        raise ValueError("Titre absent de la page Eiffel.")

    deadline = None
    if source_kind == "campus_france" and re.search(
        r"(6\s+janvier\s+2027|january\s+6,?\s+2027|6\s+january\s+2027)",
        normalized,
    ):
        deadline = "2027-01-06"

    eligibility = (
        "La candidature doit être présentée par les établissements français "
        "d'enseignement supérieur ; le candidat doit contacter l'établissement "
        "visé pour connaître sa procédure et son échéance interne."
        if source_kind == "campus_france"
        else
        "Master et doctorat selon l'appel officiel. Contacter l'Université "
        "Paris-Saclay pour vérifier l'éligibilité et l'échéance interne."
    )

    tuition_not_covered = bool(re.search(
        r"(frais de scolarité.{0,80}(ne sont pas|n'est pas).{0,30}pris en charge|"
        r"tuition fees?.{0,80}(not covered|not be covered))",
        normalized,
    ))
    # La page nationale officielle précise que les frais de scolarité
    # ne sont pas couverts. Pour la page locale, ne pas extrapoler ce point.
    if source_kind == "campus_france":
        funding_status = "PARTIAL" if tuition_not_covered or "frais de scolarité" in normalized else "UNCONFIRMED"
        tuition_status = "Non couverts" if tuition_not_covered or "frais de scolarité" in normalized else "À vérifier"
    else:
        funding_status = "UNCONFIRMED"
        tuition_status = "À vérifier"

    return {
        "title": (
            "France Excellence Eiffel 2027-2028"
            if source_kind == "campus_france"
            else "France Excellence Eiffel 2027-2028 — Université Paris-Saclay"
        ),
        "institution": institution,
        "country": "France",
        "location": "",
        "field": "Domaines éligibles selon les critères officiels de la campagne",
        "description": description[:12000],
        "url": url,
        "source": source_name,
        "funding_status": funding_status,
        "funding_type": "Bourse d'excellence — modalités selon le niveau d'études",
        "tuition_status": tuition_status,
        "eligibility": eligibility,
        "deadline": deadline,
        "published_at": None,
        "funding_evidence": (
            "Campagne Eiffel 2027-2028. Les conditions financières doivent être "
            "vérifiées dans le règlement officiel et auprès de l'établissement."
        ),
        "opportunity_type": "aides",
    }


async def collect_eiffel_scholarships(client):
    """Collecte les deux pages Eiffel officielles, avec limites et erreurs isolées."""
    targets = (
        ("campus_france", EIFFEL_CAMPUS_FRANCE_URL),
        ("paris_saclay", EIFFEL_PARIS_SACLAY_URL),
    )
    offers = []
    errors = []

    for source_kind, url in targets:
        try:
            async with client.stream(
                "GET",
                url,
                headers={"Accept": "text/html"},
            ) as response:
                if response.is_redirect:
                    raise ValueError("Redirection refusée.")
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "html" not in content_type and "text/" not in content_type:
                    raise ValueError("La réponse ne semble pas être du HTML.")

                chunks = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > 2_000_000:
                        raise ValueError("Page trop volumineuse (limite 2 Mo).")
                    chunks.append(chunk)

            html = b"".join(chunks).decode("utf-8", errors="replace")
            offers.append(parse_eiffel_page(html, source_kind))
        except Exception as exc:
            errors.append(
                f"Eiffel {source_kind}: {str(exc)[:180]}"
            )

    return {"offers": offers, "errors": errors}


# CAMPUS_FRANCE_COLLECTOR_V1
CAMPUS_FRANCE_HOST = "doctorat.campusfrance.org"
CAMPUS_FRANCE_LIST_URL = (
    "https://doctorat.campusfrance.org/fr/phd/offers/ajax_dtlist"
)
CAMPUS_FRANCE_SOURCE = "Campus France — offres de doctorat"


def validate_campus_france_url(url):
    """N'autorise que les URL HTTPS du domaine officiel Campus France."""
    try:
        parsed = urlparse(str(url or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL Campus France refusée.") from exc

    if (
        parsed.scheme != "https"
        or parsed.hostname != CAMPUS_FRANCE_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("URL Campus France refusée.")
    return parsed.geturl()


def parse_campus_france_detail(html, url):
    """Normalise une fiche HTML Campus France sans inventer de données."""
    url = validate_campus_france_url(url)
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()

    title_node = soup.find("h1")
    title = " ".join(title_node.get_text(" ", strip=True).split()) if title_node else ""
    if not title:
        title_node = soup.title
        title = " ".join(title_node.get_text(" ", strip=True).split()) if title_node else ""
    if not title:
        raise ValueError("Titre absent de la fiche Campus France.")

    description = " ".join(soup.get_text(" ", strip=True).split())
    if len(description) > 12000:
        description = description[:12000]

    # Les dates ne sont retenues que lorsqu'elles sont précédées d'un libellé
    # reconnu par le parseur commun.
    deadline = extract_deadline(description)
    combined = f"{title}\n{description}"
    funding_status = classify_funding(combined)
    evidence = funding_evidence_excerpt(combined) or evidence_excerpt(combined)

    institution = "Non précisée"
    for label in ("Établissement", "Etablissement", "Institution", "Université", "University"):
        match = re.search(
            rf"{re.escape(label)}\s*:?\s*(.{{2,160}}?)(?=\s+(?:École doctorale|Ecole doctorale|Domaine|Discipline|Région|Region|Date limite|Deadline)\b|$)",
            description,
            flags=re.IGNORECASE,
        )
        if match:
            candidate = match.group(1).strip(" :-|")
            if candidate:
                institution = candidate
                break

    field = infer_field(combined)
    return {
        "title": title[:500],
        "institution": institution,
        "country": "France",
        "location": "",
        "field": field,
        "description": description,
        "url": url,
        "source": CAMPUS_FRANCE_SOURCE,
        "funding_status": funding_status,
        "funding_evidence": evidence[:1500],
        "deadline": deadline,
        "published_at": None,
        "opportunity_type": "doctorats",
    }


def parse_campus_france_listing_row(row):
    """Extrait un lien de fiche depuis une ligne JSON DataTables."""
    if not isinstance(row, dict):
        return None
    html = str(row.get("action") or "") + " " + str(row.get("dt_name") or "")
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("a", href=True):
        href = urljoin("https://doctorat.campusfrance.org", link["href"])
        try:
            return validate_campus_france_url(href)
        except ValueError:
            continue
    return None


async def collect_campus_france(client, max_pages=3, page_size=25):
    """Collecte au plus trois pages ; renvoie des offres normalisées et erreurs."""
    max_pages = max(1, min(int(max_pages), 3))
    page_size = max(1, min(int(page_size), 25))
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
        "Referer": "https://doctorat.campusfrance.org/fr/phd/offers",
    }
    offers = []
    errors = []
    seen = set()
    total = 0

    for page in range(max_pages):
        params = {
            "draw": page + 1,
            "start": page * page_size,
            "length": page_size,
        }
        try:
            async with client.stream(
                "GET", CAMPUS_FRANCE_LIST_URL, params=params, headers=headers
            ) as response:
                if response.is_redirect:
                    raise ValueError("Redirection refusée.")
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "json" not in content_type:
                    raise ValueError("La réponse de la liste n'est pas du JSON.")
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 2_000_000:
                        raise ValueError("Réponse trop volumineuse (limite 2 Mo).")
                    chunks.append(chunk)
                import json
                payload = json.loads(b"".join(chunks).decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("Format JSON DataTables invalide.")
            total = int(payload.get("recordsFiltered") or payload.get("recordsTotal") or 0)
            rows = payload["data"]
        except Exception as exc:
            errors.append(f"Liste Campus France page {page + 1}: {str(exc)[:180]}")
            break

        if not rows:
            break

        for row in rows:
            url = parse_campus_france_listing_row(row)
            if not url or url in seen:
                continue
            seen.add(url)
            try:
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        raise ValueError("Redirection de fiche refusée.")
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if "html" not in content_type and "text/" not in content_type:
                        raise ValueError("La fiche ne semble pas être du HTML.")
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 2_000_000:
                            raise ValueError("Fiche trop volumineuse (limite 2 Mo).")
                        chunks.append(chunk)
                offer = parse_campus_france_detail(
                    b"".join(chunks).decode("utf-8", errors="replace"), url
                )
                offers.append(offer)
            except Exception as exc:
                errors.append(f"Fiche Campus France {url.rsplit('/', 1)[-1]}: {str(exc)[:160]}")

        if (page + 1) * page_size >= total:
            break

    return {"offers": offers, "pages_scanned": min(max_pages, page + 1 if 'page' in locals() else 0),
            "errors": errors}


@router.post("/sync")
async def sync_doctorates():
    feeds = configured_feeds()
    inserted = duplicates = skipped = 0
    errors = []
    headers = {
        "User-Agent": "JobCiAddunaAI/1.0 (public doctoral opportunity aggregator)"
    }

    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=False,
        headers=headers,
    ) as client:
        # Les flux RSS/Atom existants restent pris en charge.
        for feed in feeds:
            try:
                validate_feed_url(feed["url"])
                max_bytes = 5_000_000
                async with client.stream("GET", feed["url"]) as response:
                    if response.is_redirect:
                        raise ValueError(
                            "Redirection refusée : configurez l'URL finale "
                            "du flux RSS/Atom."
                        )
                    response.raise_for_status()

                    content_type = response.headers.get(
                        "content-type", ""
                    ).lower()
                    content_length = response.headers.get("content-length")

                    if content_length is not None:
                        try:
                            declared_size = int(content_length)
                        except ValueError as exc:
                            raise ValueError(
                                "En-tête Content-Length invalide."
                            ) from exc

                        if declared_size < 0 or declared_size > max_bytes:
                            raise ValueError(
                                "Flux trop volumineux (limite 5 Mo)."
                            )

                    chunks = []
                    total_bytes = 0

                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            raise ValueError(
                                "Flux trop volumineux (limite 5 Mo)."
                            )
                        chunks.append(chunk)

                    body = b"".join(chunks)

                if not (
                    "xml" in content_type
                    or "rss" in content_type
                    or "atom" in content_type
                    or body.lstrip().startswith(b"<")
                ):
                    raise ValueError(
                        "La réponse ne semble pas être un flux XML."
                    )

                for entry in parse_feed(body, feed["name"]):
                    # Les flux sont explicitement configurés par l'utilisateur.
                    # Conserver toutes leurs annonces : doctorats, bourses,
                    # aides générales et projets autofinancés.
                    try:
                        if save_offer(entry):
                            inserted += 1
                        else:
                            duplicates += 1
                    except Exception as exc:
                        errors.append(
                            f"{feed['name']}: enregistrement impossible "
                            f"({str(exc)[:180]})"
                        )
            except Exception as exc:
                errors.append(f"{feed['name']}: {str(exc)[:220]}")

        # Campus France : source académique officielle, distincte des flux RSS/Atom.
        try:
            campus = await collect_campus_france(client, max_pages=3, page_size=25)
            errors.extend(campus["errors"])
            for entry in campus["offers"]:
                try:
                    if save_offer(entry):
                        inserted += 1
                    else:
                        duplicates += 1
                except Exception as exc:
                    errors.append(
                        f"Campus France : enregistrement impossible ({str(exc)[:160]})"
                    )
            campus_pages = campus["pages_scanned"]
        except Exception as exc:
            campus_pages = 0
            errors.append(f"Campus France : {str(exc)[:180]}")

        # Bourses Eiffel : chaque page est indépendante des autres collecteurs.
        try:
            eiffel = await collect_eiffel_scholarships(client)
            errors.extend(eiffel["errors"])
            for entry in eiffel["offers"]:
                try:
                    if save_offer(entry):
                        inserted += 1
                    else:
                        duplicates += 1
                except Exception as exc:
                    errors.append(
                        f"Eiffel : enregistrement impossible ({str(exc)[:160]})"
                    )
        except Exception as exc:
            errors.append(f"Eiffel : {str(exc)[:180]}")

        # EURAXESS reste suspendu ; les flux RSS/Atom existants restent actifs.
        return {
            "inserted": inserted,
            "duplicates": duplicates,
            "skipped": skipped,
            "sources_scanned": len(feeds) + 3,
            "campus_france_pages_scanned": campus_pages,
            "errors": errors[:40],
        }
