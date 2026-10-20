from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any
import asyncio, hashlib, html, json, logging, os, re, sqlite3
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=True)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from app.doctoral import router as doctoral_router, init_doctoral_db, sync_doctorates
from app.immigration import router as immigration_router
from app.recruiters import router as recruiters_router, init_recruiters_db
from app.recruiter_sync import sync_hackernews_recruiters, sync_official_recruiters
from app.trainings import router as trainings_router, init_trainings_db
from app.training_collector import collect_force_n

logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger('jobhunter.collector')
DB_PATH = Path(os.getenv('JOBHUNTER_DB', str(Path(__file__).resolve().parents[1] / 'jobhunter.db')))
SYNC_INTERVAL_MINUTES = max(60, int(os.getenv('SYNC_INTERVAL_MINUTES', '60')))
AUTO_SYNC_ENABLED = os.getenv('AUTO_SYNC_ENABLED', 'true').lower() in {'1', 'true', 'yes', 'on'}
DOCTORAL_AUTO_SYNC_ENABLED = os.getenv(
    'DOCTORAL_AUTO_SYNC_ENABLED', 'true'
).lower() in {'1', 'true', 'yes', 'on'}
DOCTORAL_SYNC_INTERVAL_HOURS = max(
    1, int(os.getenv('DOCTORAL_SYNC_INTERVAL_HOURS', '24'))
)

RECRUITER_AUTO_SYNC_ENABLED = os.getenv(
    'RECRUITER_AUTO_SYNC_ENABLED', 'true'
).lower() in {'1', 'true', 'yes', 'on'}
RECRUITER_SYNC_INTERVAL_HOURS = max(
    1, int(os.getenv('RECRUITER_SYNC_INTERVAL_HOURS', '6'))
)

TRAINING_AUTO_SYNC_ENABLED = os.getenv(
    'TRAINING_AUTO_SYNC_ENABLED', 'true'
).lower() in {'1', 'true', 'yes', 'on'}
TRAINING_SYNC_INTERVAL_HOURS = max(
    1, int(os.getenv('TRAINING_SYNC_INTERVAL_HOURS', '24'))
)

HTTP_TIMEOUT = float(os.getenv('COLLECTOR_HTTP_TIMEOUT', '20'))
# Optional collectors are disabled until explicitly configured by the user.
JOBSPY_ENABLED = os.getenv('JOBSPY_ENABLED', 'false').lower() in {'1', 'true', 'yes', 'on'}
HIREHUNT_ENABLED = os.getenv('HIREHUNT_ENABLED', 'false').lower() in {'1', 'true', 'yes', 'on'}
CRAWL4AI_ENABLED = os.getenv('CRAWL4AI_ENABLED', 'false').lower() in {'1', 'true', 'yes', 'on'}
SCRAPEGRAPHAI_ENABLED = os.getenv('SCRAPEGRAPHAI_ENABLED', 'false').lower() in {'1', 'true', 'yes', 'on'}
REMOTE_JOBS_API_URL = os.getenv('REMOTE_JOBS_API_URL', '').strip()
PROFILE = {
    'name': 'Fallou Ndiaye', 'title': 'Ingénieur logiciel Full Stack',
    'skills': ['Java', 'Spring Boot', 'Spring Batch', 'Angular', 'PHP', 'Symfony', 'Laravel', 'PostgreSQL', 'Docker', 'REST', 'Kafka', 'Grails', 'Vue.js', 'C#', 'Flutter', 'Dart', 'React Native', 'Android', 'iOS', 'Kotlin', 'Swift'],
    'locations': ['Sénégal', 'France', 'Canada', 'Québec', 'Maroc', 'Luxembourg'],
    'summary': 'Ingénieur logiciel Full Stack avec plus de 5 ans d’expérience, notamment sur des solutions bancaires et des API.'
}

class JobIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    location: str = 'Non précisé'
    country: str = 'Non précisé'
    work_mode: str = 'Non précisé'
    contract_type: str = 'Non précisé'
    description: str = ''
    url: Optional[str] = None
    source: str = 'Ajout manuel'
    skills: list[str] = []
    published_at: Optional[str] = None

class ApplicationUpdate(BaseModel):
    status: str
    notes: str = ''

class DraftRequest(BaseModel):
    job_id: int
    cv_text: str = ''
    tone: str = 'professionnel'


def utcnow(): return datetime.now(timezone.utc).isoformat()

def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, company TEXT NOT NULL,
            location TEXT, country TEXT, work_mode TEXT, contract_type TEXT, description TEXT,
            url TEXT, source TEXT, skills TEXT, created_at TEXT, status TEXT DEFAULT 'À examiner', notes TEXT DEFAULT ''
        )''')
        existing = {r['name'] for r in db.execute('PRAGMA table_info(jobs)').fetchall()}
        migrations = {
            'published_at': 'TEXT', 'collected_at': 'TEXT', 'external_id': 'TEXT',
            'content_hash': 'TEXT', 'match_reasons': 'TEXT DEFAULT \'[]\'', 'missing_skills': 'TEXT DEFAULT \'[]\''
        }
        for col, definition in migrations.items():
            if col not in existing: db.execute(f'ALTER TABLE jobs ADD COLUMN {col} {definition}')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_content_hash ON jobs(content_hash) WHERE content_hash IS NOT NULL')
        db.execute('''CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
            status TEXT NOT NULL, inserted INTEGER DEFAULT 0, updated INTEGER DEFAULT 0,
            skipped INTEGER DEFAULT 0, sources_json TEXT DEFAULT '{}', error TEXT DEFAULT ''
        )''')
        db.commit()


def score_details(job: dict[str, Any]):
    text = ' '.join([str(job.get('title') or ''), str(job.get('description') or ''), ' '.join(job.get('skills', []) if isinstance(job.get('skills'), list) else [])]).lower()
    title = str(job.get('title') or '').lower()
    location = (str(job.get('country') or '') + ' ' + str(job.get('location') or '')).lower()
    skill_hits = [s for s in PROFILE['skills'] if s.lower() in text]
    role_points = 25 if any(x in title for x in ['full stack', 'software engineer', 'développeur', 'developer', 'java', 'backend', 'back-end', 'développeuse']) else 10 if any(x in title for x in ['tech lead', 'architect', 'ingénieur', 'engineer']) else 0

    # Les compétences centrales du poste pèsent davantage que les compétences
    # simplement citées en complément dans une annonce.
    mobile_title = any(x in title for x in [
        'mobile', 'flutter', 'react native', 'android', 'ios', 'kotlin', 'swift'
    ])
    fullstack_title = any(x in title for x in [
        'full stack', 'full-stack', 'fullstack', 'frontend', 'front-end',
        'front end', 'web developer', 'développeur web', 'développeuse web'
    ])
    backend_title = any(x in title for x in [
        'java', 'spring', 'backend', 'back-end', 'back end',
        'backend developer', 'software engineer'
    ])

    mobile_skills = {
        'flutter', 'dart', 'react native', 'android', 'ios', 'kotlin', 'swift'
    }
    backend_skills = {
        'java', 'spring boot', 'spring batch', 'postgresql', 'docker',
        'rest', 'kafka', 'grails', 'c#'
    }
    fullstack_skills = {
        'angular', 'react', 'vue.js', 'php', 'symfony', 'laravel',
        'java', 'spring boot', 'postgresql', 'docker', 'rest'
    }

    if mobile_title:
        primary_skills = mobile_skills
    elif fullstack_title:
        primary_skills = fullstack_skills
    elif backend_title:
        primary_skills = backend_skills
    else:
        primary_skills = set()

    if primary_skills:
        skill_points = min(60, sum(
            8 if skill.lower() in primary_skills else 4
            for skill in skill_hits
        ))
    else:
        skill_points = min(60, len(skill_hits) * 6)

    location_match = any(x in location for x in ['sénégal', 'senegal', 'france', 'canada', 'québec', 'quebec', 'maroc', 'luxembourg', 'remote', 'télétravail'])
    loc_points = 15 if location_match else 5
    reasons = []
    if role_points: reasons.append(f"Intitulé proche du métier cible (+{role_points})")
    if skill_hits:
        detail = "pondérées selon le poste" if primary_skills else "détectées dans l'annonce"
        reasons.append(f"Compétences reconnues ({detail}) : " + ', '.join(skill_hits[:8]) + f" (+{skill_points})")
    if location_match: reasons.append(f"Localisation dans les zones ciblées (+{loc_points})")
    else: reasons.append(f"Localisation à vérifier (+{loc_points})")
    if not skill_hits: reasons.append('Aucune compétence clé détectée dans le texte disponible')
    score = min(100, role_points + skill_points + loc_points)
    missing = [s for s in PROFILE['skills'] if s.lower() not in text]
    return score, reasons, missing

def score_job(job): return score_details(job)[0]

def classify_job(job: dict[str, Any]):
    title = str(job.get('title') or '').lower()
    body = ' '.join([title, str(job.get('description') or ''), ' '.join(job.get('skills', []) if isinstance(job.get('skills'), list) else [])]).lower()
    full_stack_terms = ['full stack', 'full-stack', 'fullstack', 'développeur web', 'web developer', 'full stack software engineer']
    mobile_terms = [
        'mobile developer', 'mobile engineer', 'mobile app developer',
        'mobile application developer', 'développeur mobile',
        'développeuse mobile', 'développeur d’application mobile',
        'développeuse d’application mobile', 'flutter developer',
        'flutter engineer', 'développeur flutter',
        'développeuse flutter', 'react native developer',
        'react native engineer', 'développeur react native',
        'développeuse react native', 'ios developer', 'ios engineer',
        'android developer', 'android engineer', 'développeur android',
        'développeuse android', 'développeur ios', 'développeuse ios'
    ]
    mobile_technologies = ['android', 'ios', 'kotlin', 'swift', 'dart']
    software_roles = [
        'developer', 'développeur', 'développeuse',
        'engineer', 'ingénieur', 'ingénieure',
        'logiciel', 'développement', 'developpement'
    ]
    mobile = (
        any(x in title for x in mobile_terms)
        or (
            any(x in title for x in mobile_technologies)
            and any(x in title for x in software_roles)
        )
        or (
            any(x in body for x in ['flutter', 'react native'])
            and any(x in title for x in ['developer', 'développeur',
                                         'développeuse', 'engineer',
                                         'ingénieur', 'ingénieure',
                                         'développement', 'developpement'])
        )
    )
    full_stack = any(x in title for x in full_stack_terms) or ('full stack' in body and any(x in title for x in ['developer', 'développeur', 'engineer', 'ingénieur']))
    category = 'Mobile' if mobile else 'Full Stack' if full_stack else 'Autre'
    relocation_terms = [
        'relocation assistance', 'relocation package', 'relocation support', 'relocation provided', 'relocation assistance is available', 'we offer relocation', 'relocation package offered',
        'visa sponsorship', 'work visa sponsorship', 'work permit sponsorship', 'sponsorship available', 'sponsor your visa', 'visa sponsorship available',
        'flight ticket provided', 'travel expenses covered', 'moving expenses', 'relocation costs',
        'prise en charge du déplacement', 'frais de déplacement pris en charge',
        'aide à la relocalisation', 'prise en charge de la relocalisation', 'visa sponsorisé',
        'sponsoring du visa', 'accompagnement à la mobilité internationale'
    ]
    relocation = any(term in body for term in relocation_terms)
    remote = str(job.get('work_mode') or '').lower()
    if any(x in remote for x in ['télétravail', 'remote', 'full remote', 'à distance']):
        remote_type = 'Remote'
    elif 'hybride' in remote or 'hybrid' in remote:
        remote_type = 'Hybride'
    elif 'site' in remote or 'présentiel' in remote or 'onsite' in remote:
        remote_type = 'Sur site'
    else:
        remote_type = 'À vérifier'
    # Une localisation étrangère ne prouve pas l'éligibilité des candidats
    # internationaux. Exiger un indice explicite dans le texte de l'annonce.
    international_terms = [
        'international applicants', 'applicants worldwide',
        'open worldwide', 'worldwide applicants', 'global applicants',
        'candidates worldwide', 'open to applicants from any country',
        'eligible to work internationally', 'visa sponsorship',
        'work visa sponsorship', 'work permit sponsorship',
        'relocation assistance', 'relocation package', 'relocation support',
        'candidatures internationales', 'candidats internationaux',
        "candidatures depuis l'étranger",
        'ouvert aux candidats internationaux',
        'prise en charge du visa', 'visa sponsorisé',
        'aide à la relocalisation', 'accompagnement à la mobilité internationale'
    ]
    international = any(term in body for term in international_terms) or relocation
    return {'role_category': category, 'remote_type': remote_type,
            'relocation_supported': relocation, 'international_recruitment': international,
            'relocation_evidence': 'Mention explicite détectée dans l’annonce' if relocation else 'Non confirmé : vérifier auprès du recruteur'}


def row_to_job(row):
    d = dict(row)
    d['skills'] = [s for s in (d.get('skills') or '').split(',') if s]
    try: d['match_reasons'] = json.loads(d.get('match_reasons') or '[]')
    except (ValueError, TypeError): d['match_reasons'] = []
    try: d['missing_skills'] = json.loads(d.get('missing_skills') or '[]')
    except (ValueError, TypeError): d['missing_skills'] = []
    d.update(classify_job(d))
    d['match_score'], reasons, missing = score_details(d)
    d['match_reasons'] = reasons
    d['missing_skills'] = missing[:8]
    return d

def infer_skills(text: str):
    low = text.lower()
    return [s for s in PROFILE['skills'] if s.lower() in low]

def infer_country(location: str):
    low = (location or '').lower()
    for key, value in [('senegal','Sénégal'),('dakar','Sénégal'),('france','France'),('paris','France'),('canada','Canada'),('quebec','Québec'),('québec','Québec'),('morocco','Maroc'),('maroc','Maroc'),('luxembourg','Luxembourg')]:
        if key in low: return value
    if any(x in low for x in ['remote','worldwide','anywhere','remote -']): return 'Remote'
    return 'Non précisé'


def clean_description(value):
    """Convert HTML or HTML-encoded job descriptions into readable plain text."""
    text = str(value or "")

    # Some feeds encode HTML more than once (for example, &amp;lt;p&amp;gt;).
    for _ in range(4):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded

    # Remove scripts and styles, including their contents.
    text = re.sub(
        r'<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>',
        ' ',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Preserve paragraph, heading and list boundaries before removing tags.
    text = re.sub(
        r'<\s*br\b[^>]*>|<\s*/\s*(p|div|li|h[1-6]|ul|ol|section|article|tr|blockquote)\s*>',
        '\n',
        text,
        flags=re.IGNORECASE,
    )

    # Strip remaining HTML tags.
    text = re.sub(r'<[^>]*>', ' ', text)

    # Normalize whitespace while preserving useful paragraph breaks.
    text = text.replace('\xa0', ' ')
    lines = [re.sub(r'[ \t\f\v]+', ' ', line).strip()
             for line in text.splitlines()]
    text = '\n'.join(line for line in lines if line)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()[:16000]


def normalize_job(raw: dict, source: str):
    title = str(raw.get('title') or raw.get('position') or '').strip()
    company = str(raw.get('company_name') or raw.get('company') or raw.get('company_name') or raw.get('organization') or '').strip()
    description = clean_description(raw.get('description') or raw.get('job_description') or raw.get('description_text') or '')
    url = raw.get('url') or raw.get('job_url') or raw.get('redirect_url') or raw.get('apply_url') or raw.get('absolute_url')
    location = raw.get('location') or raw.get('candidate_required_location') or raw.get('locations') or ''
    if isinstance(location, dict): location = location.get('name') or location.get('city') or str(location)
    if isinstance(location, list): location = ', '.join(str(x.get('name', x) if isinstance(x, dict) else x) for x in location)
    tags = raw.get('tags') or raw.get('skills') or []
    if isinstance(tags, str): tags = [x.strip() for x in re.split(r'[,;|]', tags) if x.strip()]
    text = f'{title} {description} ' + ' '.join(str(x) for x in tags)
    skills = sorted(set([str(x) for x in tags if str(x).strip()] + infer_skills(text)), key=str.lower)
    published = raw.get('publication_date') or raw.get('published_at') or raw.get('created_at') or raw.get('date') or raw.get('createdAt')
    if isinstance(published, (int, float)):
        try: published = datetime.fromtimestamp(published, timezone.utc).isoformat()
        except (ValueError, OSError): published = None
    employment = raw.get('job_type') or raw.get('employment_type') or raw.get('contract_type') or 'Non précisé'
    remote = bool(raw.get('remote')) or any(x in (str(location) + ' ' + description).lower() for x in ['remote', 'work from home', 'work-from-home', 'telecommute', 'télétravail', 'à distance', 'fully distributed'])
    work_mode = 'Télétravail' if remote else 'Non précisé'
    country = infer_country(str(location))
    ext_id = str(raw.get('id') or raw.get('requisition_id') or raw.get('job_id') or '') or None
    if not title or not company or not url: return None
    canonical = str(url).strip().lower().split('?')[0].rstrip('/')
    fingerprint = hashlib.sha256((canonical or f'{title.lower()}|{company.lower()}|{location.lower()}').encode()).hexdigest()
    return {'title':title[:200], 'company':company[:200], 'location':str(location)[:300] or 'Non précisé', 'country':country,
            'work_mode':work_mode, 'contract_type':str(employment)[:100], 'description':description,
            'url':str(url), 'source':source, 'skills':skills[:40], 'published_at':str(published) if published else None,
            'external_id':ext_id, 'content_hash':fingerprint}

async def fetch_json(client: httpx.AsyncClient, url: str, params=None):
    response = await client.get(url, params=params, headers={'User-Agent':'JobCiAddunaAI/0.2 (personal job discovery; contact: local-user)'})
    response.raise_for_status()
    return response.json()


CNRS_RSS_URL = 'https://emploi.cnrs.fr/Rss/Offres.ashx'

def _cnrs_norm(value):
    import unicodedata
    value = unicodedata.normalize('NFKD', str(value or ''))
    return ''.join(c for c in value if not unicodedata.combining(c)).lower()

def _cnrs_job_record(item):
    title = (item.findtext('title') or '').strip()
    url = (item.findtext('link') or '').strip()
    category = (item.findtext('category') or '').strip()
    description = clean_description(item.findtext('description') or '')

    if not title or not url:
        return None
    if not url.startswith('https://emploi.cnrs.fr/Offres/'):
        return None

    normalized_title = _cnrs_norm(title)
    normalized_category = _cnrs_norm(category)
    combined = normalized_title + ' ' + normalized_category

    # Les doctorats et stages restent dans leurs modules dédiés.
    if re.search(
        r'\b(doctorant|doctorante|doctorat|these|phd|doctoral|'
        r'stagiaire|stage|internship)\b',
        combined,
    ):
        return None

    is_it = normalized_category.startswith('it en contrat')
    is_research = normalized_category.startswith('chercheur en contrat')
    if not (is_it or is_research):
        return None

    # Signaux explicites de développement logiciel ou de métier informatique.
    software_terms = re.compile(
        r'\b(developpeur|developpeuse|software engineer|software developer|'
        r'genie logiciel|developpement logiciel|developpement de logiciels|'
        r'logiciel|full stack|frontend|front end|backend|back end|'
        r'developpement web|ingenieur informatique|ingenieur en informatique|'
        r'ingenieur logiciel|informatique|cybersecurite|securite informatique|'
        r'devops|cloud computing|systemes distribues|administrateur systeme|'
        r'administration systeme|base de donnees|bases de donnees|'
        r'data engineer|data scientist|machine learning engineer|'
        r'ingenieur ia|ingenieur en ia|programmation|algorithmique)\b'
    )

    # L'IA seule ou le mot « développement » ne suffisent pas :
    # les missions scientifiques expérimentales ne sont pas des postes logiciel.
    scientific_false_positive = re.search(
        r'\b(biologique|biologiques|experimentation|experimental|'
        r'experimentaux|membrane|membranes|electrochimique|'
        r'electrochimiques|materiaux|alliages|cellules solaires|'
        r'instrumentaliste|partenariats entreprises)\b',
        normalized_title,
    )

    explicit_software = re.search(
        r'\b(developpeur|developpeuse|software engineer|software developer|'
        r'genie logiciel|developpement logiciel|developpement de logiciels|'
        r'logiciel|full stack|frontend|backend|developpement web|'
        r'ingenieur informatique|ingenieur en informatique|'
        r'ingenieur logiciel|cybersecurite|devops|data engineer|'
        r'machine learning engineer|ingenieur ia|ingenieur en ia|'
        r'base de donnees|bases de donnees)\b',
        normalized_title,
    )

    # Les postes mobiles sont acceptés avec un intitulé explicite
    # ou une technologie mobile associée à un rôle de développement.
    mobile_role_terms = re.compile(
        r'\b(developpeur mobile|developpeuse mobile|ingenieur mobile|'
        r'ingenieure mobile|mobile developer|mobile engineer|'
        r'developpement mobile|application mobile|applications mobiles|'
        r'mobile application|mobile applications|react native developer|'
        r'flutter developer|flutter engineer|developpeur flutter|'
        r'developpeuse flutter|developpeur react native|'
        r'developpeuse react native|android developer|ios developer|'
        r'developpeur android|developpeuse android|'
        r'developpeur ios|developpeuse ios|cross platform|'
        r'multiplateforme)\b'
    )
    mobile_tech_terms = re.compile(
        r'\b(flutter|dart|react native|kotlin|swift|android|ios)\b'
    )
    software_role_terms = re.compile(
        r'\b(developpeur|developpeuse|developer|engineer|'
        r'ingenieur|ingenieure|developpement|application|logiciel)\b'
    )
    explicit_mobile = bool(
        mobile_role_terms.search(normalized_title)
        or (
            mobile_tech_terms.search(normalized_title)
            and software_role_terms.search(normalized_title)
        )
    )

    if not software_terms.search(normalized_title) and not explicit_mobile:
        return None

    # Les titres bio-scientifiques ne passent que s'ils annoncent
    # explicitement un travail logiciel, pas uniquement de la bioinformatique.
    if scientific_false_positive and not (explicit_software or explicit_mobile):
        return None

    # Le calcul scientifique ou l'IA ne sont retenus que si le titre
    # nomme aussi un métier ou une activité informatique explicite.
    if re.search(r'\b(bioinformatique|calcul scientifique|informatique statistique)\b',
                 normalized_title) and not (explicit_software or explicit_mobile):
        return None

    location = 'France'
    before_ref = re.split(r'\bRef\s*:', title, maxsplit=1)[0]
    parentheses = re.findall(r'\(([^()]*)\)', before_ref)
    if parentheses:
        candidate_location = parentheses[-1].strip()
        if re.search(r'\s[-,]\s', candidate_location):
            location = candidate_location

    clean_title = re.sub(r"^Offre d’emploi\s+", '', title, flags=re.I)
    clean_title = re.sub(r"^Offre d'emploi\s+", '', clean_title, flags=re.I)
    clean_title = re.sub(r'\s*\([^()]*\)\s*Ref\s*:.*$', '', clean_title, flags=re.I)
    clean_title = re.sub(r'\s+Ref\s*:.*$', '', clean_title, flags=re.I)
    clean_title = re.sub(
        r'^(IT|Chercheur)\s+en\s+contrat\s+[^:]+:\s*',
        '', clean_title, flags=re.I
    )
    clean_title = clean_title.strip(' :')

    raw = {
        'title': clean_title or title,
        'company': 'CNRS',
        'location': location,
        'country': 'France',
        'description': description,
        'url': url,
        'publication_date': item.findtext('pubDate'),
        'job_type': category,
    }
    job = normalize_job(raw, 'CNRS')
    if job:
        job['country'] = 'France'
        job['location'] = location
    return job

async def collect_cnrs(client):
    """Collecte le RSS public CNRS et conserve les postes informatiques salariés pertinents."""
    response = await client.get(
        CNRS_RSS_URL,
        headers={'User-Agent': 'JobCiAddunaAI/0.2 (public job discovery)'},
    )
    response.raise_for_status()
    content = response.content
    if len(content) > 5 * 1024 * 1024:
        raise ValueError('Flux CNRS trop volumineux : limite de 5 Mo dépassée.')
    upper = content.upper()
    if b'<!DOCTYPE' in upper or b'<!ENTITY' in upper:
        raise ValueError('Déclaration DOCTYPE/ENTITY refusée dans le flux CNRS.')
    root = ET.fromstring(content)
    jobs = []
    for item in root.findall('.//item'):
        job = _cnrs_job_record(item)
        if job:
            jobs.append(job)
    logger.info('CNRS : %d postes informatiques retenus sur %d annonces RSS',
                len(jobs), len(root.findall('.//item')))
    return jobs



EMPLOISENEGAL_RSS_URL = "https://www.emploisenegal.com/rss.xml"

_EMPLOISENEGAL_IT = re.compile(
    r"\b(informatique|informaticien|developer|développeur|software|"
    r"full[\s-]?stack|backend|frontend|java|jee|spring|angular|react|"
    r"vue\.?js|node\.?js|php|laravel|symfony|python|javascript|"
    r"typescript|dotnet|\.net|c#|ios developer|android developer|"
    r"devops|cloud|cyber.?security|cybersécurité|data engineer|"
    r"database|base[s]? de données|système[s]? d'information|"
    r"support technique|helpdesk|réseau|mobile developer)\b",
    re.IGNORECASE,
)


async def collect_emploisenegal(client):
    """Collecte limitée au flux RSS public EmploiSenegal."""
    from urllib.parse import urlparse
    from email.utils import parsedate_to_datetime

    response = await client.get(
        EMPLOISENEGAL_RSS_URL,
        headers={"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"},
    )
    response.raise_for_status()
    content = response.content

    if len(content) > 5 * 1024 * 1024:
        raise ValueError("Flux EmploiSenegal trop volumineux : limite de 5 Mo.")
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("Déclaration DOCTYPE/ENTITY refusée dans le flux EmploiSenegal.")

    root = ET.fromstring(content)
    jobs = []
    items = root.findall(".//item")

    for item in items:
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        description_html = item.findtext("description") or ""
        guid = item.findtext("guid") or ""
        pub_date = (item.findtext("pubDate") or "").strip()

        parsed = urlparse(url)
        if not (
            parsed.scheme == "https"
            and parsed.hostname == "www.emploisenegal.com"
            and parsed.path.startswith("/offre-emploi-senegal/")
            and not parsed.query
            and not parsed.fragment
        ):
            continue

        description = BeautifulSoup(
            description_html[:100_000], "html.parser"
        ).get_text(" ", strip=True)
        description = clean_description(description)

        if not title or not _EMPLOISENEGAL_IT.search(title + " " + description):
            continue
        if re.search(
            r"\b(demande d'emploi|recherche un emploi|cherche un emploi|"
            r"candidat[e]?\s+à\s+la recherche)\b",
            title,
            re.IGNORECASE,
        ):
            continue

        published = None
        if pub_date:
            try:
                published = parsedate_to_datetime(pub_date).isoformat()
            except (TypeError, ValueError, OverflowError):
                published = None

        match = re.search(r"\b(\d{5,})\b", guid)
        if not match:
            match = re.search(r"-(\d{5,})$", parsed.path)
        external_id = match.group(1) if match else None

        raw = {
            "id": external_id,
            "title": title,
            "company": "Employeur non précisé (EmploiSenegal)",
            "location": "Sénégal",
            "description": description,
            "url": url,
            "publication_date": published,
            "job_type": "À vérifier sur l'annonce",
        }
        job = normalize_job(raw, "EmploiSenegal")
        if job:
            job["country"] = "Sénégal"
            jobs.append(job)

    logger.info(
        "EmploiSenegal : %d offres IT retenues sur %d éléments RSS",
        len(jobs), len(items),
    )
    return jobs


EMPLOI_DAKAR_SITEMAP_URL = (
    "https://www.emploidakar.com/job_listing-sitemap.xml"
)
EMPLOI_DAKAR_IT_TERMS = re.compile(
    r"\b(informatique|informaticien|développeur|développeuse|developer|"
    r"software|full[\s-]?stack|back[\s-]?end|backend|front[\s-]?end|"
    r"frontend|programmer|programmation|java|spring|angular|react|"
    r"vue\.?js|node\.?js|php|laravel|symfony|python|javascript|"
    r"typescript|dotnet|\.net|devops|cloud|cyber.?sécurité|"
    r"cybersecurity|data engineer|database|base de données|"
    r"administrateur système|ingénieur système|réseau informatique|"
    r"mobile developer|développeur mobile|technicien informatique|"
    r"information technology|software engineer|software developer)\b",
    re.IGNORECASE,
)
EMPLOI_DAKAR_REJECT = re.compile(
    r"\b(demande d'emploi|recherche un emploi|cherche un emploi|"
    r"candidat[e]?\s+à\s+la recherche|formation payante)\b",
    re.IGNORECASE,
)


async def collect_emploi_dakar(client):
    """Collecte des offres IT publiques via le sitemap Emploi Dakar."""
    from urllib.parse import urlparse

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}
    response = await client.get(
        EMPLOI_DAKAR_SITEMAP_URL, headers=headers
    )
    response.raise_for_status()
    content = response.content
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("Sitemap Emploi Dakar supérieur à 5 Mo.")
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError(
            "Déclaration DOCTYPE/ENTITY refusée dans le sitemap Emploi Dakar."
        )

    root = ET.fromstring(content)
    urls = []
    seen = set()
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "loc" or not node.text:
            continue
        url = node.text.strip()
        parsed = urlparse(url)
        if (
            parsed.scheme == "https"
            and parsed.hostname == "www.emploidakar.com"
            and parsed.username is None
            and parsed.password is None
            and parsed.path.startswith("/offre-demploi/")
            and not parsed.query
            and not parsed.fragment
            and url not in seen
        ):
            seen.add(url)
            urls.append(url)
            if len(urls) >= 40:
                break

    def walk_jsonld(value, postings):
        if isinstance(value, dict):
            types = value.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if "JobPosting" in types:
                postings.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk_jsonld(child, postings)
        elif isinstance(value, list):
            for child in value:
                walk_jsonld(child, postings)

    jobs = []
    for url in urls:
        try:
            detail = await client.get(url, headers=headers)
            detail.raise_for_status()
            page_content = detail.content
            if len(page_content) > 2 * 1024 * 1024:
                continue
            page = BeautifulSoup(page_content, "html.parser")
            postings = []
            for script in page.find_all(
                "script", type="application/ld+json"
            ):
                try:
                    walk_jsonld(
                        json.loads(script.string or script.get_text()),
                        postings,
                    )
                except (ValueError, TypeError):
                    continue
            if not postings:
                continue

            posting = postings[0]
            title = str(posting.get("title") or "").strip()
            description = clean_description(posting.get("description") or "")
            combined = title + " " + description
            if (
                not title
                or EMPLOI_DAKAR_REJECT.search(combined)
                or not EMPLOI_DAKAR_IT_TERMS.search(combined)
            ):
                continue

            employer = posting.get("hiringOrganization") or {}
            if isinstance(employer, list):
                employer = employer[0] if employer else {}
            company = (
                str(employer.get("name") or "").strip()
                if isinstance(employer, dict) else str(employer).strip()
            ) or "Emploi Dakar — employeur à vérifier"

            place = posting.get("jobLocation") or {}
            if isinstance(place, list):
                place = place[0] if place else {}
            address = place.get("address", {}) if isinstance(place, dict) else {}
            if isinstance(address, dict):
                country = address.get("addressCountry") or "Sénégal"
                if isinstance(country, dict):
                    country = country.get("name") or "Sénégal"
                location = ", ".join(
                    str(part).strip()
                    for part in (
                        address.get("addressLocality"),
                        address.get("addressRegion"),
                        country,
                    )
                    if part
                )
            elif isinstance(address, str):
                location = address.strip()
            else:
                location = ""
            location = location or "Sénégal"

            employment = posting.get("employmentType") or "À vérifier"
            if isinstance(employment, list):
                employment = ", ".join(str(item) for item in employment)

            raw = {
                "id": url.rstrip("/").rsplit("/", 1)[-1],
                "title": title,
                "company": company,
                "location": location,
                "description": description,
                "url": url,
                "publication_date": posting.get("datePosted"),
                "job_type": employment,
            }
            job = normalize_job(raw, "Emploi Dakar")
            if job:
                job["country"] = "Sénégal"
                job["external_id"] = raw["id"]
                jobs.append(job)
        except Exception as exc:
            logger.warning(
                "Emploi Dakar : échec de lecture d'une annonce : %s", exc
            )
            continue

    logger.info(
        "Emploi Dakar : %d offres IT retenues sur %d URLs examinées",
        len(jobs), len(urls),
    )
    return jobs



# Senjob : pages publiques d'offres uniquement.
SENJOB_CATEGORY_URL = "https://senjob.com/sn/offres-d-emploi.php"
SENJOB_MAX_PAGES = 3
SENJOB_MAX_DETAILS = 30
SENJOB_MAX_CATEGORY_BYTES = 2 * 1024 * 1024
SENJOB_MAX_DETAIL_BYTES = 2 * 1024 * 1024

SENJOB_IT_TERMS = re.compile(
    r"\b(informatique|développeur|développeuse|developer|software|"
    r"full[\s-]?stack|back[\s-]?end|backend|front[\s-]?end|frontend|"
    r"programmer|programmation|java|spring|angular|react|vue\.?js|"
    r"node\.?js|php|laravel|symfony|python|javascript|typescript|"
    r"dotnet|devops|cloud|cybersécurité|cybersecurity|data engineer|"
    r"database|base de données|administrateur système|ingénieur système|"
    r"réseau informatique|mobile developer|développeur mobile|"
    r"technicien informatique|software engineer|software developer|"
    r"quality assurance|automaticien qa)\b",
    re.IGNORECASE,
)
SENJOB_REJECT = re.compile(
    r"\b(demande d'emploi|recherche un emploi|cherche un emploi|"
    r"candidat[e]?\s+à\s+la recherche|formation payante|"
    r"\bstage\b|stagiaire|internship|apprentissage)\b",
    re.IGNORECASE,
)


async def collect_senjob(client):
    """Collecte limitée d'offres IT sur les pages publiques de Senjob."""
    from urllib.parse import urljoin, urlparse

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}
    allowed_hosts = {"senjob.com", "www.senjob.com"}

    def safe_url(url, detail=False):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            return False
        if detail:
            return (
                parsed.path.startswith("/sn/jobseekers/")
                and re.search(r"_e_\d+\.html$", parsed.path, re.IGNORECASE)
                and not parsed.query
            )
        return (
            parsed.path == "/sn/offres-d-emploi.php"
            and not parsed.fragment
        )

    def response_is_safe(response, expected_detail=False):
        final_url = getattr(response, "url", None)
        if final_url is None:
            return True
        final_url = str(final_url)
        return safe_url(final_url, detail=expected_detail)

    urls = []
    seen = set()

    for page_number in range(1, SENJOB_MAX_PAGES + 1):
        response = await client.get(
            SENJOB_CATEGORY_URL,
            params={"Category": "8", "page": str(page_number)},
            headers=headers,
        )
        response.raise_for_status()
        if not response_is_safe(response):
            logger.warning("Senjob : URL finale de catégorie refusée.")
            continue

        content = response.content
        if len(content) > SENJOB_MAX_CATEGORY_BYTES:
            logger.warning("Senjob : page de catégorie trop volumineuse.")
            continue

        soup = BeautifulSoup(content, "html.parser")
        page_urls = []
        for anchor in soup.find_all("a", href=True):
            candidate = urljoin(SENJOB_CATEGORY_URL, anchor["href"])
            parsed = urlparse(candidate)
            if not safe_url(candidate, detail=True):
                continue
            canonical = parsed._replace(
                scheme="https", netloc="senjob.com", query="", fragment=""
            ).geturl()
            if canonical not in seen:
                seen.add(canonical)
                page_urls.append(canonical)

        urls.extend(page_urls)
        if len(urls) >= SENJOB_MAX_DETAILS:
            urls = urls[:SENJOB_MAX_DETAILS]
            break
        if not page_urls:
            break

    def find_jobposting(value, results):
        if isinstance(value, dict):
            types = value.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if "JobPosting" in types:
                results.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    find_jobposting(child, results)
        elif isinstance(value, list):
            for child in value:
                find_jobposting(child, results)

    jobs = []
    for url in urls:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            if not response_is_safe(response, expected_detail=True):
                logger.warning("Senjob : redirection d'annonce refusée.")
                continue

            content = response.content
            if len(content) > SENJOB_MAX_DETAIL_BYTES:
                continue

            soup = BeautifulSoup(content, "html.parser")
            postings = []
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    find_jobposting(
                        json.loads(script.string or script.get_text()),
                        postings,
                    )
                except (ValueError, TypeError):
                    # Senjob peut publier un JSON-LD mal formé :
                    # les métadonnées HTML servent alors de solution de repli.
                    continue

            posting = postings[0] if postings else {}
            title = str(posting.get("title") or "").strip()
            if not title:
                for attribute, key in (
                    ("property", "og:title"),
                    ("name", "twitter:title"),
                ):
                    meta = soup.find("meta", attrs={attribute: key})
                    if meta and meta.get("content"):
                        title = meta["content"].strip()
                        break
            if not title and soup.title:
                title = soup.title.get_text(" ", strip=True)
                title = re.sub(r"\s*[|–-]\s*Senjob.*$", "", title, flags=re.I).strip()

            description = str(posting.get("description") or "").strip()
            if not description:
                for attribute, key in (
                    ("property", "og:description"),
                    ("name", "description"),
                ):
                    meta = soup.find("meta", attrs={attribute: key})
                    if meta and meta.get("content", "").strip():
                        description = meta["content"].strip()
                        break
            if not description:
                main = soup.find("main") or soup.find("article")
                if main:
                    description = main.get_text("\n", strip=True)

            description = clean_description(description)
            combined = f"{title} {description}"
            if (
                not title
                or SENJOB_REJECT.search(combined)
                or not SENJOB_IT_TERMS.search(combined)
            ):
                continue

            employer = posting.get("hiringOrganization") or {}
            if isinstance(employer, list):
                employer = employer[0] if employer else {}
            company = (
                str(employer.get("name") or "").strip()
                if isinstance(employer, dict)
                else str(employer).strip()
            )

            # Métadonnée HTML parfois plus exploitable que le JSON-LD.
            if not company:
                text_content = soup.get_text(" ", strip=True)
                match = re.search(
                    r"\b(?:Entreprise|Employeur|Société)\s*:\s*"
                    r"([^|;\n]{2,100})",
                    text_content,
                    re.IGNORECASE,
                )
                if match:
                    company = match.group(1).strip()
            company = company or "Senjob — employeur à vérifier"

            location = "Sénégal"
            place = posting.get("jobLocation") or {}
            if isinstance(place, list):
                place = place[0] if place else {}
            address = place.get("address", {}) if isinstance(place, dict) else {}
            if isinstance(address, dict):
                parts = [
                    address.get("addressLocality"),
                    address.get("addressRegion"),
                    address.get("addressCountry"),
                ]
                location = ", ".join(str(part).strip() for part in parts if part) or location
            elif isinstance(address, str) and address.strip():
                location = address.strip()

            employment = posting.get("employmentType") or ""
            if isinstance(employment, list):
                employment = ", ".join(str(item) for item in employment)
            if not employment:
                match = re.search(
                    r"\bContract Type\s*:\s*([^\n|;]{2,80})",
                    soup.get_text("\n", strip=True),
                    re.IGNORECASE,
                )
                employment = match.group(1).strip() if match else "À vérifier sur l'annonce"

            match_id = re.search(r"_e_(\d+)\.html$", url, re.IGNORECASE)
            external_id = match_id.group(1) if match_id else url

            raw = {
                "id": external_id,
                "title": title,
                "company": company,
                "location": location,
                "description": description,
                "url": url,
                "publication_date": posting.get("datePosted"),
                "job_type": employment,
            }
            job = normalize_job(raw, "Senjob")
            if job:
                detected_country = infer_country(location)
                job["country"] = (
                    detected_country
                    if detected_country != "Non précisé"
                    else "Sénégal"
                )
                job["external_id"] = external_id
                jobs.append(job)
        except Exception as exc:
            # Une annonce défaillante ne doit pas arrêter les autres sources.
            logger.warning("Senjob : annonce ignorée (%s).", str(exc)[:180])
            continue

    logger.info(
        "Senjob : %d offres IT retenues sur %d annonces examinées",
        len(jobs), len(urls),
    )
    return jobs



UN_CAREERS_RSS_URL = 'https://careers.un.org/jobfeed?language=fr'

_UN_IT_TERMS = re.compile(
    r'\b(information technology|information systems|ict|'
    r'information and communication technolog(?:y|ies)|'
    r'software|developer|programmer|programming|database|'
    r'cyber ?security|information security|cloud engineer|'
    r'network engineer|systems administrator|system administrator|'
    r'systems analyst|web developer|mobile developer|'
    r'application support|technical support|service desk|help desk|'
    r'telecommunications|sharepoint|microsoft 365|m365|'
    r'digital solutions|data engineer|data scientist|'
    r'développeur|développeuse|informatique|cybersécurité|'
    r'systèmes d’information|systèmes informatiques|'
    r'base de données|administrateur réseau|développeur mobile)\b',
    re.IGNORECASE,
)


def _un_rss_field(description, labels):
    for line in description.splitlines():
        for label in labels:
            match = re.match(
                r'^\s*' + label + r'\s*:\s*(.*?)\s*$',
                line,
                re.IGNORECASE,
            )
            if match:
                return match.group(1).strip()
    return ''




IOM_JOBS_API_URL = (
    "https://fa-evlj-saasfaprod1.fa.ocs.oraclecloud.com/"
    "hcmRestApi/resources/latest/recruitingCEJobRequisitions"
)
IOM_JOBS_PORTAL = (
    "https://fa-evlj-saasfaprod1.fa.ocs.oraclecloud.com/"
    "hcmUI/CandidateExperience/en/sites/CX_1001/jobs"
)
IOM_IT_TERMS = re.compile(
    r"\b(ict|information technolog(?:y|ies)|it analyst|it officer|"
    r"it specialist|software|developer|programmer|programming|"
    r"cyber.?security|data engineer|data scientist|database|"
    r"systems analyst|network engineer|cloud computing|devops|"
    r"application support|business intelligence|machine learning|"
    r"artificial intelligence|digital transformation|web developer|"
    r"full.?stack|mobile development|computer science|"
    r"telecommunications|erp systems|information systems|"
    r"ingénieur logiciel|développeur|informatique|cybersécurité)\b",
    re.IGNORECASE,
)


async def collect_iom(client):
    """Collecte les postes IT publics de l'OIM via l'API Oracle officielle."""
    found = []
    limit = 100
    today = datetime.now(timezone.utc).date()

    for offset in range(0, 500, limit):
        response = await client.get(
            IOM_JOBS_API_URL,
            params={
                "onlyData": "true",
                "expand": (
                    "requisitionList.workLocation,"
                    "requisitionList.otherWorkLocations,"
                    "requisitionList.secondaryLocations,"
                    "requisitionList.requisitionFlexFields"
                ),
                "finder": (
                    f"findReqs;siteNumber=CX_1001,"
                    f"limit={limit},offset={offset}"
                ),
            },
            headers={
                "User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"
            },
        )
        response.raise_for_status()

        content = response.content
        if len(content) > 5 * 1024 * 1024:
            raise ValueError("Réponse API OIM supérieure à 5 Mo.")

        payload = response.json()
        items = payload.get("items") or []
        records = []
        for item in items:
            if isinstance(item, dict):
                listing = item.get("requisitionList") or []
                if isinstance(listing, list):
                    records.extend(x for x in listing if isinstance(x, dict))

        if not records:
            break

        for item in records:
            job_id = item.get("Id")
            title = str(item.get("Title") or "").strip()
            if not job_id or not str(job_id).isdigit() or not title:
                continue

            published = str(item.get("PostedDate") or "").strip()
            deadline = str(item.get("PostingEndDate") or "").strip()

            if deadline:
                try:
                    if datetime.fromisoformat(deadline[:10]).date() < today:
                        continue
                except ValueError:
                    pass

            description_parts = [
                item.get("ShortDescriptionStr"),
                item.get("ExternalResponsibilitiesStr"),
                item.get("ExternalQualificationsStr"),
                item.get("JobFamily"),
                item.get("JobFunction"),
            ]
            detail = "\n".join(
                str(part).strip()
                for part in description_parts
                if part and str(part).strip()
            )

            if not IOM_IT_TERMS.search(title + "\n" + detail):
                continue

            location = str(
                item.get("PrimaryLocation")
                or item.get("PrimaryLocationCountry")
                or "Non précisé"
            ).strip()

            url = (
                "https://fa-evlj-saasfaprod1.fa.ocs.oraclecloud.com/"
                "hcmUI/CandidateExperience/en/sites/CX_1001/job/"
                + str(job_id)
            )
            description = (
                f"Source : Organisation internationale pour les migrations (OIM/IOM)\n"
                f"Publié le : {published or 'Non précisé'}\n"
                f"Date limite : {deadline or 'Non précisée'}\n"
                f"Lieu : {location}\n"
                f"Type de contrat : {item.get('ContractType') or item.get('WorkerType') or 'Non précisé'}\n"
                f"Mobilité internationale : vérifier les conditions, le droit au travail "
                f"et les éventuelles restrictions dans l'annonce officielle.\n"
                f"Fiche officielle : {url}\n\n{detail}"
            )

            raw = {
                "id": str(job_id),
                "title": title,
                "company": "IOM — Organisation internationale pour les migrations",
                "location": location,
                "description": description,
                "url": url,
                "publication_date": published or None,
                "job_type": item.get("ContractType") or item.get("WorkerType") or item.get("JobType"),
            }
            job = normalize_job(raw, "IOM Careers")
            if job:
                found.append(job)

        if len(records) < limit:
            break

    return found


UNDP_JOBS_URL = "https://jobs.undp.org/cj_view_jobs.cfm?cur_categ_id=&cur_lang=en&cur_rgn_id_c="
UNDP_IT_TERMS = re.compile(
    r"\b(ict|information technolog(?:y|ies)|information systems?|"
    r"it analyst|it associate|software|developer|development|programmer|"
    r"programming|cyber.?security|data engineer|data scientist|database|"
    r"systems analyst|technology|technical architect|cloud computing|"
    r"network engineer|application support|enterprise architecture|"
    r"business intelligence|machine learning|artificial intelligence|"
    r"digital transformation|digital technology|web developer|full.?stack|"
    r"mobile development|computer science|telecommunications|"
    r"ingénieur logiciel|développeur|informatique|cybersécurité)\b",
    re.IGNORECASE,
)


def _undp_cell_text(cell):
    """Extrait une cellule et retire son libellé responsive éventuel."""
    value = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
    return re.sub(
        r"^(?:Job Title|Post level|Apply by|Agency|Location)\s*:?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()


def _undp_deadline(value):
    """Interprète les formats de date du tableau public du PNUD."""
    from datetime import date

    value = re.sub(r"\s+", " ", value or "").strip()
    for fmt in ("%b-%d-%y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


async def collect_undp(client):
    """Collecte les postes IT ouverts depuis le tableau public officiel UNDP."""
    from urllib.parse import urlparse

    response = await client.get(
        UNDP_JOBS_URL,
        headers={"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"},
    )
    response.raise_for_status()
    content = response.content

    if len(content) > 5 * 1024 * 1024:
        raise ValueError("Page UNDP supérieure à 5 Mo.")

    soup = BeautifulSoup(content, "html.parser")
    jobs = []
    seen = set()
    total = 0

    # Les liens de la table officielle portent la classe vacanciesTableLink.
    for anchor in soup.find_all("a", class_="vacanciesTableLink"):
        total += 1
        href = (anchor.get("href") or "").strip()
        parsed = urlparse(href)

        # N'accepter que les fiches de poste Oracle officielles et identifiables.
        if (
            parsed.scheme != "https"
            or parsed.hostname != "estm.fa.em2.oraclecloud.com"
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(
                r"/hcmUI/CandidateExperience/[^/]+/sites/[^/]+/requisitions/job/\d+",
                parsed.path,
                flags=re.IGNORECASE,
            )
        ):
            continue

        match = re.search(r"/requisitions/job/(\d+)$", parsed.path)
        if not match or href in seen:
            continue
        seen.add(href)

        cells = [
            _undp_cell_text(cell)
            for cell in anchor.find_all(
                class_="vacanciesTable__cell", recursive=True
            )
        ]
        cells = [value for value in cells if value]

        # Ordre des cellules du tableau public : titre, grade, échéance,
        # agence, lieu. Les annonces incomplètes sont ignorées.
        if len(cells) < 5:
            continue

        title, grade, deadline_text, agency, location = cells[:5]
        if not title or not UNDP_IT_TERMS.search(title):
            continue

        deadline = _undp_deadline(deadline_text)
        if deadline is not None and deadline < datetime.now(timezone.utc).date():
            continue

        # Si une date est présente mais non interprétable, ne pas prétendre
        # que l'annonce est encore ouverte : on l'écarte par prudence.
        if deadline_text and deadline is None:
            logger.info(
                "UNDP : annonce ignorée, échéance non interprétable (%s) : %s",
                deadline_text, title,
            )
            continue

        description = (
            f"Source officielle : United Nations Development Programme (UNDP).\n"
            f"Grade / niveau : {grade or 'Non précisé'}.\n"
            f"Date limite de candidature : {deadline_text or 'Non précisée'}.\n"
            f"Agence : {agency or 'UNDP'}.\n"
            f"Lieu : {location or 'Non précisé'}.\n"
            f"Portail officiel : {UNDP_JOBS_URL}\n"
            "Vérifier les critères d'éligibilité, les conditions de mobilité "
            "et le parrainage éventuel du visa dans l'annonce officielle."
        )

        raw = {
            "id": match.group(1),
            "title": title,
            "company": agency or "United Nations Development Programme (UNDP)",
            "location": location or "Non précisé",
            "description": description,
            "url": href,
            "job_type": grade or "Non précisé",
        }
        job = normalize_job(raw, "UNDP Careers")
        if job:
            job["external_id"] = match.group(1)
            jobs.append(job)

    logger.info(
        "UNDP Careers : %d postes IT ouverts retenus sur %d lignes examinées",
        len(jobs), total,
    )
    return jobs



WORLD_BANK_GROUP_HOME = (
    "https://worldbankgroup.csod.com/ux/ats/careersite/1/"
    "home?c=worldbankgroup"
)
WORLD_BANK_GROUP_API = "https://us.api.csod.com/rec-job-search/external/jobs"
WORLD_BANK_GROUP_BASE = (
    "https://worldbankgroup.csod.com/ux/ats/careersite/1/requisition/"
)
WORLD_BANK_GROUP_SEARCH_TERMS = (
    "software developer",
    "software engineer",
    "full stack developer",
    "backend engineer",
    "frontend engineer",
    "application developer",
    "web developer",
    "mobile developer",
    "AI engineer",
    "artificial intelligence",
    "machine learning",
    "data engineer",
    "data scientist",
    "information technology",
    "cybersecurity",
    "cloud engineer",
    "DevOps engineer",
    "platform engineer",
    "solutions architect",
    "digital technology",
)
WORLD_BANK_GROUP_TITLE_TERMS = re.compile(
    r"\b(software|developer|development|programmer|"
    r"full[ -]?stack|backend|back[ -]?end|frontend|front[ -]?end|"
    r"application|web developer|mobile developer|"
    r"artificial intelligence|AI engineer|machine learning|"
    r"data engineer|data scientist|data architect|data management|"
    r"information technology|IT officer|cybersecurity|cyber security|"
    r"cloud engineer|cloud architect|solutions architect|"
    r"solution architect|systems architect|technology specialist|"
    r"digital specialist|digital technology|devops|platform engineer|"
    r"database engineer|software architect)\b",
    re.IGNORECASE,
)
WORLD_BANK_GROUP_DESCRIPTION_TERMS = re.compile(
    r"\b(software development|application development|"
    r"machine learning engineer|artificial intelligence engineer|"
    r"data engineering|cybersecurity engineer|"
    r"cloud infrastructure engineer|devops engineer)\b",
    re.IGNORECASE,
)

async def collect_world_bank_group(client):
    """Collecte les postes techniques ouverts du portail public officiel WBG."""
    from datetime import datetime, timezone

    home = await client.get(
        WORLD_BANK_GROUP_HOME,
        headers={"User-Agent": "Mozilla/5.0 (compatible; JobCiAddunaAI/0.2)"},
    )
    home.raise_for_status()
    if len(home.text) > 5 * 1024 * 1024:
        raise ValueError("Page World Bank Group supérieure à 5 Mo.")

    token_match = re.search(r'"token"\s*:\s*"([^"]+)"', home.text)
    if not token_match:
        logger.info("World Bank Group : jeton public absent, collecte interrompue.")
        return []

    # Le jeton reste en mémoire et ne doit jamais être journalisé ni enregistré.
    headers = {
        "Authorization": "Bearer " + token_match.group(1),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://worldbankgroup.csod.com",
        "Referer": WORLD_BANK_GROUP_HOME,
    }
    page_size = 25
    candidates = {}

    for term in WORLD_BANK_GROUP_SEARCH_TERMS:
        for page_number in range(1, 5):
            payload = {
                "careerSiteId": 1,
                "careerSitePageId": 1,
                "pageNumber": page_number,
                "pageSize": page_size,
                "cultureId": 1,
                "searchText": term,
                "cultureName": "en-US",
                "states": [],
                "countryCodes": [],
                "cities": [],
                "placeID": "",
                "radius": "",
                "postingsWithinDays": "",
                "customFieldCheckboxKeys": [],
                "customFieldDropdowns": [],
                "customFieldRadios": [],
            }
            response = await client.post(
                WORLD_BANK_GROUP_API, json=payload, headers=headers
            )
            response.raise_for_status()
            if len(response.content) > 10 * 1024 * 1024:
                raise ValueError("Réponse API World Bank Group supérieure à 10 Mo.")

            envelope = response.json()
            data = envelope.get("data", {})
            if not isinstance(data, dict):
                raise ValueError("Format de réponse API World Bank Group inattendu.")
            rows = data.get("requisitions", [])
            if not isinstance(rows, list):
                raise ValueError("Liste d'offres World Bank Group invalide.")

            for row in rows:
                if not isinstance(row, dict):
                    continue
                identifier = str(row.get("requisitionId") or "").strip()
                if identifier.isdigit():
                    candidates.setdefault(identifier, row)

            total = data.get("totalCount", 0)
            try:
                total = int(total)
            except (ValueError, TypeError):
                total = 0

            if not rows or len(rows) < page_size or page_number * page_size >= total:
                break

    today = datetime.now(timezone.utc).date()
    jobs = []

    for identifier, row in candidates.items():
        title = clean_description(row.get("displayJobTitle") or "")
        description = clean_description(row.get("externalDescription") or "")
        if not title:
            continue

        if not (
            WORLD_BANK_GROUP_TITLE_TERMS.search(title)
            or WORLD_BANK_GROUP_DESCRIPTION_TERMS.search(description)
        ):
            continue

        expiration = str(row.get("postingExpirationDate") or "").strip()
        if expiration:
            try:
                deadline = datetime.strptime(expiration, "%m/%d/%Y").date()
            except ValueError:
                logger.info(
                    "World Bank Group : échéance illisible, offre ignorée (%s)",
                    identifier,
                )
                continue
            if deadline < today:
                continue

        publication = str(row.get("postingEffectiveDate") or "").strip()
        published_at = None
        if publication:
            try:
                published_at = datetime.strptime(
                    publication, "%m/%d/%Y"
                ).date().isoformat()
            except ValueError:
                published_at = None

        locations = row.get("locations") or []
        location_parts = []
        if isinstance(locations, list):
            for place in locations:
                if not isinstance(place, dict):
                    continue
                city = str(place.get("city") or "").strip()
                country_code = str(place.get("country") or "").strip().upper()
                label = ", ".join(part for part in (city, country_code) if part)
                if label and label not in location_parts:
                    location_parts.append(label)
        location = "; ".join(location_parts) or "Non précisé"

        official_url = WORLD_BANK_GROUP_BASE + identifier
        description_parts = [
            "Source officielle : World Bank Group Careers.",
            f"Identifiant de réquisition : {identifier}.",
            f"Date de publication : {publication or 'Non précisée'}.",
            f"Date limite : {expiration or 'Non précisée'}.",
            f"Lieu indiqué par le portail : {location}.",
            description,
            "Vérifier sur la fiche officielle les critères d'expérience, "
            "la nationalité et l'éligibilité, le droit au travail, le visa, "
            "la relocalisation et les conditions de télétravail. "
            "La présence d'un poste dans ce portail ne garantit pas "
            "une mobilité internationale.",
        ]
        raw = {
            "id": identifier,
            "title": title,
            "company": "World Bank Group",
            "location": location,
            "description": "\n".join(part for part in description_parts if part),
            "url": official_url,
            "publication_date": published_at,
            "job_type": "Non précisé",
        }
        job = normalize_job(raw, "World Bank Group Careers")
        if job:
            job["external_id"] = identifier
            jobs.append(job)

    logger.info(
        "World Bank Group Careers : %d postes techniques ouverts retenus "
        "sur %d réquisitions uniques examinées",
        len(jobs), len(candidates),
    )
    return jobs


async def collect_un_careers(client):
    """Lit le flux RSS public de l'ONU et retient les annonces IT pertinentes."""
    response = await client.get(
        UN_CAREERS_RSS_URL,
        headers={'User-Agent': 'JobCiAddunaAI/0.2 (public job discovery)'},
    )
    response.raise_for_status()
    content = response.content

    if len(content) > 5 * 1024 * 1024:
        raise ValueError('Flux ONU trop volumineux : limite de 5 Mo dépassée.')

    upper = content.upper()
    if b'<!DOCTYPE' in upper or b'<!ENTITY' in upper:
        raise ValueError('Déclaration DOCTYPE/ENTITY refusée dans le flux ONU.')

    root = ET.fromstring(content)
    jobs = []
    total = 0

    for item in root.findall('.//item'):
        total += 1
        title = (item.findtext('title') or '').strip()
        url = (item.findtext('link') or '').strip()
        if not title or not url:
            continue

        # Accepter uniquement les fiches de poste du domaine officiel ONU.
        if not re.match(
            r'^https://careers\.un\.org/jobSearchDescription/\d+(?:\?|$)',
            url,
            re.IGNORECASE,
        ):
            continue

        description = clean_description(item.findtext('description') or '')
        network = _un_rss_field(
            description,
            [r'Réseau d[’\']emplois', r'Job Network'],
        )
        family = _un_rss_field(
            description,
            [r'Famille d[’\']emplois', r'Job Family'],
        )
        department = _un_rss_field(
            description,
            [r'Département/Bureau', r'Department/Office'],
        )
        location = _un_rss_field(
            description,
            [r'Lieu d[’\']affectation', r'Duty Station'],
        )
        grade = _un_rss_field(description, [r'Classe', r'Level'])
        reference = _un_rss_field(
            description,
            [r'Référence', r'Reference', r'Job ID'],
        )
        published = _un_rss_field(
            description,
            [r'Date de publication', r'Publication Date'],
        )

        searchable = ' '.join((title, network, family, description))
        if not _UN_IT_TERMS.search(searchable):
            continue

        match = re.search(r'/jobSearchDescription/(\d+)', url)
        external_id = reference or (match.group(1) if match else None)

        raw = {
            'title': title,
            'company': department or 'United Nations',
            'location': location or 'Non précisé',
            'description': description,
            'url': url,
            'publication_date': published or None,
            'job_type': grade or 'Non précisé',
            'id': external_id,
        }
        job = normalize_job(raw, 'ONU Careers RSS')
        if job:
            job['external_id'] = str(external_id) if external_id else None
            jobs.append(job)

    logger.info(
        'ONU Careers RSS : %d postes informatiques retenus sur %d annonces RSS',
        len(jobs), total,
    )
    return jobs





AFRICAN_UNION_API_URL = "https://jobs.au.int/services/recruiting/v1/jobs"
AFRICAN_UNION_BASE_URL = "https://jobs.au.int"

_AU_IT_TITLE = re.compile(
    r"\b(software engineer|software developer|developer|programmer|"
    r"ICT officer|ICT specialist|IT officer|IT specialist|information technology|"
    r"systems analyst|systems engineer|data engineer|data scientist|"
    r"database administrator|cybersecurity|cyber security|network engineer|"
    r"web developer|mobile developer|digital technology|technology officer|"
    r"technology specialist|computer science|information systems officer|"
    r"ingénieur logiciel|développeur|développeuse|informatique|cybersécurité)\b",
    re.IGNORECASE,
)
_AU_INTERNSHIP_TECH = re.compile(
    r"\b(software development|web development|mobile applications|"
    r"programming languages|database administration|network administration|"
    r"cybersecurity|ICT systems|information technology specialist)\b",
    re.IGNORECASE,
)


def _au_date(value):
    if not value:
        return None
    raw = str(value).strip()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(raw[:20], fmt).date()
            except ValueError:
                pass
    return None


def _au_text(value):
    if isinstance(value, list):
        return ", ".join(str(x) for x in value if x)
    if isinstance(value, dict):
        return str(value.get("name") or value.get("label") or "")
    return str(value or "").strip()


async def collect_african_union(client):
    """Collecte les offres IT publiques du portail officiel de l'Union africaine."""
    from datetime import date

    headers = {
        "User-Agent": "JobCiAddunaAI/0.2 (public job discovery)",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": AFRICAN_UNION_BASE_URL,
        "Referer": AFRICAN_UNION_BASE_URL + "/go/All-Jobs/9831757/",
    }
    response = await client.post(
        AFRICAN_UNION_API_URL,
        json={
            "keywords": "",
            "locale": "en_US",
            "location": "",
            "pageNumber": 0,
            "sortBy": "recent",
        },
        headers=headers,
    )
    response.raise_for_status()
    if len(response.content) > 5 * 1024 * 1024:
        raise ValueError("Réponse API African Union supérieure à 5 Mo.")

    data = response.json()
    rows = data.get("items", []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        rows = []

    candidates = {}
    for row in rows:
        if not isinstance(row, dict):
            continue

        job_id = str(row.get("id") or "").strip()
        title = clean_description(
            row.get("unifiedStandardTitle") or row.get("title") or ""
        )
        slug = str(row.get("unifiedUrlTitle") or row.get("urlTitle") or "").strip()
        if not job_id or not title or not slug:
            continue

        is_internship = bool(re.search(r"\b(internship|intern)\b", title, re.I))
        if not _AU_IT_TITLE.search(title) and not is_internship:
            continue

        deadline_raw = row.get("cus_enddate") or row.get("endDate")
        deadline = _au_date(deadline_raw)
        if deadline and deadline < date.today():
            continue

        candidates[job_id] = {
            "id": job_id,
            "title": title,
            "url": f"{AFRICAN_UNION_BASE_URL}/job/{slug}/{job_id}-en_US",
            "location": _au_text(row.get("mfield1") or row.get("location")),
            "grade": _au_text(row.get("jobGrade") or row.get("grade")),
            "deadline": deadline,
            "published": _au_text(row.get("cus_postingdate")),
            "internship": is_internship,
        }

    jobs = []
    for item in candidates.values():
        detail = await client.get(item["url"], headers=headers)
        detail.raise_for_status()
        if len(detail.content) > 5 * 1024 * 1024:
            logger.warning("Fiche African Union trop volumineuse : %s", item["url"])
            continue

        soup = BeautifulSoup(detail.content, "html.parser")
        node = soup.select_one(".job")
        body = clean_description(
            node.get_text("\n", strip=True) if node else soup.get_text("\n", strip=True)
        )
        heading = soup.find("h1")
        title = clean_description(heading.get_text(" ", strip=True)) if heading else item["title"]

        if not _AU_IT_TITLE.search(title):
            if not (item["internship"] and _AU_INTERNSHIP_TECH.search(body)):
                continue

        # Une date limite explicite dans la fiche complète prévaut sur l'API.
        match = re.search(
            r"(?:closing date|application deadline|deadline)\s*[:\-]?\s*"
            r"([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|"
            r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|\d{4}-\d{2}-\d{2})",
            body,
            re.IGNORECASE,
        )
        detail_deadline = _au_date(match.group(1)) if match else None
        deadline = detail_deadline or item["deadline"]
        if deadline and deadline < date.today():
            continue

        metadata = [
            "Source officielle : African Union Careers.",
            f"Identifiant : {item['id']}",
            f"Lieu publié : {item['location'] or 'non précisé'}",
            f"Grade : {item['grade'] or 'non précisé'}",
            f"Date de publication : {item['published'] or 'non détectée'}",
            "Date limite : " + (
                deadline.isoformat() if deadline
                else "non détectée, disponibilité à confirmer"
            ),
            "Vérifier l'éligibilité, les langues, le droit au travail et "
            "les conditions de mobilité sur la fiche officielle.",
        ]
        raw = {
            "title": title,
            "company": "African Union",
            "location": item["location"] or "Non précisé",
            "description": clean_description(body + "\n\n" + "\n".join(metadata)),
            "url": item["url"],
            "id": item["id"],
            "job_type": item["grade"] or "Non précisé",
        }
        job = normalize_job(raw, "African Union Careers")
        if job:
            job["external_id"] = item["id"]
            jobs.append(job)

    logger.info(
        "African Union Careers : %d postes IT retenus sur %d candidats",
        len(jobs), len(candidates),
    )
    return jobs




# CEDEAO / ECOWAS : offres IT depuis les pages publiques officielles.
ECOWAS_BASE_URL = "https://www.ecowas.int"
ECOWAS_JOBS_URL = ECOWAS_BASE_URL + "/jobs/?lang=fr"

_ECOWAS_IT_TITLE_RE = re.compile(
    r"\b(information technology|information systems|it officer|it specialist|"
    r"ict|informatique|technologies? de l['’]information|"
    r"software|developer|développeur|développement logiciel|"
    r"systèmes d['’]information|cybersecurity|cyber security|cybersécurité|"
    r"network engineer|data engineer|database administrator|devops|"
    r"web developer|applications developer|ingénieur logiciel)\b",
    re.IGNORECASE,
)


def _ecowas_parse_date(value):
    """Interprète les formats de date courants en français et en anglais."""
    from datetime import datetime
    import unicodedata

    value = str(value or "").strip()
    if not value:
        return None

    value = unicodedata.normalize("NFC", value)
    months = {
        "janvier": "January", "février": "February", "fevrier": "February",
        "mars": "March", "avril": "April", "mai": "May", "juin": "June",
        "juillet": "July", "août": "August", "aout": "August",
        "septembre": "September", "octobre": "October",
        "novembre": "November", "décembre": "December",
        "decembre": "December",
    }
    for fr, en in months.items():
        value = re.sub(fr, en, value, flags=re.IGNORECASE)

    for fmt in (
        "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y",
        "%b %d %Y", "%B %d %Y", "%d %b %Y",
        "%d %B %Y", "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _ecowas_normalized_text(value):
    import unicodedata
    value = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in value if not unicodedata.combining(c)).lower()


UNOPS_SEARCH_URL = "https://careers.unops.org/careersmarketplace/SearchJobs?search={keyword}"


async def collect_ecowas(client):
    """Collecte les offres IT publiques CEDEAO, sans contourner de protection."""
    from datetime import date
    from urllib.parse import urljoin, urlparse

    headers = {
        "User-Agent": "JobCiAddunaAI/0.2 (public job discovery)",
        "Accept": "text/html,application/xhtml+xml",
    }
    max_bytes = 5 * 1024 * 1024
    max_pages = 3
    max_details = 20

    def is_official_job_url(url):
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        return (
            parsed.scheme == "https"
            and parsed.hostname in {"www.ecowas.int", "ecowas.int"}
            and path.startswith("/jobs/")
            and not re.search(r"/jobs/page/\d+$", path)
            and path != "/jobs"
        )

    page_urls = [ECOWAS_JOBS_URL]
    listings = {}

    # Découverte de liens sur un maximum de trois pages de résultats.
    for page_index in range(max_pages):
        if page_index >= len(page_urls):
            break
        page_url = page_urls[page_index]
        try:
            response = await client.get(page_url, headers=headers)
            response.raise_for_status()
            if len(response.content) > max_bytes:
                logger.warning("CEDEAO : page trop volumineuse, ignorée.")
                continue
            soup = BeautifulSoup(response.content, "html.parser")

            for a in soup.select("a[href]"):
                href = urljoin(str(response.url), a["href"])
                parsed = urlparse(href)
                if (
                    parsed.scheme == "https"
                    and parsed.hostname in {"www.ecowas.int", "ecowas.int"}
                    and re.search(r"/jobs/page/\d+/?$", parsed.path)
                    and href not in page_urls
                    and len(page_urls) < max_pages
                ):
                    page_urls.append(href)

                title = clean_description(a.get_text(" ", strip=True))
                if (
                    title
                    and is_official_job_url(href)
                    and _ECOWAS_IT_TITLE_RE.search(_ecowas_normalized_text(title))
                ):
                    listings.setdefault(href, title)
        except Exception as exc:
            logger.warning("CEDEAO : lecture de page impossible (%s)", exc)

    jobs = []
    today = date.today()

    for url, listing_title in list(listings.items())[:max_details]:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            if len(response.content) > max_bytes:
                logger.warning("CEDEAO : fiche trop volumineuse, ignorée.")
                continue

            soup = BeautifulSoup(response.content, "html.parser")
            heading = soup.find("h1")
            title = clean_description(
                heading.get_text(" ", strip=True) if heading else listing_title
            )
            if not _ECOWAS_IT_TITLE_RE.search(_ecowas_normalized_text(title)):
                continue

            article = soup.find("article") or soup.find("main") or soup.body
            body = clean_description(
                article.get_text("\n", strip=True) if article else ""
            )
            if not body:
                continue

            # Cherche uniquement une date explicitement associée à la clôture.
            deadline_match = re.search(
                r"(?:date limite(?: de candidature)?|date de clôture|"
                r"closing date|application deadline|deadline)"
                r"\s*[:\-]?\s*"
                r"((?:\d{4}-\d{2}-\d{2})|"
                r"[A-Za-zÀ-ÿ]+\s+\d{1,2},?\s+\d{4}|"
                r"\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})",
                body,
                re.IGNORECASE,
            )
            deadline = (
                _ecowas_parse_date(deadline_match.group(1))
                if deadline_match else None
            )
            if deadline and deadline < today:
                continue

            # La date de publication est distincte de la date limite.
            published = None
            for node in soup.select("time"):
                published = _ecowas_parse_date(
                    node.get("datetime") or node.get_text(" ", strip=True)
                )
                if published:
                    break

            if not published:
                pub_match = re.search(
                    r"\b([A-Za-zÀ-ÿ]{3,12}\s+\d{1,2},?\s+\d{4})\b",
                    body,
                    re.IGNORECASE,
                )
                if pub_match:
                    published = _ecowas_parse_date(pub_match.group(1))

            slug = urlparse(url).path.rstrip("/").split("/")[-1]
            deadline_text = (
                deadline.isoformat() if deadline
                else "non détectée — disponibilité à vérifier"
            )
            metadata = (
                "\n\nSource officielle : CEDEAO / ECOWAS Careers."
                f"\nDate limite détectée : {deadline_text}."
                "\nVérifier la nationalité admissible, les langues, les "
                "conditions de candidature et la mobilité sur la fiche officielle."
            )
            raw = {
                "title": title,
                "company": "CEDEAO / ECOWAS",
                "location": "Non précisé — consulter la fiche officielle",
                "description": clean_description(body + metadata),
                "url": url,
                "id": slug,
                "published_at": published.isoformat() if published else None,
                "job_type": "Non précisé",
            }
            job = normalize_job(raw, "CEDEAO Careers")
            if job:
                job["external_id"] = "ecowas:" + slug
                jobs.append(job)

        except Exception as exc:
            logger.warning("CEDEAO : fiche ignorée (%s) : %s", url, exc)

    logger.info(
        "CEDEAO Careers : %d postes IT retenus sur %d fiches candidates",
        len(jobs), len(listings),
    )
    return jobs


"https://careers.unops.org/careersmarketplace/SearchJobs?search={keyword}"
_UNOPS_IT_TERMS = re.compile(
    r"\b(software|developer|development|programmer|programming|"
    r"information technology|information systems|ICT|IT specialist|"
    r"IT officer|computer science|systems analyst|systems engineer|"
    r"data engineer|database|cybersecurity|cyber security|network engineer|"
    r"cloud engineer|DevOps|applications developer|digital technology|"
    r"digital transformation|technology specialist|technology officer|"
    r"web developer|mobile developer|software engineer|"
    r"ingénieur logiciel|développeur|développeuse|informatique|"
    r"cybersécurité|administrateur systèmes)\b",
    re.IGNORECASE,
)


def _unops_field(body, labels):
    """Extrait prudemment un champ textuel présenté sous forme de libellé."""
    for label in labels:
        match = re.search(
            rf"(?im)^\s*{label}\s*(?:\n|:\s*)([^\n]+)",
            body,
        )
        if match:
            value = clean_description(match.group(1)).strip(" :\t")
            if value:
                return value[:300]
    return None


def _unops_deadline(body):
    """Retourne la date de clôture reconnue, ou None si elle est illisible."""
    match = re.search(
        r"\bPosting\s+End\s+Date\s*:?\s*(\d{1,2}-[A-Za-z]{3}-\d{4})",
        body,
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d-%b-%Y").date()
    except ValueError:
        return None


async def collect_unops(client):
    """Collecte les offres IT du portail officiel UNOPS."""
    from datetime import date
    from urllib.parse import quote, urljoin, urlparse

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}
    keywords = (
        "software",
        "developer",
        "ICT",
        "information technology",
        "mobile",
        "digital",
    )
    candidates = {}

    for keyword in keywords:
        search_url = UNOPS_SEARCH_URL.format(keyword=quote(keyword))
        response = await client.get(search_url, headers=headers)
        response.raise_for_status()

        if len(response.content) > 5 * 1024 * 1024:
            raise ValueError("Page de recherche UNOPS supérieure à 5 Mo.")

        soup = BeautifulSoup(response.content, "html.parser")
        for link in soup.select('a[href*="/careersmarketplace/JobDetail/"]'):
            href = (link.get("href") or "").strip()
            result_title = clean_description(link.get_text(" ", strip=True))
            if not href:
                continue

            absolute = urljoin("https://careers.unops.org", href)
            parsed = urlparse(absolute)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "careers.unops.org"
                or not re.match(
                    r"^/careersmarketplace/JobDetail/[^?#]+/\d+/?$",
                    parsed.path,
                )
            ):
                continue

            match = re.search(r"/(\d+)/?$", parsed.path)
            if not match:
                continue

            job_id = match.group(1)
            canonical = f"https://careers.unops.org{parsed.path.rstrip('/')}"
            candidates[job_id] = {
                "url": canonical,
                "title": result_title,
                "id": job_id,
            }

    jobs = []
    today = date.today()

    for candidate in candidates.values():
        response = await client.get(candidate["url"], headers=headers)
        response.raise_for_status()

        if len(response.content) > 5 * 1024 * 1024:
            logger.warning("Fiche UNOPS trop volumineuse, ignorée : %s", candidate["url"])
            continue

        soup = BeautifulSoup(response.content, "html.parser")
        body = soup.get_text("\n", strip=True)
        heading = soup.find("h1")
        title = (
            clean_description(heading.get_text(" ", strip=True))
            if heading else candidate["title"]
        )

        if not title or not _UNOPS_IT_TERMS.search(title):
            continue

        deadline = _unops_deadline(body)
        if deadline and deadline < today:
            continue

        location = _unops_field(body, (r"Duty station", r"Duty Station"))
        contract = _unops_field(body, (r"Contract Type", r"Contract type"))
        level = _unops_field(body, (r"Contract Level", r"Contract level"))
        seniority = _unops_field(body, (r"Seniority",))
        duration = _unops_field(body, (r"Duration",))
        start_date = _unops_field(body, (r"Posting Start Date",))

        details = [
            f"Source officielle : UNOPS Careers.",
            f"Identifiant UNOPS : {candidate['id']}",
            f"Date de publication indiquée : {start_date or 'non détectée'}",
            f"Date limite : {deadline.isoformat() if deadline else 'non détectée, disponibilité à confirmer'}",
            f"Type de contrat : {contract or 'non précisé'}",
            f"Niveau de contrat : {level or 'non précisé'}",
            f"Ancienneté/niveau : {seniority or 'non précisé'}",
            f"Durée : {duration or 'non précisée'}",
            "Vérifier sur la fiche officielle l'éligibilité, les exigences "
            "linguistiques, le droit au travail et les conditions de mobilité.",
        ]
        description = clean_description(body + "\n\n" + "\n".join(details))

        raw = {
            "title": title,
            "company": "UNOPS",
            "location": location or "Non précisé",
            "description": description,
            "url": candidate["url"],
            "id": candidate["id"],
            "job_type": contract or "Non précisé",
            "remote": bool(
                location and re.search(
                    r"\b(home based|home-based|remote)\b",
                    location,
                    re.IGNORECASE,
                )
            ),
        }
        job = normalize_job(raw, "UNOPS Careers")
        if job:
            job["external_id"] = candidate["id"]
            jobs.append(job)

    logger.info(
        "UNOPS Careers : %d postes IT retenus parmi %d fiches candidates",
        len(jobs), len(candidates),
    )
    return jobs





# World Food Programme (WFP/PAM) — API publique Workday.
WFP_BASE_URL = "https://wfp.wd3.myworkdayjobs.com"
WFP_API_BASE = WFP_BASE_URL + "/wday/cxs/wfp/job_openings"
WFP_PUBLIC_BASE = WFP_BASE_URL + "/en-US/job_openings"

_WFP_IT_TITLE_RE = re.compile(
    r"\b("
    r"information technology|information systems|IT operations|IT solutions|"
    r"IT specialist|IT officer|ICT|software engineer|software developer|"
    r"applications developer|application developer|web developer|"
    r"mobile developer|systems engineer|systems analyst|data engineer|"
    r"database administrator|database engineer|cybersecurity|cyber security|"
    r"network engineer|cloud engineer|DevOps|digital technology|"
    r"technology specialist|technology officer|programmer|"
    r"ingénieur logiciel|développeur|développeuse|informatique|cybersécurité"
    r")\b",
    re.IGNORECASE,
)


def _wfp_parse_deadline(description, end_date=None):
    """Privilégie la date limite explicitement affichée dans la description."""
    from datetime import date, datetime

    soup = BeautifulSoup(str(description or ""), "html.parser")
    body = soup.get_text(" ", strip=True)
    match = re.search(
        r"DEADLINE\s+FOR\s+APPLICATIONS\s*[:\-]?\s*"
        r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        body,
        re.IGNORECASE,
    )
    if match:
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(match.group(1), fmt).date()
            except ValueError:
                pass

    if end_date:
        try:
            return date.fromisoformat(str(end_date)[:10])
        except (TypeError, ValueError):
            pass
    return None


def _wfp_is_relevant(title):
    return bool(_WFP_IT_TITLE_RE.search(str(title or "")))


async def collect_wfp(client):
    """Collecte les postes informatiques du catalogue public WFP Workday."""
    from datetime import date
    from urllib.parse import urljoin, urlparse

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "JobCiAddunaAI/0.2 (public job discovery)",
    }
    keywords = (
        "ICT", "information technology", "software",
        "developer", "cybersecurity", "IT solutions",
    )
    candidates = {}

    for keyword in keywords:
        offset = 0
        # Limite la charge réseau par mot-clé et respecte la pagination Workday.
        while offset < 100:
            response = await client.post(
                f"{WFP_API_BASE}/jobs",
                json={
                    "appliedFacets": {},
                    "limit": 20,
                    "offset": offset,
                    "searchText": keyword,
                    "searchType": "relevance",
                },
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            postings = data.get("jobPostings", [])
            if not isinstance(postings, list) or not postings:
                break

            for item in postings:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                path = str(item.get("externalPath") or "").strip()
                if not title or not _wfp_is_relevant(title):
                    continue
                if not path.startswith("/job/") or "?" in path or "#" in path:
                    continue
                if not re.search(r"_JR\d+$", path):
                    continue
                candidates[path] = item

            offset += len(postings)
            total = data.get("total")
            if isinstance(total, int) and offset >= total:
                break
            if len(postings) < 20:
                break

    jobs = []
    today = date.today()

    for path, listing in candidates.items():
        detail_url = WFP_API_BASE + path
        try:
            response = await client.get(detail_url, headers={
                "Accept": "application/json",
                "User-Agent": headers["User-Agent"],
            })
            response.raise_for_status()
            data = response.json()
            info = data.get("jobPostingInfo", {})
            if not isinstance(info, dict):
                info = {}
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.warning("WFP : détail indisponible pour %s (%s)", path, exc)
            continue

        title = str(info.get("title") or listing.get("title") or "").strip()
        if not _wfp_is_relevant(title):
            continue
        if info.get("canApply") is False:
            continue

        description_html = str(info.get("jobDescription") or "")
        deadline = _wfp_parse_deadline(
            description_html, info.get("endDate")
        )
        if deadline and deadline < today:
            continue

        external_url = str(info.get("externalUrl") or "").strip()
        parsed = urlparse(external_url)
        allowed_hosts = {
            "wfp.wd3.myworkdayjobs.com",
            "wd3.myworkdaysite.com",
        }
        if (
            parsed.scheme != "https"
            or parsed.hostname not in allowed_hosts
            or not parsed.path.startswith("/recruiting/wfp/job_openings/")
            and parsed.hostname == "wd3.myworkdaysite.com"
        ):
            external_url = urljoin(
                WFP_PUBLIC_BASE + "/",
                path.lstrip("/"),
            )

        # Lien public Workday stable ; ne pas fabriquer une URL de candidature
        # à partir d'un domaine ou d'un chemin non validé.
        if not external_url:
            external_url = WFP_PUBLIC_BASE + path

        description_text = clean_description(description_html)
        details = [
            "Source officielle : World Food Programme (WFP/PAM) Careers.",
            f"Identifiant de réquisition : {info.get('jobReqId') or listing.get('bulletFields', ['Non précisé'])[0]}",
            f"Date limite : {deadline.isoformat() if deadline else 'non confirmée ; vérifier la fiche officielle'}",
            f"Date de publication : {info.get('postedOn') or listing.get('postedOn') or 'non précisée'}",
            f"Temps de travail : {info.get('timeType') or 'non précisé'}",
            "Vérifier sur la fiche officielle les critères de nationalité, "
            "l'éligibilité, les exigences linguistiques et les conditions de mobilité.",
        ]
        raw = {
            "title": title,
            "company": "World Food Programme (WFP/PAM)",
            "location": info.get("location") or listing.get("locationsText") or "Non précisé",
            "description": description_text + "\n\n" + "\n".join(details),
            "url": external_url,
            "id": info.get("jobReqId") or listing.get("bulletFields", [None])[0],
            "job_type": info.get("timeType") or "Non précisé",
            "publication_date": info.get("startDate") or None,
        }
        job = normalize_job(raw, "WFP Careers")
        if job:
            job["external_id"] = str(raw["id"] or path.rsplit("_", 1)[-1])
            jobs.append(job)

    logger.info(
        "WFP Careers : %d postes IT retenus parmi %d annonces candidates",
        len(jobs), len(candidates),
    )
    return jobs




# GIZ : API publique du portail officiel de recrutement.
GIZ_CONFIG_URL = "https://jobs.giz.de/assets/js/jobboard-giz.config.json"
GIZ_API_URL = "https://giz-beesite-production-gjb.app.beesite.de/search/"
GIZ_PUBLIC_BASE = "https://jobs.giz.de"

_GIZ_IT_TITLE_RE = re.compile(
    r"\b(software|developer|development|programmer|programming|"
    r"information technology|information systems|ICT|IT specialist|"
    r"IT officer|IT architect|computer science|systems engineer|"
    r"systems administrator|data engineer|data scientist|database|"
    r"cybersecurity|cyber security|network engineer|cloud engineer|"
    r"DevOps|web developer|mobile developer|application developer|"
    r"software engineer|digital solutions|digital infrastructure|"
    r"IT security|SAP consultant|SAP developer|"
    r"softwareentwickler|softwareentwicklung|informatiker|"
    r"anwendungsentwicklung|systemadministrator|"
    r"entwickler|développeur|développeuse|ingénieur logiciel|"
    r"ingénieur informatique|développement logiciel|"
    r"développement informatique|cybersécurité)\b",
    re.IGNORECASE,
)
_GIZ_NON_TARGET_TITLE_RE = re.compile(
    r"\b(intern|internship|praktikant|praktikum|trainee|"
    r"apprentice|apprenticeship|stage|stagiaire)\b",
    re.IGNORECASE,
)


def _giz_location(value):
    """Retourne une localisation lisible et, si possible, son pays."""
    if isinstance(value, dict):
        locations = [value]
    elif isinstance(value, list):
        locations = [item for item in value if isinstance(item, dict)]
    else:
        locations = []

    cities = []
    countries = []
    for item in locations:
        city = next((
            str(item[key]).strip()
            for key in ("CityName", "City", "PositionLocationName",
                        "LocationName", "city", "name")
            if item.get(key) and isinstance(item.get(key), (str, int))
        ), "")
        country = next((
            str(item[key]).strip()
            for key in ("CountryName", "Country", "country", "CountryDescription")
            if item.get(key) and isinstance(item.get(key), (str, int))
        ), "")
        if city and city not in cities:
            cities.append(city)
        if country and country not in countries:
            countries.append(country)

    parts = cities + [c for c in countries if c not in cities]
    return ", ".join(parts) if parts else "Non précisé", (
        countries[0] if countries else "Non précisé"
    )


async def collect_giz(client):
    """Collecte les offres IT ouvertes depuis l'API publique officielle GIZ."""
    from datetime import date
    from urllib.parse import urlparse

    headers = {
        "Accept": "application/json",
        "User-Agent": "JobCiAddunaAI/0.2 (public job discovery)",
    }

    response = await client.get(GIZ_CONFIG_URL, headers=headers)
    response.raise_for_status()
    config = response.json()

    try:
        descriptor_search = config["configWidgetContainer"]["search"][
            "parameter"
        ]["matchedObjectDescriptor"]["search"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Configuration publique GIZ inattendue") from exc

    payload = {
        "LanguageCode": "EN",
        "SearchParameters": {
            "FirstItem": 1,
            "CountItem": 50,
            "Sort": [{
                "Criterion": "PublicationStartDate",
                "Direction": "DESC",
            }],
            "MatchedObjectDescriptor": descriptor_search,
        },
        "SearchCriteria": [],
    }

    response = await client.get(
        GIZ_API_URL,
        params={"data": json.dumps(payload, separators=(",", ":"))},
        headers=headers,
    )
    response.raise_for_status()
    result = response.json()
    search_result = result.get("SearchResult", {})
    items = search_result.get("SearchResultItems", [])
    if not isinstance(items, list):
        raise ValueError("Résultats de recherche GIZ invalides")

    jobs = []
    seen_ids = set()
    today = date.today()

    for item in items:
        if not isinstance(item, dict):
            continue
        descriptor = item.get("MatchedObjectDescriptor", {})
        if not isinstance(descriptor, dict):
            continue

        title = str(descriptor.get("PositionTitle") or "").strip()
        if not title or not _GIZ_IT_TITLE_RE.search(title):
            continue
        if _GIZ_NON_TARGET_TITLE_RE.search(title):
            continue

        identifier = str(
            descriptor.get("ID") or item.get("MatchedObjectId") or ""
        ).strip()
        if identifier and identifier in seen_ids:
            continue

        deadline_raw = str(
            descriptor.get("PublicationEndDate") or ""
        ).strip()
        deadline = None
        if re.match(r"^\d{4}-\d{2}-\d{2}", deadline_raw):
            try:
                deadline = date.fromisoformat(deadline_raw[:10])
            except ValueError:
                deadline = None
        if deadline and deadline < today:
            continue

        url = str(
            descriptor.get("PositionURI")
            or descriptor.get("PositionShortURI")
            or ""
        ).strip()
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "jobs.giz.de"
            or not parsed.path.startswith("/")
            or parsed.username
            or parsed.password
        ):
            continue

        location, country = _giz_location(
            descriptor.get("PositionLocation")
        )
        publication_date = str(
            descriptor.get("PublicationStartDate") or ""
        ).strip() or None

        metadata = [
            "Source officielle : GIZ Careers.",
            f"Identifiant GIZ : {identifier or 'non précisé'}",
            f"Date de clôture indiquée : "
            f"{deadline.isoformat() if deadline else 'à vérifier sur la fiche officielle'}",
            f"Catégorie : {descriptor.get('JobCategory') or 'non précisée'}",
            f"Niveau : {descriptor.get('CareerLevel') or 'non précisé'}",
            "Vérifier sur la fiche officielle l'éligibilité internationale, "
            "la nationalité requise, le visa et les conditions de mobilité.",
        ]
        raw = {
            "title": title,
            "company": "Deutsche Gesellschaft für Internationale Zusammenarbeit (GIZ)",
            "location": location,
            "description": "\n".join(metadata),
            "url": url,
            "id": identifier or None,
            "job_type": descriptor.get("CareerLevel") or "Non précisé",
            "publication_date": publication_date,
        }
        job = normalize_job(raw, "GIZ Careers")
        if not job:
            continue

        # normalize_job ne connaît pas encore tous les pays internationaux.
        job["country"] = country
        if identifier:
            job["external_id"] = identifier
            seen_ids.add(identifier)
        jobs.append(job)

    logger.info("GIZ Careers : %d postes IT retenus parmi %d annonces",
                len(jobs), len(items))
    return jobs


# Islamic Development Bank : portail officiel de recrutement.
ISDB_SEARCH_URL = "https://careers.isdb.org/search/"
ISDB_BASE_URL = "https://careers.isdb.org/"
_ISDB_TITLE_IT_RE = re.compile(
    r"\b(software|developer|programmer|programming|"
    r"information technology|information systems|ICT|IT officer|"
    r"IT specialist|computer science|systems analyst|systems engineer|"
    r"data engineer|data scientist|database|cybersecurity|cyber security|"
    r"network engineer|cloud engineer|DevOps|web developer|mobile developer|"
    r"software engineer|digital technology|technology operations|"
    r"applications developer|IT architect|cyber security analyst|"
    r"ingénieur logiciel|développeur|développeuse|informatique|"
    r"cybersécurité|administrateur systèmes)\b",
    re.IGNORECASE,
)
_ISDB_BODY_IT_RE = re.compile(
    r"\b(information management and disruptive technology|"
    r"technology operations|information technology|IT policies|"
    r"software development|software engineering|systems administration|"
    r"cybersecurity|cyber security|cloud infrastructure|"
    r"network infrastructure|database administration|"
    r"application development|collaboration solutions and platforms)\b",
    re.IGNORECASE,
)


def _isdb_is_relevant(title, body):
    """Évite de retenir les postes généraux sans signal informatique explicite."""
    return bool(
        _ISDB_TITLE_IT_RE.search(title or "")
        or _ISDB_BODY_IT_RE.search(body or "")
    )


def _isdb_parse_deadline(value):
    """Interprète uniquement les formats de date connus du portail IsDB."""
    from datetime import datetime

    if not value:
        return None

    match = re.search(
        r"\b(\d{1,2}[- ]+[A-Za-z]{3,9}[- ]+\d{4}|"
        r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b",
        value.strip(),
    )
    if not match:
        return None

    candidate = re.sub(r"\s+", " ", match.group(1).replace(",", " ")).strip()
    formats = (
        "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y",
        "%b %d %Y", "%B %d %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None




ICAO_CAREERS_URL = "https://icaocareers.icao.int/careers"
_ICAO_ALLOWED_HOSTS = {"icaocareers.icao.int", "estm.fa.em2.oraclecloud.com"}
_ICAO_TITLE_RE = re.compile(
    r"\b(software|developer|programmer|information technology|"
    r"IT engineer|ICT|cyber.?security|data engineer|cloud|network|"
    r"computer|database|digital technology|systems engineer|"
    r"machine learning|artificial intelligence|IT specialist)\b",
    re.IGNORECASE,
)


def _icao_is_relevant(title):
    """Retient les annonces ICAO avec un signal informatique explicite."""
    return bool(_ICAO_TITLE_RE.search(str(title or "")))


def _icao_parse_deadline(value):
    """Interprète les formats de date visibles sur le portail ICAO."""
    from datetime import datetime as _datetime

    candidate = re.sub(r"\s+", " ", str(value or "")).strip()
    if not candidate:
        return None
    for fmt in (
        "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
        "%d-%b-%Y", "%d %b %Y", "%d %B %Y",
        "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y",
    ):
        try:
            return _datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None


def _icao_extract_jobs(html, today=None):
    """Extrait les offres IT liées depuis les tableaux publics ICAO."""
    from datetime import date as _date
    from urllib.parse import urljoin, urlparse

    today = today or _date.today()
    soup = BeautifulSoup(html or "", "html.parser")
    found, seen = [], set()

    for row in soup.find_all("tr"):
        cells = [
            re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
            for cell in row.find_all(["th", "td"])
        ]
        if not cells:
            continue

        for link in row.find_all("a", href=True):
            title = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
            href = urljoin(ICAO_CAREERS_URL, link["href"].strip())
            parsed = urlparse(href)
            host = (parsed.hostname or "").lower()
            match = re.search(r"/(?:requisitions/)?job/(\d+)(?:/|$)", parsed.path, re.I)

            if not title or not match or host not in _ICAO_ALLOWED_HOSTS:
                continue
            if not _icao_is_relevant(title):
                continue

            job_id = match.group(1)
            if job_id in seen:
                continue

            # Le portail affiche habituellement titre, grade, identifiant,
            # lieu et échéance.
            deadline_text = cells[-1] if len(cells) >= 2 else ""
            deadline = _icao_parse_deadline(deadline_text)
            if deadline and deadline < today:
                continue

            # Les tableaux de postes classiques ont 5 colonnes ;
            # les tableaux de rosters et de consultance en ont généralement 4.
            if len(cells) >= 5:
                grade = cells[1]
                location = cells[3]
            elif len(cells) >= 4:
                grade = ""
                location = cells[-2]
            else:
                grade = ""
                location = "Non précisé"
            lower_title = title.lower()

            if "roster" in lower_title:
                contract_type = "Roster / mission potentielle"
            elif "internship" in lower_title or "intern" in lower_title:
                contract_type = "Stage"
            elif "consultant" in lower_title or "consultancy" in lower_title:
                contract_type = "Consultance"
            else:
                contract_type = "Non précisé"

            details = [
                "Métadonnées extraites du tableau public ICAO ; "
                "la fiche de candidature peut afficher des informations complémentaires.",
                f"Identifiant ICAO : {job_id}.",
            ]
            if grade:
                details.append(f"Grade affiché : {grade}.")
            if deadline_text:
                if deadline:
                    details.append(f"Date limite affichée : {deadline_text}.")
                else:
                    details.append(
                        f"Date limite affichée, format non interprété : {deadline_text}."
                    )
            details.append(
                "Vérifier sur la fiche officielle l'éligibilité, la rémunération, "
                "le statut contractuel et les possibilités de mobilité."
            )

            found.append({
                "id": job_id,
                "title": title,
                "company_name": "International Civil Aviation Organization (ICAO)",
                "location": location or "Non précisé",
                "job_type": contract_type,
                "description": " ".join(details),
                "url": href,
                "deadline": deadline.isoformat() if deadline else None,
            })
            seen.add(job_id)
            break

    return found


async def collect_icao(client):
    """Lit le tableau ICAO public sans contourner le portail candidat."""
    try:
        response = await client.get(ICAO_CAREERS_URL)
        response.raise_for_status()
    except Exception as exc:
        logger.warning("ICAO Careers : lecture du portail public impossible (%s)", exc)
        return []

    raw_jobs = _icao_extract_jobs(response.text)
    normalized = []
    for raw in raw_jobs:
        item = normalize_job(raw, "ICAO Careers")
        if item:
            normalized.append(item)

    logger.info(
        "ICAO Careers : %s offre(s) informatique(s) publique(s) retenue(s)",
        len(normalized),
    )
    return normalized



ITU_BASE_URL = "https://jobs.itu.int"
ITU_LIST_URL = ITU_BASE_URL + "/go/View-all-categories/8942455/"

_ITU_TITLE_RE = re.compile(
    r"\b(software|developer|programmer|information technology|"
    r"\bIT\b|ICT|cyber.?security|data|cloud|network|telecom|"
    r"technology|systems?|computer|database|digital|"
    r"machine learning|artificial intelligence|innovation ecosystem|"
    r"technical advisor|technical expert)\b",
    re.IGNORECASE,
)

_ITU_BODY_RE = re.compile(
    r"\b(information and communication technolog(?:y|ies)|"
    r"software development|information technology|cybersecurity|"
    r"telecommunication|ICT accessibility|digital inclusion|"
    r"cloud infrastructure|network infrastructure|database "
    r"administration|computer science|data engineering)\b",
    re.IGNORECASE,
)


def _itu_is_relevant(title, body=""):
    """Retient les postes et missions présentant un signal informatique clair."""
    title = str(title or "")
    body = str(body or "")
    return bool(
        _ITU_TITLE_RE.search(title)
        or (
            re.search(r"\b(consultant|consultancy|expert|advisor|adviser|roster)\b",
                      title, re.IGNORECASE)
            and _ITU_BODY_RE.search(body)
        )
    )


def _itu_parse_deadline(value):
    """Interprète les dates de clôture anglaises explicites du portail ITU."""
    from datetime import datetime

    if not value:
        return None

    match = re.search(
        r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|"
        r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b",
        str(value),
    )
    if not match:
        return None

    candidate = re.sub(r"\s+", " ", match.group(1).replace(",", " ")).strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            pass
    return None


def _itu_field(body, label):
    """Extrait une valeur située sur la ligne d'un champ de fiche ITU."""
    match = re.search(
        r"^\s*" + re.escape(label) + r"\s*:\s*(.*?)\s*$",
        body or "",
        re.IGNORECASE | re.MULTILINE,
    )
    return match.group(1).strip()[:300] if match else None


async def collect_itu(client):
    """Collecte les postes IT/numériques accessibles sur le portail officiel ITU."""
    from datetime import date
    from urllib.parse import urljoin, urlparse

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}
    listing_urls = [ITU_LIST_URL]
    candidates = {}

    # Découvre uniquement les pages de pagination du même portail.
    try:
        response = await client.get(ITU_LIST_URL, headers=headers)
        response.raise_for_status()
        if len(response.content) > 5 * 1024 * 1024:
            logger.warning("Liste ITU trop volumineuse ; source ignorée.")
            return []

        listing = BeautifulSoup(response.content, "html.parser")
        for link in listing.select('a[href*="/go/View-all-categories/8942455/"]'):
            href = urljoin(ITU_BASE_URL, link.get("href", ""))
            parsed = urlparse(href)
            if (
                parsed.scheme == "https"
                and parsed.hostname == "jobs.itu.int"
                and parsed.path.startswith("/go/View-all-categories/8942455/")
                and href not in listing_urls
                and re.search(r"/8942455/\d+/", parsed.path)
            ):
                listing_urls.append(href)
                if len(listing_urls) >= 3:
                    break
    except Exception as exc:
        logger.warning("Liste ITU inaccessible : %s", type(exc).__name__)
        return []

    # Relit les pages publiques de résultats, sans suivre de domaines externes.
    for listing_url in listing_urls:
        try:
            response = await client.get(listing_url, headers=headers)
            response.raise_for_status()
            if len(response.content) > 5 * 1024 * 1024:
                continue
            page = BeautifulSoup(response.content, "html.parser")

            for link in page.select('a[href*="/job/"]'):
                title = clean_description(link.get_text(" ", strip=True))
                href = urljoin(ITU_BASE_URL, link.get("href", ""))
                parsed = urlparse(href)

                if (
                    title
                    and parsed.scheme == "https"
                    and parsed.hostname == "jobs.itu.int"
                    and parsed.path.startswith("/job/")
                ):
                    canonical = f"https://jobs.itu.int{parsed.path}"
                    candidates.setdefault(canonical, title[:200])
        except Exception as exc:
            logger.warning("Page de résultats ITU ignorée : %s", type(exc).__name__)

    jobs = []
    today = date.today()

    # Limite le nombre de fiches consultées par cycle automatique.
    for canonical, listed_title in list(candidates.items())[:60]:
        try:
            response = await client.get(canonical, headers=headers)
            response.raise_for_status()
            if len(response.content) > 5 * 1024 * 1024:
                continue
        except Exception as exc:
            logger.warning("Fiche ITU inaccessible : %s", type(exc).__name__)
            continue

        page = BeautifulSoup(response.content, "html.parser")
        heading = page.find("h1") or page.select_one("#reqtitle")
        title = clean_description(
            heading.get_text(" ", strip=True) if heading else listed_title
        )

        # Le portail ITU place la description dans .jobdescription.
        description_node = page.select_one(".jobdescription")
        body = clean_description(
            description_node.get_text("\n", strip=True)
            if description_node else page.get_text("\n", strip=True)
        )
        if not title or not _itu_is_relevant(title, body):
            continue

        contract = _itu_field(body, "Type of contract")
        contract_duration = _itu_field(body, "Duration of contract")
        country = _itu_field(body, "Country of contract")
        duty_station = _itu_field(body, "Duty station")
        recruitment_open = _itu_field(body, "Recruitment open to")
        deadline_text = _itu_field(
            body, "Application deadline (Midnight Geneva Time)"
        )
        deadline = _itu_parse_deadline(deadline_text)

        # Une date passée n'exclut l'offre que si elle est interprétée.
        if deadline and deadline < today:
            continue

        vacancy = _itu_field(body, "Vacancy notice no")
        apply_url = None
        for link in page.select('a[href*="/talentcommunity/apply/"]'):
            candidate_url = urljoin(canonical, link.get("href", ""))
            parsed = urlparse(candidate_url)
            if (
                parsed.scheme == "https"
                and parsed.hostname == "jobs.itu.int"
            ):
                apply_url = candidate_url
                break

        metadata = [
            f"Type de contrat : {contract or 'Non précisé'}",
            f"Durée : {contract_duration or 'Non précisée'}",
            f"Pays de contrat : {country or 'Non précisé'}",
            f"Lieu d'affectation : {duty_station or 'Non précisé'}",
            f"Candidatures ouvertes à : {recruitment_open or 'Non précisé'}",
            f"Date limite : {deadline_text or 'absente ou non interprétable'}",
            f"Numéro d'avis : {vacancy or 'non précisé'}",
            f"Fiche officielle : {canonical}",
        ]
        if apply_url:
            metadata.append(f"Lien de candidature : {apply_url}")
        metadata.append(
            "Vérifier les critères d'éligibilité, les langues, "
            "la rémunération, le visa et la mobilité sur la fiche officielle."
        )

        location = " — ".join(
            value for value in (duty_station, country) if value
        ) or "Non précisé"

        raw = {
            "title": title,
            "company": "International Telecommunication Union (ITU)",
            "location": location,
            "description": body + "\n\n" + "\n".join(metadata),
            "url": canonical,
            "id": vacancy,
            "job_type": contract or "Non précisé",
            "remote": bool(re.search(
                r"\b(remote|home based|home-based)\b",
                (country or "") + " " + (duty_station or ""),
                re.IGNORECASE,
            )),
        }
        normalized = normalize_job(raw, "ITU Careers")
        if normalized:
            jobs.append(normalized)

    return jobs


async def collect_isdb(client):
    """Collecte les postes IT visibles sur le portail officiel IsDB."""
    from datetime import date
    from urllib.parse import urljoin, urlparse

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}
    queries = (
        "", "software", "developer", "information technology",
        "data", "digital", "cybersecurity", "cloud", "systems",
    )
    candidates = {}

    # Plusieurs recherches publiques, sans contournement de contrôle d'accès.
    for query in queries:
        response = await client.get(
            ISDB_SEARCH_URL,
            params={"q": query},
            headers=headers,
        )
        response.raise_for_status()
        if len(response.content) > 5 * 1024 * 1024:
            logger.warning("Page de recherche IsDB trop volumineuse ; ignorée.")
            continue

        page = BeautifulSoup(response.content, "html.parser")
        for link in page.select('a[href*="/job/"]'):
            title = clean_description(link.get_text(" ", strip=True))
            href = urljoin(ISDB_BASE_URL, link.get("href", ""))
            parsed = urlparse(href)

            if (
                not title
                or parsed.scheme != "https"
                or parsed.hostname != "careers.isdb.org"
                or not parsed.path.startswith("/job/")
            ):
                continue

            canonical = f"https://careers.isdb.org{parsed.path}"
            candidates.setdefault(canonical, title[:200])

    jobs = []
    today = date.today()

    # Limite le nombre de fiches consultées à chaque cycle automatique.
    for canonical, listed_title in list(candidates.items())[:50]:
        try:
            response = await client.get(canonical, headers=headers)
            response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "Fiche IsDB inaccessible, ignorée : %s (%s)",
                canonical, type(exc).__name__,
            )
            continue

        if len(response.content) > 5 * 1024 * 1024:
            continue

        page = BeautifulSoup(response.content, "html.parser")
        heading = page.find("h1")
        title = clean_description(
            heading.get_text(" ", strip=True) if heading else listed_title
        )
        body = clean_description(page.get_text("\n", strip=True))

        if not title or not _isdb_is_relevant(title, body):
            continue

        def field(label, next_label=None):
            if next_label:
                pattern = (
                    re.escape(label) + r"\s*(.*?)\s+"
                    + re.escape(next_label)
                )
            else:
                pattern = re.escape(label) + r"\s*(.*?)(?:\s{2,}|$)"
            found = re.search(pattern, body, re.IGNORECASE)
            return found.group(1).strip(" :|")[:300] if found else None

        country = field("Country:", "Location:")
        location = field("Location:", "Job Grade:")
        contract = field("Contract Type:", "Closing Date:")
        closing_value = field("Closing Date:", "JOB PURPOSE")
        deadline = _isdb_parse_deadline(closing_value)

        # Une date passée clairement interprétée exclut l'annonce.
        if deadline and deadline < today:
            continue

        requisition = re.search(
            r"Requisition ID:\s*([A-Za-z0-9_-]+)", body, re.IGNORECASE
        )
        job_id = requisition.group(1) if requisition else None

        apply_url = None
        for link in page.select("a[href]"):
            candidate_url = urljoin(canonical, link.get("href", ""))
            parsed_apply = urlparse(candidate_url)
            if (
                parsed_apply.scheme == "https"
                and parsed_apply.hostname == "careers.isdb.org"
                and "/talentcommunity/apply/" in parsed_apply.path
            ):
                apply_url = candidate_url
                break

        deadline_note = (
            f"Closing Date : {closing_value}"
            if deadline
            else "Closing Date : absente ou non interprétable ; à vérifier"
        )
        description = (
            f"{body}\n\n{deadline_note}\n"
            f"Pays affiché : {country or 'Non précisé'}\n"
            f"Identifiant IsDB : {job_id or 'non détecté'}\n"
            f"Fiche officielle : {canonical}\n"
            + (f"Lien de candidature : {apply_url}\n" if apply_url else "")
            + "Vérifier les critères d'éligibilité, la nationalité, "
              "le permis de travail et la mobilité sur la fiche officielle."
        )

        raw = {
            "title": title,
            "company": "Islamic Development Bank (IsDB)",
            "location": location or country or "Non précisé",
            "description": description,
            "url": canonical,
            "id": job_id,
            "job_type": contract or "Non précisé",
        }
        job = normalize_job(raw, "IsDB Careers")
        if job:
            job["external_id"] = job_id
            jobs.append(job)

    logger.info(
        "IsDB Careers : %d offres IT retenues parmi %d fiches candidates",
        len(jobs), len(candidates),
    )
    return jobs


# UNFPA Careers : portail public officiel.
UNFPA_JOBS_URL = "https://www.unfpa.org/jobs"
_UNFPA_IT_TITLE_RE = re.compile(
    r"\b(software|developer|programmer|programming|"
    r"information technology|information systems|ICT|IT officer|"
    r"IT specialist|computer science|systems analyst|systems engineer|"
    r"data engineer|database|cybersecurity|cyber security|"
    r"network engineer|cloud engineer|DevOps|web developer|"
    r"mobile developer|software engineer|digital technology|"
    r"digital transformation|technology specialist|technology officer|"
    r"applications developer|ingénieur logiciel|développeur|"
    r"développeuse|informatique|cybersécurité|administrateur systèmes)\b",
    re.IGNORECASE,
)


def _unfpa_field(soup, label):
    """Lit la valeur affichée à côté d'un libellé d'une fiche UNFPA."""
    for node in soup.find_all(string=lambda value:
                              value and value.strip().lower() == label.lower()):
        for parent in (node.parent, node.parent.parent if node.parent else None):
            if parent is None:
                continue
            parts = [
                clean_description(part)
                for part in parent.get_text(" | ", strip=True).split("|")
            ]
            for index, part in enumerate(parts):
                if part.strip().lower() == label.lower() and index + 1 < len(parts):
                    value = parts[index + 1].strip()
                    if value:
                        return value[:300]
            text = clean_description(parent.get_text(" ", strip=True))
            match = re.match(
                r"^\s*" + re.escape(label) + r"\s*[:|]\s*(.+)$",
                text, re.IGNORECASE,
            )
            if match:
                return match.group(1).strip()[:300]
    return None


def _unfpa_deadline(value):
    """Convertit la date de clôture UNFPA en date, sans inventer de fuseau."""
    if not value:
        return None
    match = re.search(
        r"\b(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b", value
    )
    if not match:
        return None
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(match.group(1), fmt).date()
        except ValueError:
            continue
    return None


async def collect_unfpa(client):
    """Collecte les offres informatiques visibles sur le portail officiel UNFPA."""
    from datetime import date
    from urllib.parse import urljoin, urlparse

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}
    response = await client.get(UNFPA_JOBS_URL, headers=headers)
    response.raise_for_status()
    if len(response.content) > 5 * 1024 * 1024:
        raise ValueError("Page UNFPA supérieure à 5 Mo.")

    soup = BeautifulSoup(response.content, "html.parser")
    candidates = {}
    excluded_paths = {
        "/jobs", "/jobs/contract-types", "/jobs/faqs",
        "/jobs/why-unfpa",
    }

    for link in soup.select("a[href]"):
        title = clean_description(link.get_text(" ", strip=True))
        href = urljoin(UNFPA_JOBS_URL, link.get("href", ""))
        parsed = urlparse(href)

        if (
            not title
            or parsed.scheme != "https"
            or parsed.hostname != "www.unfpa.org"
            or not parsed.path.startswith("/jobs/")
            or parsed.path.rstrip("/").lower() in excluded_paths
            or not _UNFPA_IT_TITLE_RE.search(title)
        ):
            continue

        canonical = f"https://www.unfpa.org{parsed.path.rstrip('/')}"
        candidates.setdefault(canonical, title[:200])

    jobs = []
    today = date.today()

    for canonical, listed_title in candidates.items():
        try:
            detail = await client.get(canonical, headers=headers)
            detail.raise_for_status()
        except Exception as exc:
            logger.warning("Fiche UNFPA inaccessible, ignorée : %s (%s)",
                           canonical, type(exc).__name__)
            continue

        if len(detail.content) > 5 * 1024 * 1024:
            logger.warning("Fiche UNFPA supérieure à 5 Mo, ignorée : %s",
                           canonical)
            continue

        page = BeautifulSoup(detail.content, "html.parser")
        heading = page.find("h1")
        title = clean_description(
            heading.get_text(" ", strip=True) if heading else listed_title
        )
        if not title or not _UNFPA_IT_TITLE_RE.search(title):
            continue

        body = clean_description(page.get_text("\n", strip=True))
        closing_value = _unfpa_field(page, "Closing date")
        deadline = _unfpa_deadline(closing_value)

        # Une date reconnue et passée exclut l'offre. Une date absente ou
        # illisible reste incertaine et est signalée dans la description.
        if deadline and deadline < today:
            continue

        location = _unfpa_field(page, "Duty station") or "Non précisé"
        job_id = _unfpa_field(page, "Job ID")
        if not job_id:
            match = re.search(r"/job/(\d+)(?:/|$)", canonical)
            job_id = match.group(1) if match else None

        apply_url = None
        for link in page.select("a[href]"):
            candidate_url = urljoin(canonical, link.get("href", ""))
            parsed_apply = urlparse(candidate_url)
            if (
                parsed_apply.scheme == "https"
                and parsed_apply.hostname == "estm.fa.em2.oraclecloud.com"
                and "/hcmUI/CandidateExperience/" in parsed_apply.path
            ):
                apply_url = candidate_url
                break

        deadline_note = (
            f"Closing date : {closing_value}"
            if deadline
            else "Closing date : non confirmée ou non interprétable"
        )
        description = (
            f"{body}\n\n{deadline_note}\n"
            f"Identifiant UNFPA : {job_id or 'non détecté'}\n"
            f"Fiche officielle : {canonical}\n"
            + (f"Lien de candidature : {apply_url}\n" if apply_url else "")
            + "Vérifier les critères de nationalité, le type de contrat, "
              "le permis de travail et les possibilités de mobilité sur "
              "la fiche officielle avant de postuler."
        )

        raw = {
            "title": title,
            "company": "UNFPA",
            "location": location,
            "description": description,
            "url": canonical,
            "id": job_id,
            "job_type": "Non précisé",
        }
        job = normalize_job(raw, "UNFPA Careers")
        if job:
            job["external_id"] = job_id
            jobs.append(job)

    logger.info(
        "UNFPA Careers : %d offres IT retenues parmi %d fiches candidates",
        len(jobs), len(candidates),
    )
    return jobs



UNICEF_SEARCH_URL = "https://jobs.unicef.org/en-us/search/?search-keyword={keyword}"
_UNICEF_IT_TERMS = re.compile(
    r"\b(software|developer|development|programmer|programming|"
    r"information technology|information systems|ICT|IT officer|"
    r"IT specialist|computer science|systems analyst|systems engineer|"
    r"data engineer|database|cybersecurity|cyber security|network engineer|"
    r"cloud engineer|DevOps|applications developer|digital technology|"
    r"digital transformation|technology specialist|technology officer|"
    r"web developer|mobile developer|software engineer|"
    r"ingénieur logiciel|développeur|développeuse|informatique|"
    r"cybersécurité|administrateur systèmes)\b",
    re.IGNORECASE,
)


def _unicef_deadline(text):
    """Retourne une date limite comprise dans le texte, ou None."""
    match = re.search(
        r"\bDeadline\s*:\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    value = match.group(1).strip()
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


async def collect_unicef(client):
    """Collecte des postes IT publics sur le portail officiel UNICEF."""
    from urllib.parse import quote
    from datetime import date

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}
    keywords = ("software", "developer", "ICT", "information technology", "digital")
    candidates = {}

    # Les pages de recherche peuvent contenir des résultats hors sujet :
    # seuls les titres IT sont conservés.
    for keyword in keywords:
        url = UNICEF_SEARCH_URL.format(keyword=quote(keyword))
        response = await client.get(url, headers=headers)
        response.raise_for_status()

        if len(response.content) > 5 * 1024 * 1024:
            raise ValueError("Page de recherche UNICEF supérieure à 5 Mo.")

        soup = BeautifulSoup(response.content, "html.parser")
        for link in soup.select('a[href*="/en-us/job/"]'):
            href = (link.get("href") or "").strip()
            title = clean_description(link.get_text(" ", strip=True))
            if not href or not title or not _UNICEF_IT_TERMS.search(title):
                continue

            absolute = __import__("urllib.parse", fromlist=["urljoin"]).urljoin(
                "https://jobs.unicef.org", href
            )
            # Hôte et chemin officiels uniquement.
            from urllib.parse import urlparse
            parsed = urlparse(absolute)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "jobs.unicef.org"
                or not re.match(r"^/en-us/job/\d+/", parsed.path)
            ):
                continue

            canonical = f"https://jobs.unicef.org{parsed.path}".rstrip("/")
            match = re.match(r"^/en-us/job/(\d+)/", parsed.path)
            external_id = match.group(1) if match else None
            candidates[canonical] = {
                "url": absolute,
                "title": title[:200],
                "id": external_id,
            }

    jobs = []
    today = date.today()

    for canonical, candidate in candidates.items():
        response = await client.get(candidate["url"], headers=headers)
        response.raise_for_status()

        if len(response.content) > 5 * 1024 * 1024:
            logger.warning("Fiche UNICEF trop volumineuse, ignorée : %s", canonical)
            continue

        soup = BeautifulSoup(response.content, "html.parser")
        body = soup.get_text("\n", strip=True)
        description = clean_description(body)

        # Le titre visible sur la fiche est préférable au titre du résultat.
        heading = soup.find("h1")
        title = clean_description(heading.get_text(" ", strip=True)) if heading else candidate["title"]
        if not title or not _UNICEF_IT_TERMS.search(title):
            continue

        deadline = _unicef_deadline(body)
        if deadline and deadline < today:
            continue

        # Les dates absentes ou illisibles restent explicitement incertaines.
        deadline_note = (
            f"Deadline : {deadline.isoformat()}"
            if deadline else "Deadline : non détectée, disponibilité à confirmer"
        )
        description = clean_description(
            f"{description}\n\n{deadline_note}\n"
            "Source officielle : UNICEF Careers. Vérifier les restrictions "
            "de nationalité, de résidence, de permis de travail et de mobilité "
            "sur la fiche officielle avant de postuler."
        )

        # La localisation est extraite de la page sans supposer une mobilité internationale.
        location = "Non précisé"
        for pattern in (
            r"\bLocation\s*:\s*([^\n]+)",
            r"\bDuty Station\s*:\s*([^\n]+)",
        ):
            found = re.search(pattern, body, re.IGNORECASE)
            if found:
                location = found.group(1).strip()[:300]
                break

        raw = {
            "title": title,
            "company": "UNICEF",
            "location": location,
            "description": description,
            "url": canonical,
            "id": candidate["id"],
            "job_type": "Non précisé",
        }
        job = normalize_job(raw, "UNICEF Careers")
        if job:
            job["external_id"] = candidate["id"]
            jobs.append(job)

    logger.info(
        "UNICEF Careers : %d postes IT retenus parmi %d fiches candidates",
        len(jobs), len(candidates),
    )
    return jobs



UNESCO_RSS_URL = "https://careers.unesco.org/services/rss/job/"

# Le filtrage porte sur le titre pour éviter d'importer des postes
# génériques simplement parce que leur description mentionne le numérique.
_UNESCO_IT_TITLE_TERMS = re.compile(
    r"\b(software|developer|programmer|programming|"
    r"ict|information technolog(?:y|ies)|"
    r"it infrastructure|it systems?|information systems?|"
    r"digital business solutions|cyber.?security|database|"
    r"web developer|web development|mobile app(?:lication)?|"
    r"application developer|systems analyst|network engineer|"
    r"data engineer|data scientist|cloud architect|"
    r"technology officer|digital technology|digital solutions|"
    r"business intelligence|computer science|"
    r"it officer|it assistant|it specialist|"
    r"software engineering|software architect|"
    r"ingénieur logiciel|développeur|informatique|cybersécurité)\b",
    re.IGNORECASE,
)


async def collect_unesco(client):
    """Collecte des offres IT du flux RSS public officiel de l'UNESCO."""
    from urllib.parse import urlencode, urlparse
    from email.utils import parsedate_to_datetime

    keywords = (
        "software",
        "software engineer",
        "developer",
        "information technology",
        "ICT",
        "IT systems",
        "Java",
        "digital business solutions",
        "cybersecurity",
        "database",
        "web development",
    )
    candidates = {}

    def field(item, name):
        for element in item.iter():
            if element.tag.split("}")[-1].lower() == name.lower():
                return (element.text or "").strip()
        return ""

    for keyword in keywords:
        url = UNESCO_RSS_URL + "?" + urlencode({
            "locale": "en_GB",
            "keywords": f"({keyword})",
        })
        response = await client.get(
            url,
            headers={"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"},
        )
        response.raise_for_status()

        if len(response.content) > 5 * 1024 * 1024:
            raise ValueError("Flux RSS UNESCO supérieur à 5 Mo.")

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            logger.warning("Flux RSS UNESCO illisible pour %s : %s", keyword, exc)
            continue

        for item in root.iter():
            if item.tag.split("}")[-1].lower() != "item":
                continue

            title = clean_description(field(item, "title"))
            url = field(item, "link").strip()
            raw_description = field(item, "description")
            description = clean_description(raw_description)

            if not title or not url or not _UNESCO_IT_TITLE_TERMS.search(title):
                continue

            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != "careers.unesco.org":
                continue

            # Conserver l'URL officielle complète et supprimer seulement le fragment.
            canonical_url = parsed._replace(fragment="").geturl()
            key = canonical_url.rstrip("/").lower()

            published = field(item, "pubDate") or field(item, "publicationDate")
            if published:
                try:
                    published = parsedate_to_datetime(published).isoformat()
                except (TypeError, ValueError, OverflowError):
                    # Conserver la date textuelle si elle n'est pas au format RSS standard.
                    pass

            guid = field(item, "guid") or canonical_url
            location = "Non précisé"
            match = re.search(
                r"(?:Duty Station|Location|Location of assignment)\s*:\s*([^\n;|]+)",
                description,
                re.IGNORECASE,
            )
            if match:
                location = match.group(1).strip()[:300]

            # Une même annonce peut apparaître dans plusieurs recherches.
            candidates.setdefault(key, {
                "title": title[:200],
                "url": canonical_url,
                "id": guid[:300],
                "description": description,
                "location": location,
                "published": published or None,
            })

    jobs = []
    for candidate in candidates.values():
        detail = (
            f"Source officielle : UNESCO Careers\n"
            f"Date de publication : {candidate['published'] or 'Non précisée'}\n"
            f"Lieu : {candidate['location']}\n"
            "Vérifier sur la fiche officielle la date limite, les critères "
            "d'éligibilité, le contrat et les conditions de mobilité.\n\n"
            f"{candidate['description']}\n\n"
            f"Fiche officielle : {candidate['url']}"
        )
        raw = {
            "title": candidate["title"],
            "company": "UNESCO",
            "location": candidate["location"],
            "description": detail,
            "url": candidate["url"],
            "id": candidate["id"],
            "publication_date": candidate["published"],
            "job_type": "Non précisé",
        }
        job = normalize_job(raw, "UNESCO Careers")
        if job:
            job["external_id"] = candidate["id"]
            jobs.append(job)

    logger.info("UNESCO Careers : %d offres IT retenues", len(jobs))
    return jobs


EURAXESS_SEARCH_URL = 'https://euraxess.ec.europa.eu/jobs/search'

_EURAXESS_IT_TERMS = re.compile(
    r'\b(software|developer|programmer|programming|computer science|'
    r'information technology|informatics|artificial intelligence|'
    r'machine learning|data science|data engineer|cyber ?security|'
    r'cloud computing|database|web development|mobile development|'
    r'computer vision|computational science|bioinformatics|robotics|'
    r'embedded systems|digital technology|software engineering|'
    r'développeur|développeuse|informatique|intelligence artificielle|'
    r'apprentissage automatique|science des données|cybersécurité|'
    r'systèmes embarqués|robotique|génie logiciel)\b',
    re.IGNORECASE,
)



FAO_SEARCH_URL = "https://jobs.fao.org/careersection/fao_external/moresearch.ftl"
FAO_IT_TITLE_RE = re.compile(
    r"\b(?:"
    r"software|developer|programmer|programming|information technology|"
    r"information systems|ICT|IT|digital|data engineer|data analyst|"
    r"database|cybersecurity|cyber security|cloud|network engineer|"
    r"systems analyst|web developer|mobile developer|application developer|"
    r"GIS specialist|technology specialist"
    r")\b",
    re.IGNORECASE,
)


async def collect_fao(client):
    """Collecte les postes informatiques visibles sur la première page FAO."""
    import ast
    from datetime import datetime

    response = await client.get(
        FAO_SEARCH_URL,
        headers={"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"},
    )
    response.raise_for_status()
    page = response.text

    if len(page.encode("utf-8")) > 5 * 1024 * 1024:
        raise ValueError("Page FAO trop volumineuse ; collecte interrompue.")

    match = re.search(
        r"api\.fillList\(\s*['\"]requisitionListInterface['\"]\s*,"
        r"\s*['\"]listRequisition['\"]\s*,\s*(\[.*?\])\s*\)",
        page,
        re.DOTALL,
    )
    if not match:
        logger.warning("FAO Careers : liste initiale introuvable sur le portail.")
        return []

    try:
        flat = ast.literal_eval(match.group(1))
    except (ValueError, SyntaxError) as exc:
        raise ValueError("Format de liste FAO inattendu.") from exc

    if not isinstance(flat, list) or len(flat) % 36 != 0:
        raise ValueError("Structure des résultats FAO inattendue (36 champs attendus).")
    if not all(isinstance(value, str) for value in flat):
        raise ValueError("La liste FAO contient des valeurs de type inattendu.")

    jobs = []
    seen = set()

    for offset in range(0, len(flat), 36):
        record = flat[offset:offset + 36]
        internal_id, title, requisition, location, date_text = (
            record[2].strip(),
            record[3].strip(),
            record[7].strip(),
            record[8].strip(),
            record[14].strip(),
        )

        if not title or not requisition.isdigit():
            continue
        if requisition in seen or not FAO_IT_TITLE_RE.search(title):
            continue
        seen.add(requisition)

        published = ""
        if date_text:
            try:
                published = datetime.strptime(date_text, "%d/%b/%Y").date().isoformat()
            except ValueError:
                published = ""

        description = (
            "Source officielle : FAO Careers.\n"
            f"Numéro de réquisition FAO : {requisition}\n"
            f"Date affichée par le portail : {date_text or 'Non précisée'}\n"
            f"Lieu affiché : {location or 'Non précisé'}\n\n"
            "La liste publique initiale ne fournit pas de lien individuel exploitable. "
            "Consultez le portail officiel et recherchez ce numéro de réquisition. "
            "La disponibilité, les critères d'éligibilité et les conditions de mobilité "
            "doivent être vérifiés sur l'annonce officielle."
        )

        normalized = normalize_job(
            {
                "id": requisition,
                "title": title,
                "company": "FAO",
                "location": location or "Non précisé",
                "description": description,
                "url": FAO_SEARCH_URL,
                "published_at": published or None,
            },
            "FAO Careers",
        )
        if not normalized:
            continue

        # La page de recherche est commune à plusieurs offres : une empreinte
        # fondée sur l'identifiant FAO évite de fusionner ces offres entre elles.
        normalized["external_id"] = requisition
        normalized["content_hash"] = hashlib.sha256(
            f"FAO:{requisition}".encode("utf-8")
        ).hexdigest()
        jobs.append(normalized)

    logger.info("FAO Careers : %d offres informatiques retenues sur la première page", len(jobs))
    return jobs



ILO_RSS_URL = "https://jobs.ilo.org/services/rss/category/?catid=2842101"

_ILO_IT_TITLE_RE = re.compile(
    r"\b(?:"
    r"software|developer|development|programmer|programming|"
    r"full[\s-]?stack|front[\s-]?end|back[\s-]?end|"
    r"information technology|information systems|ICT|IT|"
    r"database|data engineer|data analyst|data scientist|"
    r"cyber[\s-]?security|network engineer|systems analyst|"
    r"web developer|mobile developer|application developer|"
    r"cloud engineer|DevOps|computer science|digital technology"
    r")\b",
    re.IGNORECASE,
)


async def collect_ilo(client):
    """Collecte les offres informatiques du flux RSS officiel de l'OIT."""
    from email.utils import parsedate_to_datetime
    from urllib.parse import urlparse

    response = await client.get(
        ILO_RSS_URL,
        headers={"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"},
    )
    response.raise_for_status()
    content = response.content

    if len(content) > 5 * 1024 * 1024:
        raise ValueError("Flux RSS OIT supérieur à 5 Mo.")
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("Déclaration DOCTYPE/ENTITY refusée dans le flux RSS OIT.")

    root = ET.fromstring(content)
    jobs = []
    seen = set()

    def field(item, name):
        for element in item.iter():
            if element.tag.split("}")[-1].lower() == name.lower():
                return "".join(element.itertext()).strip()
        return ""

    items = [
        element for element in root.iter()
        if element.tag.split("}")[-1].lower() == "item"
    ]

    for item in items:
        title = clean_description(field(item, "title"))
        raw_url = field(item, "link").strip()
        raw_description = field(item, "description")
        description = clean_description(raw_description)

        if not title or not raw_url or not _ILO_IT_TITLE_RE.search(title):
            continue

        parsed = urlparse(raw_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "jobs.ilo.org"
            or not parsed.path.startswith("/job/")
        ):
            continue

        # Retirer les paramètres de suivi RSS, pas le chemin de l'annonce.
        canonical_url = parsed._replace(query="", fragment="").geturl()
        key = canonical_url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)

        published = field(item, "pubDate")
        if published:
            try:
                published = parsedate_to_datetime(published).isoformat()
            except (TypeError, ValueError, OverflowError):
                published = None
        else:
            published = None

        guid = field(item, "guid")
        external_id = canonical_url
        if guid:
            guid_parsed = urlparse(guid)
            if (
                guid_parsed.scheme == "https"
                and guid_parsed.hostname == "jobs.ilo.org"
                and guid_parsed.path.startswith("/job/")
            ):
                external_id = guid_parsed._replace(
                    query="", fragment=""
                ).geturl()

        location = "Non précisé"
        # Le titre RSS se termine souvent par une localisation entre parenthèses.
        location_match = re.search(r"\(([^()]{2,100})\)\s*$", title)
        if location_match:
            location = location_match.group(1).strip()

        description_location = re.search(
            r"(?:Location|Lieu d'affectation|Duty Station)\s*:\s*([^\n]+)",
            description,
            re.IGNORECASE,
        )
        if description_location:
            location = description_location.group(1).strip()[:300]

        detail = (
            "Source officielle : International Labour Organization (ILO/OIT)\n"
            f"Date de publication : {published or 'Non précisée'}\n"
            f"Lieu : {location}\n"
            "Vérifier la date limite, les critères d'éligibilité, le contrat "
            "et les conditions de mobilité sur la fiche officielle.\n\n"
            f"{description}\n\n"
            f"Fiche officielle : {canonical_url}"
        )

        job = normalize_job(
            {
                "title": title,
                "company": "International Labour Organization (ILO/OIT)",
                "location": location,
                "description": detail,
                "url": canonical_url,
                "id": external_id,
                "publication_date": published,
                "job_type": "Non précisé",
            },
            "ILO Careers",
        )
        if job:
            job["external_id"] = external_id
            jobs.append(job)

    logger.info(
        "ILO Careers : %d offres IT retenues sur %d annonces RSS",
        len(jobs), len(items),
    )
    return jobs


async def collect_euraxess(client):
    """Lit au plus trois pages publiques EURAXESS et retient les offres IT."""
    from urllib.parse import urljoin

    jobs = []
    seen = set()
    total = 0

    for page in range(3):
        response = await client.get(
            EURAXESS_SEARCH_URL,
            params={'page': page},
            headers={'User-Agent': 'JobCiAddunaAI/0.2 (public job discovery)'},
        )
        response.raise_for_status()
        content = response.content
        if len(content) > 5 * 1024 * 1024:
            raise ValueError('Page EURAXESS trop volumineuse : limite de 5 Mo dépassée.')

        soup = BeautifulSoup(content, 'html.parser')
        cards = soup.select('div.ecl-content-item__content-block')
        if not cards:
            cards = soup.select('h3.ecl-content-block__title')

        for card in cards:
            link = card.select_one('h3.ecl-content-block__title a[href]') \
                if card.name != 'h3' else card.select_one('a[href]')
            if link is None:
                continue

            url = urljoin(EURAXESS_SEARCH_URL, link.get('href', '').strip())
            if not re.fullmatch(
                r'https://euraxess\.ec\.europa\.eu/jobs/\d+',
                url,
                re.IGNORECASE,
            ):
                continue
            if url in seen:
                continue
            seen.add(url)
            total += 1

            item = link.find_parent('li') or card
            title = link.get_text(' ', strip=True)
            description_node = item.select_one('.ecl-content-block__description')
            description = description_node.get_text(' ', strip=True) if description_node else ''
            department_node = item.select_one('.id-Department .ecl-text-standard')
            company = department_node.get_text(' ', strip=True) if department_node else ''
            if not company:
                card_text = item.get_text(' ', strip=True)
                posted_match = re.search(
                    r'^\s*(.+?)\s+Posted on:\s*\d{1,2}\s+\w+\s+\d{4}',
                    card_text,
                    re.IGNORECASE,
                )
                company = posted_match.group(1).strip() if posted_match else 'EURAXESS — organisme à vérifier'

            location_node = item.select_one('.id-Work-Locations .ecl-text-standard')
            location = location_node.get_text(' ', strip=True) if location_node else ''
            country_node = item.select_one('.ecl-label--highlight')
            country = country_node.get_text(' ', strip=True) if country_node else ''
            field_node = item.select_one('.id-Research-Field .ecl-text-standard')
            research_field = field_node.get_text(' ', strip=True) if field_node else ''
            searchable = ' '.join((title, description, research_field))
            if not _EURAXESS_IT_TERMS.search(searchable):
                continue

            card_text = item.get_text(' ', strip=True)
            date_match = re.search(
                r'Posted on:\s*(\d{1,2}\s+\w+\s+\d{4})',
                card_text,
                re.IGNORECASE,
            )
            raw = {
                'id': url.rsplit('/', 1)[-1],
                'title': title,
                'company': company,
                'location': location or country or 'Non précisé',
                'description': description,
                'url': url,
                'publication_date': date_match.group(1) if date_match else None,
                'job_type': 'Offre EURAXESS — contrat à vérifier',
            }
            job = normalize_job(raw, 'EURAXESS')
            if job:
                job['external_id'] = url.rsplit('/', 1)[-1]
                if country:
                    job['country'] = country
                jobs.append(job)

    logger.info(
        'EURAXESS : %d offres informatiques retenues sur %d annonces examinées (3 pages max)',
        len(jobs), total,
    )
    return jobs



EXPAT_DAKAR_SITEMAPS = (
    "https://www.expat-dakar.com/sitemap-listings-emploi-informatique-fr.xml",
    "https://www.expat-dakar.com/sitemap-listings-emploi-service-client-support-technique-fr.xml",
)
EXPAT_DAKAR_IT_TERMS = re.compile(
    r"\b(informatique|informaticien|développeur|developer|software|"
    r"full[\s-]?stack|backend|back[\s-]?end|frontend|front[\s-]?end|"
    r"java|spring boot|angular|react|vue\.?js|php|laravel|symfony|"
    r"python|javascript|typescript|devops|cloud|cyber.?sécurité|"
    r"cybersecurity|data engineer|data scientist|base[s]? de données|"
    r"database|administrateur réseau|support technique|helpdesk|"
    r"webmaster|intelligence artificielle|machine learning|"
    r"technicien informatique|système[s]? d'information)\b",
    re.IGNORECASE,
)
EXPAT_DAKAR_REJECT = re.compile(
    r"\b(demande d'emploi|demandeur d'emploi|recherche un emploi|"
    r"cherche un emploi|offre de service|prestation[s]? de service|"
    r"je propose mes services|candidat[e]?\s+à\s+la recherche)\b",
    re.IGNORECASE,
)


async def collect_expat_dakar(client):
    """Collecte limitée d'annonces IT publiques depuis les sitemaps officiels."""
    from urllib.parse import urlparse
    from datetime import date

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}
    urls = []
    seen = set()

    for sitemap_url in EXPAT_DAKAR_SITEMAPS:
        response = await client.get(sitemap_url, headers=headers)
        response.raise_for_status()
        content = response.content
        if len(content) > 2 * 1024 * 1024:
            raise ValueError("Sitemap Expat-Dakar supérieur à 2 Mo.")
        root = ET.fromstring(content)
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] != "loc" or not node.text:
                continue
            url = node.text.strip()
            parsed = urlparse(url)
            if (parsed.scheme == "https"
                    and parsed.hostname == "www.expat-dakar.com"
                    and parsed.path.startswith("/annonce/")
                    and not parsed.query and not parsed.fragment
                    and url not in seen):
                seen.add(url)
                urls.append(url)
                if len(urls) >= 40:
                    break
        if len(urls) >= 40:
            break

    jobs = []
    for url in urls:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        content = response.content
        if len(content) > 2 * 1024 * 1024:
            continue

        soup = BeautifulSoup(content, "html.parser")
        postings = []

        def walk(value):
            if isinstance(value, dict):
                types = value.get("@type", [])
                if isinstance(types, str):
                    types = [types]
                if "JobPosting" in types:
                    postings.append(value)
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                walk(json.loads(script.string or script.get_text()))
            except (ValueError, TypeError):
                continue

        posting = postings[0] if postings else {}
        title = str(posting.get("title") or
                    (soup.title.get_text(" ", strip=True) if soup.title else ""))
        title = re.sub(r"\s*[|–-]\s*Expat-Dakar.*$", "", title, flags=re.I).strip()
        meta = soup.find("meta", attrs={"name": "description"})
        description = str(posting.get("description") or
                           (meta.get("content", "") if meta else ""))
        description = BeautifulSoup(description, "html.parser").get_text(" ", strip=True)

        if not title or EXPAT_DAKAR_REJECT.search(title + " " + description):
            continue
        if not EXPAT_DAKAR_IT_TERMS.search(title + " " + description):
            continue
        if not postings:
            # Without JobPosting metadata, require explicit offer wording.
            if not re.search(r"offre d'emploi|recrutement|nous recrutons",
                             description, re.I):
                continue

        employer = posting.get("hiringOrganization") or {}
        if isinstance(employer, list):
            employer = employer[0] if employer else {}
        company = employer.get("name", "") if isinstance(employer, dict) else str(employer)
        if not company:
            company = "Expat-Dakar — employeur à vérifier"

        place = posting.get("jobLocation") or {}
        if isinstance(place, list):
            place = place[0] if place else {}
        address = place.get("address", {}) if isinstance(place, dict) else {}
        if isinstance(address, list):
            address = address[0] if address else {}
        locality = address.get("addressLocality", "") if isinstance(address, dict) else ""
        region = address.get("addressRegion", "") if isinstance(address, dict) else ""
        location = ", ".join(x for x in (locality, region, "Sénégal") if x)
        if not location:
            location = "Sénégal"

        raw = {
            "id": url.rstrip("/").rsplit("-", 1)[-1],
            "title": title,
            "company": company,
            "location": location,
            "description": description,
            "url": url,
            "publication_date": posting.get("datePosted"),
            "job_type": posting.get("employmentType") or "À vérifier",
        }
        job = normalize_job(raw, "Expat-Dakar")
        if job:
            job["country"] = "Sénégal"
            job["external_id"] = raw["id"]
            jobs.append(job)

    logger.info("Expat-Dakar : %d offres IT retenues sur %d URLs examinées",
                len(jobs), len(urls))
    return jobs


LIGGEY_CATEGORY_URL = "https://liggey.com/emplois/developpement-it/dakar"
LIGGEY_IT_TERMS = re.compile(
    r"\b(développeur|développeuse|développement|developpeur|developpeuse|developpement|developer|software|informatique|"
    r"full[\s-]?stack|back[\s-]?end|backend|front[\s-]?end|frontend|"
    r"java|spring|angular|react|vue\.?js|php|laravel|symfony|python|"
    r"javascript|typescript|devops|cloud|cybersecurite|cybersecurity|"
    r"data architect|architecte data|architecte donnees|data engineer|"
    r"data scientist|base[s]? de donnees|database|reseau informatique|"
    r"systemes informatiques|ingenieur systeme|ingenieur informatique|"
    r"administrateur systeme|technicien informatique|machine learning|"
    r"intelligence artificielle|analyste programmeur)\b",
    re.IGNORECASE,
)
LIGGEY_REJECT_TITLE = re.compile(
    r"\b(apporteur d[’']affaires|comptable|commercial|commerciale|"
    r"vendeur|vendeuse|sales|marketing)\b",
    re.IGNORECASE,
)


async def collect_liggey(client):
    """Extrait des offres IT depuis la page publique et les JobPosting Liggey."""
    from urllib.parse import urljoin, urlsplit, urlunsplit

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}

    response = await client.get(LIGGEY_CATEGORY_URL, headers=headers)
    response.raise_for_status()
    content = response.content
    if len(content) > 2 * 1024 * 1024:
        raise ValueError("Page catégorie Liggey supérieure à 2 Mo.")

    soup = BeautifulSoup(content, "html.parser")
    urls = []
    seen = set()

    # Seules les annonces HTTPS du domaine attendu sont acceptées.
    for anchor in soup.find_all("a", href=True):
        candidate = urljoin(LIGGEY_CATEGORY_URL, anchor["href"])
        parsed = urlsplit(candidate)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "liggey.com"
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.path.startswith("/missions/")
        ):
            continue

        canonical_url = urlunsplit(("https", "liggey.com", parsed.path, "", ""))
        if canonical_url not in seen:
            seen.add(canonical_url)
            urls.append(canonical_url)
        if len(urls) >= 40:
            break

    jobs = []

    def walk_jsonld(value, postings):
        if isinstance(value, dict):
            types = value.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if "JobPosting" in types:
                postings.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk_jsonld(child, postings)
        elif isinstance(value, list):
            for child in value:
                walk_jsonld(child, postings)

    for url in urls:
        try:
            detail = await client.get(url, headers=headers)
            detail.raise_for_status()
            page_content = detail.content
            if len(page_content) > 2 * 1024 * 1024:
                continue
        except Exception as exc:
            logger.warning("Liggey : échec de lecture d'une annonce : %s", exc)
            continue

        page = BeautifulSoup(page_content, "html.parser")
        postings = []
        for script in page.find_all("script", type="application/ld+json"):
            try:
                walk_jsonld(json.loads(script.string or script.get_text()), postings)
            except (ValueError, TypeError):
                continue

        if not postings:
            continue

        posting = postings[0]
        title = str(posting.get("title") or "").strip()
        description = BeautifulSoup(
            str(posting.get("description") or ""), "html.parser"
        ).get_text(" ", strip=True)

        if not title or LIGGEY_REJECT_TITLE.search(title):
            continue
        if not LIGGEY_IT_TERMS.search(title + " " + description):
            continue

        employer = posting.get("hiringOrganization") or {}
        if isinstance(employer, list):
            employer = employer[0] if employer else {}
        company = (
            employer.get("name", "")
            if isinstance(employer, dict)
            else str(employer)
        )
        if not company:
            company = "Liggey — employeur à vérifier"

        place = posting.get("jobLocation") or {}
        if isinstance(place, list):
            place = place[0] if place else {}
        address = place.get("address", {}) if isinstance(place, dict) else {}
        if isinstance(address, list):
            address = address[0] if address else {}
        if isinstance(address, dict):
            locality = str(address.get("addressLocality") or "").strip()
            region = str(address.get("addressRegion") or "").strip()
            country_name = str(address.get("addressCountry") or "").strip()
            if isinstance(address.get("addressCountry"), dict):
                country_name = str(address["addressCountry"].get("name") or "")
            location = ", ".join(
                part for part in (locality, region, country_name or "Sénégal") if part
            )
        else:
            location = "Sénégal"
        if not location:
            location = "Sénégal"

        employment = posting.get("employmentType") or "À vérifier"
        if isinstance(employment, list):
            employment = ", ".join(str(x) for x in employment)

        raw = {
            "id": url.rstrip("/").rsplit("/", 1)[-1],
            "title": title,
            "company": company,
            "location": location,
            "description": description,
            "url": url,
            "publication_date": posting.get("datePosted"),
            "job_type": employment,
        }
        job = normalize_job(raw, "Liggey")
        if job:
            job["external_id"] = raw["id"]
            jobs.append(job)

    logger.info(
        "Liggey : %d offres IT retenues sur %d annonces examinées",
        len(jobs), len(urls),
    )
    return jobs


async def collect_arbeitnow(client):
    data = await fetch_json(client, 'https://www.arbeitnow.com/api/job-board-api')
    jobs = data.get('data', []) if isinstance(data, dict) else []
    if not isinstance(jobs, list):
        return []
    return [x for raw in jobs if isinstance(raw, dict)
            if (x := normalize_job(raw, 'Arbeitnow API'))]

async def collect_remotive(client):
    gathered = []
    for term in ('Java', 'Spring Boot', 'Angular'):
        try:
            data = await fetch_json(client, 'https://remotive.com/api/remote-jobs', {'search': term, 'limit': 50})
            for raw in data.get('jobs', []) if isinstance(data, dict) else []:
                item = normalize_job(raw, 'Remotive API')
                if item: gathered.append(item)
        except Exception as exc:
            logger.warning('Remotive (%s) indisponible: %s', term, exc)
    return gathered

async def collect_greenhouse(client):
    boards = [x.strip() for x in os.getenv('GREENHOUSE_BOARDS', '').split(',') if x.strip()]
    gathered = []
    for board in boards:
        data = await fetch_json(client, f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs', {'content':'true'})
        for raw in data.get('jobs', []):
            raw = {**raw, 'company': raw.get('company') or board}
            item = normalize_job(raw, f'Greenhouse · {board}')
            if item: gathered.append(item)
    return gathered

async def collect_lever(client):
    companies = [x.strip() for x in os.getenv('LEVER_SITES', '').split(',') if x.strip()]
    gathered = []
    for site in companies:
        data = await fetch_json(client, f'https://api.lever.co/v0/postings/{site}', {'mode':'json'})
        for raw in data if isinstance(data, list) else []:
            raw = {**raw, 'company': raw.get('company') or site, 'location': (raw.get('categories') or {}).get('location') or ''}
            item = normalize_job(raw, f'Lever · {site}')
            if item: gathered.append(item)
    return gathered


SMARTRECRUITERS_API = "https://api.smartrecruiters.com/v1/companies"
SMARTRECRUITERS_DEFAULT_COMPANIES = ("ALTEN", "OECD")

SMARTRECRUITERS_IT_TITLE = re.compile(
    r"\b(software|developer|développeur|développeuse|"
    r"full[\s-]?stack|frontend|front[\s-]?end|backend|back[\s-]?end|"
    r"programmer|programming|java|angular|react|vue\.?js|"
    r"php|symfony|laravel|flutter|mobile developer|"
    r"devops|cloud engineer|data engineer|"
    r"IT engineer|software architect|solution architect|"
    r"tech lead|technical lead|QA automation|test automation|"
    r"cybersecurity|cyber security|security engineer|"
    r"ingénieur logiciel|ingénieur informatique|"
    r"développement web|développeur web|"
    r"administrateur systèmes|systems engineer)\b",
    re.IGNORECASE,
)


def _smartrecruiters_text(value):
    """Extract readable text from SmartRecruiters job-ad sections."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result = []
        for key, child in value.items():
            if key.lower() in {"text", "content", "description", "title", "value"}:
                result.extend(_smartrecruiters_text(child))
            elif isinstance(child, (dict, list)):
                result.extend(_smartrecruiters_text(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(_smartrecruiters_text(child))
        return result
    return []


def _smartrecruiters_location(value):
    if isinstance(value, dict):
        parts = [
            value.get("city"),
            value.get("region"),
            value.get("country"),
            value.get("name"),
        ]
        return ", ".join(dict.fromkeys(
            str(part).strip() for part in parts if part and str(part).strip()
        ))
    if isinstance(value, list):
        return ", ".join(
            _smartrecruiters_location(item) if isinstance(item, dict) else str(item)
            for item in value if item
        )
    return str(value or "")


async def collect_smartrecruiters(client):
    """
    Generic SmartRecruiters public API collector.

    Companies are configured through SMARTRECRUITERS_COMPANIES as comma-separated
    company identifiers. ALTEN and OECD are verified starter entries.
    Pagination is bounded; each company's failure is isolated.
    """
    configured = os.getenv("SMARTRECRUITERS_COMPANIES", "").strip()
    companies = configured.split(",") if configured else list(
        SMARTRECRUITERS_DEFAULT_COMPANIES
    )
    companies = list(dict.fromkeys(
        item.strip() for item in companies
        if item.strip() and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", item.strip())
    ))

    try:
        max_pages = int(os.getenv("SMARTRECRUITERS_MAX_PAGES", "5"))
    except ValueError:
        max_pages = 5
    max_pages = max(1, min(max_pages, 10))
    page_size = 100
    gathered = []

    for company_slug in companies:
        company_jobs = []
        seen_ids = set()
        try:
            for page in range(max_pages):
                offset = page * page_size
                endpoint = f"{SMARTRECRUITERS_API}/{company_slug}/postings"
                data = await fetch_json(
                    client, endpoint, {"limit": page_size, "offset": offset}
                )
                if not isinstance(data, dict):
                    break

                postings = data.get("content", [])
                if not isinstance(postings, list) or not postings:
                    break

                for posting in postings:
                    if not isinstance(posting, dict):
                        continue

                    title = str(posting.get("name") or "").strip()
                    posting_id = str(posting.get("id") or "").strip()
                    if not title or not posting_id or posting_id in seen_ids:
                        continue
                    seen_ids.add(posting_id)

                    # Filter by title before making the additional detail request.
                    if not SMARTRECRUITERS_IT_TITLE.search(title):
                        continue

                    detail_url = (
                        f"{SMARTRECRUITERS_API}/{company_slug}/postings/{posting_id}"
                    )
                    try:
                        detail = await fetch_json(client, detail_url)
                    except Exception as exc:
                        logger.warning(
                            "SmartRecruiters %s (%s) : détail indisponible : %s",
                            company_slug, posting_id, exc,
                        )
                        detail = {}

                    if not isinstance(detail, dict):
                        detail = {}

                    company_data = detail.get("company") or {}
                    company_name = (
                        company_data.get("name")
                        if isinstance(company_data, dict) else None
                    ) or company_slug

                    job_ad = detail.get("jobAd") or {}
                    sections = job_ad.get("sections", {}) if isinstance(job_ad, dict) else {}
                    description_parts = _smartrecruiters_text(sections)
                    description = "\n\n".join(dict.fromkeys(
                        part.strip() for part in description_parts if part.strip()
                    ))

                    location = _smartrecruiters_location(
                        posting.get("location") or detail.get("location")
                    )
                    employment = detail.get("typeOfEmployment") or {}
                    if isinstance(employment, dict):
                        employment = employment.get("label") or employment.get("name") or ""
                    if not employment:
                        employment = "Non précisé"

                    url = (
                        detail.get("postingUrl")
                        or posting.get("postingUrl")
                        or detail.get("applyUrl")
                        or posting.get("applyUrl")
                    )
                    if not url or not str(url).startswith("https://"):
                        continue

                    raw = {
                        "id": posting_id,
                        "title": title,
                        "company": company_name,
                        "location": location,
                        "description": description,
                        "url": url,
                        "publication_date": (
                            detail.get("releasedDate")
                            or posting.get("releasedDate")
                        ),
                        "job_type": employment,
                    }
                    item = normalize_job(
                        raw, f"SmartRecruiters · {company_slug}"
                    )
                    if item:
                        # Preserve the provider's stable posting ID for deduplication.
                        item["external_id"] = posting_id
                        company_jobs.append(item)

                total = data.get("totalFound")
                if len(postings) < page_size:
                    break
                if isinstance(total, int) and offset + len(postings) >= total:
                    break

            gathered.extend(company_jobs)
            logger.info(
                "SmartRecruiters %s : %d offres IT retenues",
                company_slug, len(company_jobs),
            )
        except Exception as exc:
            logger.warning(
                "SmartRecruiters %s indisponible : %s", company_slug, exc
            )

    return gathered



ICRC_JOBS_URL = "https://careers.icrc.org/go/All-Jobs/3807301/"
ICRC_BASE_URL = "https://careers.icrc.org"
_ICRC_IT_TITLE = re.compile(
    r"\b(software|developer|development|programmer|programming|"
    r"full[\s-]?stack|back[\s-]?end|front[\s-]?end|"
    r"information technology|ICT|IT specialist|IT officer|"
    r"data engineer|data scientist|data analyst|cybersecurity|"
    r"cloud engineer|DevOps|ERP engineer|systems engineer|"
    r"database administrator|application engineer|"
    r"digital technology|digital solutions|"
    r"quality assurance|test automation|"
    r"mobile application|web engineer|web developer)\b",
    re.IGNORECASE,
)


def _icrc_deadline(text):
    """Renvoie une date limite reconnue, ou None si elle est inconnue."""
    from datetime import date
    from email.utils import parsedate_to_datetime

    text = str(text or "")
    match = re.search(
        r"(?:Deadline\s+of\s+Application|Application\s+Deadline|"
        r"Closing\s+Date)\s*:\s*"
        r"([A-Za-z]+\s+\d{1,2},?\s+\d{4}|"
        r"\d{1,2}\s+[A-Za-z]+\s+\d{4}|"
        r"\d{1,2}[-/]\d{1,2}[-/]\d{4})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    value = match.group(1).replace(",", "").strip()
    for fmt in ("%B %d %Y", "%b %d %Y", "%d %B %Y",
                "%d %b %Y", "%d-%m-%Y", "%d/%m/%Y",
                "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


async def collect_icrc(client):
    """Collecte limitée des postes informatiques du portail public du CICR."""
    from datetime import date
    from urllib.parse import urljoin, urlparse

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}

    try:
        response = await client.get(ICRC_JOBS_URL, headers=headers)
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Catalogue CICR indisponible : %s", type(exc).__name__)
        return []

    if len(response.content) > 5 * 1024 * 1024:
        logger.warning("Catalogue CICR trop volumineux ; ignoré.")
        return []

    soup = BeautifulSoup(response.content, "html.parser")
    candidates = {}

    for link in soup.select('a[href*="/job/"]'):
        title = clean_description(link.get_text(" ", strip=True))
        href = urljoin(ICRC_BASE_URL, link.get("href", ""))
        parsed = urlparse(href)

        if (
            not title
            or not _ICRC_IT_TITLE.search(title)
            or parsed.scheme != "https"
            or parsed.hostname != "careers.icrc.org"
            or not re.fullmatch(r"/job/[^?#]+/\d+/?", parsed.path)
        ):
            continue

        canonical = f"{ICRC_BASE_URL}{parsed.path.rstrip('/')}/"
        candidates.setdefault(canonical, title[:200])

    jobs = []
    today = date.today()

    # Limite les requêtes par cycle ; le catalogue reste la source officielle.
    for url, listed_title in list(candidates.items())[:40]:
        try:
            detail_response = await client.get(url, headers=headers)
            detail_response.raise_for_status()

            if len(detail_response.content) > 5 * 1024 * 1024:
                continue

            page = BeautifulSoup(detail_response.content, "html.parser")
            heading = page.find("h1")
            title = clean_description(
                heading.get_text(" ", strip=True) if heading else listed_title
            )
            body = clean_description(page.get_text("\n", strip=True))

            if not title or not _ICRC_IT_TITLE.search(title):
                continue

            deadline = _icrc_deadline(body)
            if deadline and deadline < today:
                continue

            def field(pattern):
                found = re.search(pattern, body, re.IGNORECASE)
                return found.group(1).strip(" \t:|-")[:300] if found else ""

            location = field(
                r"Job location\s*:?\s*(.*?)"
                r"(?=\s+Contract type\b|\s+Deadline of Application\b|\Z)"
            )
            contract = field(
                r"Contract type\s*:?\s*(.*?)"
                r"(?=\s+Deadline of Application\b|\s+Job Description\b|\Z)"
            )

            # La fiche entière est conservée comme description, y compris
            # les instructions utiles à l'évaluation de la mobilité.
            raw = {
                "id": url.rstrip("/").rsplit("/", 1)[-1],
                "title": title,
                "company": "International Committee of the Red Cross (ICRC)",
                "location": location or "Non précisé",
                "description": body,
                "url": url,
                "publication_date": None,
                "job_type": contract or "Non précisé",
            }
            item = normalize_job(raw, "ICRC Careers")
            if item:
                item["external_id"] = raw["id"]
                jobs.append(item)

        except Exception as exc:
            logger.warning(
                "Fiche CICR ignorée (%s) : %s",
                url, type(exc).__name__,
            )
            continue

    return jobs






# Médecins Sans Frontières — portail officiel français.
MSF_JOBS_URL = (
    "https://www.msf.fr/agir/rejoindre-nos-equipes/offres-emploi"
)
MSF_BASE_URL = "https://www.msf.fr"
_MSF_IT_TITLE = re.compile(
    r"\b(d[eé]veloppeur|d[eé]veloppeuse|software|full[\s-]?stack|"
    r"front[\s-]?end|back[\s-]?end|informatique|informaticien|"
    r"informaticienne|syst[eè]mes?\s+d['’]information|"
    r"ing[eé]nieur.{0,25}(logiciel|informatique|donn[eé]es)|"
    r"data\s+(engineer|scientist|analyst)|cyber[\s-]?s[eé]curit[eé]|"
    r"administrateur.{0,20}(syst[eè]me|r[eé]seau|base de donn[eé]es)|"
    r"technicien.{0,20}(informatique|support|syst[eè]me)|"
    r"chef.{0,20}projet.{0,20}(digital|num[eé]rique|informatique)|"
    r"num[eé]rique|digital|webmaster|application.{0,20}(IT|informatique))\b",
    re.IGNORECASE,
)


def _msf_job_posting(value):
    """Retrouve un objet JobPosting dans du JSON-LD, y compris @graph."""
    if isinstance(value, dict):
        types = value.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if "JobPosting" in types:
            return value
        for child in value.values():
            found = _msf_job_posting(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _msf_job_posting(child)
            if found:
                return found
    return None


def _msf_date(value):
    """Interprète une date ISO ou une date ISO avec heure."""
    from datetime import date

    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None


async def collect_msf(client):
    """Collecte les offres IT pertinentes depuis le portail officiel MSF."""
    from datetime import date
    from urllib.parse import urljoin, urlparse

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}
    try:
        response = await client.get(MSF_JOBS_URL, headers=headers)
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Catalogue MSF indisponible : %s", type(exc).__name__)
        return []

    if len(response.content) > 5 * 1024 * 1024:
        logger.warning("Catalogue MSF trop volumineux ; ignoré.")
        return []

    soup = BeautifulSoup(response.content, "html.parser")
    candidates = {}

    for link in soup.select("a[href]"):
        title = clean_description(link.get_text(" ", strip=True))
        parsed = urlparse(urljoin(MSF_BASE_URL, link.get("href", "")))
        if (
            not title
            or not _MSF_IT_TITLE.search(title)
            or parsed.scheme != "https"
            or parsed.hostname != "www.msf.fr"
            or not parsed.path.startswith(
                "/agir/rejoindre-nos-equipes/toutes-nos-offres-emploi/"
            )
        ):
            continue
        canonical = f"{MSF_BASE_URL}{parsed.path.rstrip('/')}"
        candidates.setdefault(canonical, title[:200])

    jobs = []
    today = date.today()

    for url, listed_title in list(candidates.items())[:30]:
        try:
            detail_response = await client.get(url, headers=headers)
            detail_response.raise_for_status()
            if len(detail_response.content) > 5 * 1024 * 1024:
                continue

            page = BeautifulSoup(detail_response.content, "html.parser")
            posting = None
            for script in page.select('script[type="application/ld+json"]'):
                try:
                    posting = _msf_job_posting(json.loads(script.string or script.get_text()))
                except (ValueError, TypeError):
                    continue
                if posting:
                    break

            heading = page.find("h1")
            title = clean_description(
                (posting or {}).get("title")
                or (heading.get_text(" ", strip=True) if heading else listed_title)
            )
            if not title or not _MSF_IT_TITLE.search(title):
                continue

            valid_through = _msf_date((posting or {}).get("validThrough"))
            if valid_through and valid_through < today:
                continue

            body = clean_description(page.get_text("\n", strip=True))
            if valid_through:
                body += f"\nDate limite publiée par MSF : {valid_through.isoformat()}"

            published = (posting or {}).get("datePosted")
            if published:
                published = str(published)[:10]

            location_parts = []
            for loc in (posting or {}).get("jobLocation", []) if isinstance(
                (posting or {}).get("jobLocation", []), list
            ) else [(posting or {}).get("jobLocation", {})]:
                if not isinstance(loc, dict):
                    continue
                address = loc.get("address", {})
                if isinstance(address, dict):
                    location_parts.extend(
                        str(address[k]).strip()
                        for k in ("addressLocality", "addressRegion", "addressCountry")
                        if address.get(k)
                    )
            location = ", ".join(dict.fromkeys(location_parts))

            identifier = (posting or {}).get("identifier")
            if isinstance(identifier, dict):
                identifier = identifier.get("value")
            identifier = str(identifier or url.rsplit("/", 1)[-1])

            raw = {
                "id": identifier,
                "title": title,
                "company": "Médecins Sans Frontières (MSF)",
                "location": location or "Non précisé",
                "description": body,
                "url": url,
                "publication_date": published,
                "job_type": (posting or {}).get("employmentType") or "Non précisé",
            }
            item = normalize_job(raw, "MSF Careers")
            if item:
                item["external_id"] = identifier
                jobs.append(item)

        except Exception as exc:
            logger.warning(
                "Fiche MSF ignorée (%s) : %s", url, type(exc).__name__
            )

    return jobs


# Norwegian Refugee Council (NRC) — portail public Oracle Recruiting.
NRC_API_BASE = "https://ekum.fa.em2.oraclecloud.com"
NRC_SITE_NUMBER = "CX_2019"
NRC_LIST_ENDPOINT = (
    f"{NRC_API_BASE}/hcmRestApi/resources/11.13.18.05/"
    "recruitingCEJobRequisitions"
)
NRC_DETAIL_ENDPOINT = (
    f"{NRC_API_BASE}/hcmRestApi/resources/11.13.18.05/"
    "recruitingCEJobRequisitionDetails"
)
NRC_CAREERS_BASE = (
    f"{NRC_API_BASE}/hcmUI/CandidateExperience/en/sites/{NRC_SITE_NUMBER}"
)
_NRC_RELEVANT_TITLE = re.compile(
    r"\b(software|developer|development|programmer|programming|"
    r"full[\s-]?stack|back[\s-]?end|front[\s-]?end|"
    r"information technology|ICT|IT officer|IT specialist|"
    r"database|data engineer|data scientist|data analyst|"
    r"information management|digital officer|digital technology|"
    r"cybersecurity|cyber security|cloud engineer|DevOps|"
    r"systems engineer|system administrator|web developer|"
    r"application developer|application engineer|"
    r"business intelligence|Power BI|SQL developer)\b",
    re.IGNORECASE,
)


def _nrc_find_value(payload, key):
    """Recherche une valeur dans les enveloppes JSON Oracle imbriquées."""
    if isinstance(payload, dict):
        if key in payload and payload[key] is not None:
            return payload[key]
        for value in payload.values():
            found = _nrc_find_value(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _nrc_find_value(value, key)
            if found is not None:
                return found
    return None


def _nrc_requisition_list(payload):
    """Extrait la liste de réquisitions d'une réponse Oracle."""
    if isinstance(payload, dict):
        rows = payload.get("requisitionList")
        if isinstance(rows, list):
            return rows
        for value in payload.values():
            found = _nrc_requisition_list(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _nrc_requisition_list(value)
            if found is not None:
                return found
    return None


def _nrc_date(value):
    """Convertit une date Oracle en date locale ; valeur inconnue = None."""
    from datetime import date

    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        pass

    for fmt in ("%d %B %Y", "%B %d, %Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


async def collect_nrc(client):
    """Collecte les offres IT/numériques publiques du portail officiel NRC."""
    from datetime import date

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}
    gathered = {}
    offset = 0
    page_size = 25
    total = None

    # Pagination bornée : ne suit aucune URL fournie par les données reçues.
    for _ in range(20):
        params = {
            "onlyData": "true",
            "finder": (
                f"findReqs;siteNumber={NRC_SITE_NUMBER},"
                f"offset={offset},limit={page_size}"
            ),
            "expand": "requisitionList",
        }
        try:
            response = await client.get(
                NRC_LIST_ENDPOINT, params=params, headers=headers
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("Catalogue NRC indisponible (%s).", type(exc).__name__)
            return []

        rows = _nrc_requisition_list(payload)
        if rows is None:
            logger.warning("Réponse NRC sans liste de réquisitions reconnue.")
            return []

        if total is None:
            try:
                total = int(_nrc_find_value(payload, "TotalJobsCount") or 0)
            except (ValueError, TypeError):
                total = 0

        for row in rows:
            if not isinstance(row, dict):
                continue
            title = clean_description(row.get("Title") or "")
            identifier = str(row.get("Id") or "").strip()
            if identifier and title and _NRC_RELEVANT_TITLE.search(title):
                gathered.setdefault(identifier, row)

        offset += len(rows)
        if not rows or (total and offset >= total) or len(rows) < page_size:
            break

    jobs = []
    today = date.today()

    for identifier, row in gathered.items():
        title = clean_description(row.get("Title") or "")
        location = clean_description(
            row.get("PrimaryLocation") or row.get("PrimaryLocationCountry") or ""
        )
        country = clean_description(row.get("PrimaryLocationCountry") or "")
        list_deadline = row.get("PostingEndDate")
        detail_url = f"{NRC_CAREERS_BASE}/job/{identifier}"

        detail_params = {
            "onlyData": "true",
            "finder": f"ById;Id={identifier},siteNumber={NRC_SITE_NUMBER}",
        }
        try:
            response = await client.get(
                NRC_DETAIL_ENDPOINT, params=detail_params, headers=headers
            )
            response.raise_for_status()
            detail_payload = response.json()
            detail = _nrc_find_value(detail_payload, "ExternalDescriptionStr")
            responsibilities = _nrc_find_value(
                detail_payload, "ExternalResponsibilitiesStr"
            )
            qualifications = _nrc_find_value(
                detail_payload, "ExternalQualificationsStr"
            )
            detail_deadline = _nrc_find_value(
                detail_payload, "ExternalPostedEndDate"
            )
        except Exception as exc:
            logger.warning(
                "Fiche NRC %s ignorée (%s).", identifier, type(exc).__name__
            )
            continue

        deadline_value = detail_deadline or list_deadline
        deadline = _nrc_date(deadline_value)
        if deadline and deadline < today:
            continue

        parts = [
            clean_description(detail),
            clean_description(responsibilities),
            clean_description(qualifications),
        ]
        description = "\n\n".join(part for part in parts if part)
        if deadline_value:
            description += (
                "\n\nDate limite publiée par NRC : " + str(deadline_value)
            )
        if country:
            description += "\nPays indiqué par NRC : " + country

        # Ne pas affirmer qu'un visa est fourni : les conditions officielles
        # sont conservées dans le texte pour permettre leur vérification.
        raw = {
            "id": identifier,
            "title": title,
            "company": "Norwegian Refugee Council (NRC)",
            "location": location or country or "Non précisé",
            "description": description or title,
            "url": detail_url,
            "publication_date": row.get("PostedDate"),
            # WorkplaceType décrit le mode de travail, pas le contrat.
            "job_type": (
                row.get("ContractType")
                or row.get("WorkerType")
                or row.get("JobType")
                or "Non précisé"
            ),
        }
        item = normalize_job(raw, "NRC Careers")
        if item:
            workplace = str(
                row.get("WorkplaceType") or row.get("WorkplaceTypeCode") or ""
            ).strip().lower()

            if workplace in {"on-site", "onsite", "ora_on_site"}:
                item["work_mode"] = "Présentiel"
            elif workplace in {"hybrid", "ora_hybrid"}:
                item["work_mode"] = "Hybride"
            elif workplace in {
                "remote", "fully remote", "work from home",
                "ora_remote", "ora_work_from_home",
            }:
                item["work_mode"] = "Télétravail"

            item["external_id"] = identifier
            if country:
                item["country"] = country
            jobs.append(item)

    return jobs





# UNIDO — portail public officiel de recrutement.
UNIDO_BASE_URL = "https://careers.unido.org"
UNIDO_SEARCH_URL = UNIDO_BASE_URL + "/search/"
_UNIDO_IT_TITLE_RE = re.compile(
    r"\b(software|developer|programmer|programming|full[\s-]?stack|"
    r"back[\s-]?end|front[\s-]?end|web developer|mobile developer|"
    r"application developer|software architect|ICT|information technology|"
    r"IT specialist|IT officer|digital technology|digital solutions|"
    r"cybersecurity|cyber security|data engineer|data scientist|"
    r"data analyst|cloud engineer|DevOps|database administrator|"
    r"systems engineer|system administrator|business intelligence)\b",
    re.IGNORECASE,
)
_UNIDO_IT_DESCRIPTION_RE = re.compile(
    r"\b(software development|application development|web development|"
    r"mobile application development|software engineering|"
    r"information systems development|cybersecurity engineering|"
    r"cloud infrastructure|database administration|"
    r"data engineering|machine learning engineer)\b",
    re.IGNORECASE,
)
_UNIDO_SEARCH_TERMS = (
    "software", "software engineer", "developer",
    "information technology", "ICT", "digital technology",
    "cybersecurity", "data engineer", "cloud engineer",
)


def _unido_parse_deadline(body):
    """Extrait une date limite malgré les retours à la ligne du HTML."""
    from datetime import datetime

    normalized = re.sub(r"\s+", " ", body or "")
    section = re.search(
        r"Application Deadline\s*:\s*(.{0,180})",
        normalized,
        re.IGNORECASE,
    )
    if not section:
        return None, None

    value = section.group(1).strip()
    date_match = re.search(
        r"\b(\d{1,2}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|"
        r"Sep|Oct|Nov|Dec)[a-z]*[- ]\d{4}|"
        r"\d{1,2}\s+[A-Za-z]+\s+\d{4}|"
        r"[A-Za-z]+\s+\d{1,2},?\s+\d{4}|"
        r"\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})\b",
        value,
        re.IGNORECASE,
    )
    if not date_match:
        return None, value

    date_text = date_match.group(1).strip()
    formats = (
        "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y",
        "%B %d, %Y", "%B %d %Y", "%d/%m/%Y", "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(date_text, fmt).date(), date_text
        except ValueError:
            continue
    return None, date_text


async def collect_unido(client):
    """Collecte les postes IT publics UNIDO sans contourner les protections."""
    from datetime import date
    from urllib.parse import urlencode, urlparse

    headers = {
        "User-Agent": "JobCiAddunaAI/0.2 (public job discovery)",
        "Accept-Language": "en",
    }
    candidates = {}

    # Recherche bornée sur le portail officiel ; aucun lien externe suivi.
    for keyword in _UNIDO_SEARCH_TERMS:
        response = await client.get(
            UNIDO_SEARCH_URL + "?" + urlencode({"q": keyword}),
            headers=headers,
        )
        response.raise_for_status()
        if len(response.content) > 5 * 1024 * 1024:
            raise ValueError("Page de recherche UNIDO supérieure à 5 Mo.")

        soup = BeautifulSoup(response.content, "html.parser")
        for link in soup.select('a[href*="/job/"]'):
            href = (link.get("href") or "").strip()
            if not href:
                continue
            parsed = urlparse(
                href if href.startswith("https://")
                else UNIDO_BASE_URL + href
            )
            if (
                parsed.scheme != "https"
                or parsed.hostname != "careers.unido.org"
                or not re.fullmatch(r"/job/[^?#]+/\d+/?", parsed.path)
            ):
                continue

            canonical = UNIDO_BASE_URL + parsed.path
            identifier = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            candidates.setdefault(identifier, {
                "url": canonical,
                "title": clean_description(link.get_text(" ", strip=True)),
                "id": identifier,
            })

    jobs = []
    today = date.today()

    for candidate in candidates.values():
        try:
            response = await client.get(candidate["url"], headers=headers)
            response.raise_for_status()
            if len(response.content) > 5 * 1024 * 1024:
                logger.warning("Fiche UNIDO trop volumineuse, ignorée.")
                continue

            soup = BeautifulSoup(response.content, "html.parser")
            body = soup.get_text("\n", strip=True)
            heading = soup.find("h1")
            title = (
                clean_description(heading.get_text(" ", strip=True))
                if heading else candidate["title"]
            )
            if not title:
                continue

            # Les intitulés doivent être techniques ; un mot IT dans le
            # texte seul ne suffit pas à retenir une annonce administrative.
            if not _UNIDO_IT_TITLE_RE.search(title):
                continue

            deadline, deadline_text = _unido_parse_deadline(body)
            if deadline and deadline < today:
                continue

            normalized_body = re.sub(r"\s+", " ", body or "")
            local_recruitment = bool(re.search(
                r"\b(local recruitment only|local recruitment|"
                r"locally recruited|local opportunities)\b",
                normalized_body,
                re.IGNORECASE,
            ))
            location_match = re.search(
                r"(?:Location|Duty Station|Work Location)\s*:\s*([^\n\r]+)",
                body,
                re.IGNORECASE,
            )
            location = (
                clean_description(location_match.group(1))
                if location_match else "Non précisé"
            )
            contract_match = re.search(
                r"(?:Employment Type|Contract Type|Contract Duration)\s*:\s*"
                r"([^\n\r]+)",
                body,
                re.IGNORECASE,
            )
            contract = (
                clean_description(contract_match.group(1))
                if contract_match else "Non précisé"
            )

            details = [
                "Source officielle : UNIDO Careers.",
                f"Identifiant UNIDO : {candidate['id']}",
                f"Date limite publiée : {deadline_text or 'non détectée ; disponibilité à confirmer'}",
                f"Type/durée du contrat : {contract}",
                "Vérifier sur la fiche officielle les critères d'expérience, "
                "l'éligibilité selon la nationalité, le droit au travail, "
                "le visa, la relocalisation et les conditions de candidature.",
                "La présence sur le portail ne garantit pas une mobilité internationale.",
            ]
            if local_recruitment:
                details.append(
                    "ATTENTION : la fiche indique un recrutement local. "
                    "Ne pas considérer cette offre comme une mobilité "
                    "internationale confirmée."
                )

            raw = {
                "id": candidate["id"],
                "title": title,
                "company": "UNIDO",
                "location": location,
                "description": body + "\n\n" + "\n".join(details),
                "url": candidate["url"],
                "job_type": contract,
            }
            item = normalize_job(raw, "UNIDO Careers")
            if item:
                item["external_id"] = candidate["id"]
                if local_recruitment:
                    item["recruitment_scope"] = "local"
                jobs.append(item)

        except Exception as exc:
            logger.warning(
                "Fiche UNIDO %s ignorée (%s).",
                candidate["id"], type(exc).__name__,
            )
            continue

    logger.info("UNIDO Careers : %d postes techniques retenus.", len(jobs))
    return jobs




# EBRD — portail officiel de recrutement.
EBRD_BASE_URL = "https://jobs.ebrd.com"
EBRD_CATEGORY_URLS = (
    EBRD_BASE_URL + "/go/Corporate-Services/1111301/",
    EBRD_BASE_URL + "/go/Early-career-opportunities/1111501/",
)
_EBRD_IT_TITLE_RE = re.compile(
    r"\b(software|developer|development|programmer|programming|"
    r"full[\s-]?stack|front[\s-]?end|back[\s-]?end|"
    r"web developer|mobile developer|application developer|"
    r"service[\s-]?now|technology engineer|product engineer|"
    r"QA automation|quality engineer|data engineer|data scientist|"
    r"data analyst|AI engineer|engineering,\s*AI|"
    r"engineering,\s*artificial intelligence|artificial intelligence|"
    r"machine learning|cybersecurity|cyber security|"
    r"cloud engineer|DevOps|database administrator|"
    r"systems engineer|information technology|IT specialist)\b",
    re.IGNORECASE,
)


def _ebrd_date(body):
    """Retourne la date limite interprétable et le texte d'origine."""
    from datetime import datetime

    text = re.sub(r"\s+", " ", body or "")
    match = re.search(
        r"Posting End Date\s*:?\s*"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|"
        r"\d{4}-\d{2}-\d{2}|"
        r"\d{1,2}\s+[A-Za-z]+\s+\d{4}|"
        r"[A-Za-z]+\s+\d{1,2},?\s+\d{4})",
        text, re.IGNORECASE,
    )
    if not match:
        return None, None

    value = match.group(1).strip()
    for fmt in (
        "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
        "%d %B %Y", "%d %b %Y",
        "%B %d, %Y", "%B %d %Y",
    ):
        try:
            return datetime.strptime(value, fmt).date(), value
        except ValueError:
            continue
    return None, value


async def collect_ebrd(client):
    """Collecte des offres techniques depuis les pages publiques EBRD."""
    from datetime import date
    from urllib.parse import urlparse

    headers = {"User-Agent": "JobCiAddunaAI/0.2 (public job discovery)"}
    candidates = {}

    for page_url in EBRD_CATEGORY_URLS:
        response = await client.get(page_url, headers=headers)
        response.raise_for_status()
        if len(response.content) > 5 * 1024 * 1024:
            logger.warning("Page de recherche EBRD trop volumineuse.")
            continue

        soup = BeautifulSoup(response.content, "html.parser")
        for link in soup.select('a[href*="/job/"]'):
            href = (link.get("href") or "").strip()
            if not href:
                continue
            parsed = urlparse(
                href if href.startswith("https://")
                else EBRD_BASE_URL + href
            )
            if (
                parsed.scheme != "https"
                or parsed.hostname != "jobs.ebrd.com"
                or not re.fullmatch(r"/job/[^?#]+/\d+/?", parsed.path)
            ):
                continue

            identifier = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            canonical = EBRD_BASE_URL + parsed.path
            title = clean_description(link.get_text(" ", strip=True))
            candidates.setdefault(identifier, {
                "id": identifier, "url": canonical, "title": title,
            })

    jobs = []
    today = date.today()

    for candidate in candidates.values():
        try:
            response = await client.get(candidate["url"], headers=headers)
            response.raise_for_status()
            if len(response.content) > 5 * 1024 * 1024:
                logger.warning("Fiche EBRD trop volumineuse, ignorée.")
                continue

            soup = BeautifulSoup(response.content, "html.parser")
            body = soup.get_text("\n", strip=True)
            heading = soup.find("h1")
            title = (
                clean_description(heading.get_text(" ", strip=True))
                if heading else candidate["title"]
            )
            if not title or not _EBRD_IT_TITLE_RE.search(title):
                continue

            deadline, deadline_text = _ebrd_date(body)
            if deadline and deadline < today:
                continue

            normalized = re.sub(r"\s+", " ", body)
            location_match = re.search(
                r"Office City\s+(.+?)\s+Division\s+",
                normalized, re.IGNORECASE,
            )
            country_match = re.search(
                r"Office Country\s+(.+?)\s+Office City\s+",
                normalized, re.IGNORECASE,
            )
            contract_match = re.search(
                r"Contract Type\s+(.+?)\s+Contract Length\s+",
                normalized, re.IGNORECASE,
            )
            length_match = re.search(
                r"Contract Length\s+(.+?)\s+Posting End Date\s+",
                normalized, re.IGNORECASE,
            )
            posted_match = re.search(
                r"Posting Date\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
                normalized, re.IGNORECASE,
            )

            location = (
                clean_description(location_match.group(1))
                if location_match else "Non précisé"
            )
            country = (
                clean_description(country_match.group(1))
                if country_match else "Non précisé"
            )
            contract = (
                clean_description(contract_match.group(1))
                if contract_match else "Non précisé"
            )
            duration = (
                clean_description(length_match.group(1))
                if length_match else "Non précisée"
            )
            published = None
            if posted_match:
                for fmt in ("%d %b %Y", "%d %B %Y"):
                    try:
                        published = datetime.strptime(
                            posted_match.group(1), fmt
                        ).date().isoformat()
                        break
                    except ValueError:
                        pass

            details = [
                "Source officielle : EBRD Careers.",
                f"Identifiant EBRD : {candidate['id']}",
                f"Pays : {country}",
                f"Type de contrat : {contract}",
                f"Durée : {duration}",
                "Date limite : " + (
                    deadline_text if deadline_text
                    else "non détectée ; disponibilité à confirmer"
                ),
                "Vérifier les exigences du poste, l'éligibilité selon la "
                "nationalité, le droit au travail, le visa et les conditions "
                "de relocalisation sur la fiche officielle.",
            ]

            raw = {
                "id": candidate["id"],
                "title": title,
                "company": "European Bank for Reconstruction and Development (EBRD)",
                "location": location,
                "country": country,
                "description": body + "\n\n" + "\n".join(details),
                "url": candidate["url"],
                "job_type": f"{contract} — {duration}",
                "published_at": published,
            }
            item = normalize_job(raw, "EBRD Careers")
            if item:
                item["external_id"] = candidate["id"]
                jobs.append(item)

        except Exception as exc:
            logger.warning(
                "Fiche EBRD %s ignorée (%s).",
                candidate["id"], type(exc).__name__,
            )

    logger.info("EBRD Careers : %d postes techniques retenus.", len(jobs))
    return jobs


# UN Women — API publique officielle Oracle Recruiting.
UN_WOMEN_API_BASE = "https://estm.fa.em2.oraclecloud.com"
UN_WOMEN_SITE_NUMBER = "CX_1001"
UN_WOMEN_LIST_ENDPOINT = (
    f"{UN_WOMEN_API_BASE}/hcmRestApi/resources/latest/"
    "recruitingCEJobRequisitions"
)
UN_WOMEN_DETAIL_ENDPOINT = (
    f"{UN_WOMEN_API_BASE}/hcmRestApi/resources/latest/"
    "recruitingCEJobRequisitionDetails"
)
UN_WOMEN_CAREERS_BASE = (
    f"{UN_WOMEN_API_BASE}/hcmUI/CandidateExperience/en/sites/"
    f"{UN_WOMEN_SITE_NUMBER}"
)
_UN_WOMEN_IT_TITLE_RE = re.compile(
    r"\b(software|developer|development|programmer|programming|"
    r"full[\s-]?stack|back[\s-]?end|front[\s-]?end|"
    r"information technology|ICT|IT officer|IT associate|IT specialist|"
    r"database|data engineer|data scientist|data analyst|"
    r"information management|digital officer|digital technology|"
    r"cybersecurity|cyber security|cloud engineer|DevOps|"
    r"systems engineer|system administrator|web developer|"
    r"application developer|application engineer|"
    r"business intelligence|Power BI|SQL developer|"
    r"technology analyst|technology specialist|"
    r"technologies de l'information|informatique|développeur|"
    r"développeuse|ingénieur logiciel)\b",
    re.IGNORECASE,
)


async def collect_un_women(client):
    """Collecte les postes IT publics d'ONU Femmes via l'API Oracle."""
    from datetime import date

    headers = {
        "User-Agent": "JobCiAddunaAI/0.2 (public job discovery)",
        "Accept": "application/json",
        "Accept-Language": "en",
    }
    gathered = {}
    offset = 0
    page_size = 25

    # Pagination bornée et URL fixée en dur : aucun lien distant suivi.
    for _ in range(20):
        params = {
            "onlyData": "true",
            "finder": (
                f"findReqs;siteNumber={UN_WOMEN_SITE_NUMBER},"
                f"offset={offset},limit={page_size}"
            ),
            "expand": "requisitionList",
        }
        try:
            response = await client.get(
                UN_WOMEN_LIST_ENDPOINT, params=params, headers=headers
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning(
                "Catalogue ONU Femmes indisponible (%s).",
                type(exc).__name__,
            )
            return []

        rows = _nrc_requisition_list(payload)
        if rows is None:
            logger.warning(
                "Réponse ONU Femmes sans liste de réquisitions reconnue."
            )
            return []

        for row in rows:
            if not isinstance(row, dict):
                continue
            title = clean_description(row.get("Title") or "")
            identifier = str(row.get("Id") or "").strip()
            if (
                identifier.isdigit()
                and title
                and _UN_WOMEN_IT_TITLE_RE.search(title)
            ):
                gathered.setdefault(identifier, row)

        offset += len(rows)
        has_more = payload.get("hasMore") if isinstance(payload, dict) else None
        try:
            total = int(payload.get("count") or 0)
        except (ValueError, TypeError, AttributeError):
            total = 0

        if not rows:
            break
        # Oracle peut envelopper les 25 offres dans un seul objet items :
        # count/hasMore racine décrivent alors l'enveloppe, pas les offres.
        # Une page complète doit donc déclencher la page suivante.
        if len(rows) < page_size:
            break

    jobs = []
    today = date.today()

    for identifier, row in gathered.items():
        title = clean_description(row.get("Title") or "")
        location = clean_description(
            row.get("PrimaryLocation")
            or row.get("PrimaryLocationCountry")
            or ""
        )
        country = clean_description(row.get("PrimaryLocationCountry") or "")
        list_deadline = row.get("PostingEndDate")
        detail_url = f"{UN_WOMEN_CAREERS_BASE}/job/{identifier}"
        detail_params = {
            "onlyData": "true",
            "finder": (
                f"ById;Id={identifier},siteNumber={UN_WOMEN_SITE_NUMBER}"
            ),
            "expand": "all",
        }

        try:
            response = await client.get(
                UN_WOMEN_DETAIL_ENDPOINT,
                params=detail_params,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
            # Ne retenir que les données d'une fiche reconnue par son ID.
            detail_rows = _nrc_requisition_list(payload)
            detail = (
                detail_rows[0]
                if detail_rows
                else (
                    payload.get("items", [])[0]
                    if isinstance(payload, dict)
                    and isinstance(payload.get("items"), list)
                    and payload.get("items")
                    and isinstance(payload["items"][0], dict)
                    else None
                )
            )
            if not isinstance(detail, dict):
                detail = payload if isinstance(payload, dict) else {}
            detail_id = str(detail.get("Id") or "")
            if detail_id and detail_id != identifier:
                logger.warning(
                    "Fiche ONU Femmes %s ignorée : ID inattendu.",
                    identifier,
                )
                continue

            description_html = (
                detail.get("ExternalDescriptionStr")
                or detail.get("CorporateDescriptionStr")
                or detail.get("OrganizationDescriptionStr")
                or ""
            )
            responsibilities = detail.get("ExternalResponsibilitiesStr") or ""
            qualifications = detail.get("ExternalQualificationsStr") or ""
            deadline_value = (
                detail.get("ExternalPostedEndDate") or list_deadline
            )

            # Préférer la localisation détaillée et convertir les codes pays
            # Oracle connus en noms lisibles.
            detail_location = clean_description(
                detail.get("PrimaryLocation") or ""
            )
            if detail_location:
                location = detail_location

            detail_country = clean_description(
                detail.get("PrimaryLocationCountry") or ""
            )
            country_names = {
                "UA": "Ukraine", "US": "United States",
                "CA": "Canada", "SN": "Senegal", "FR": "France",
                "KE": "Kenya", "ET": "Ethiopia", "UG": "Uganda",
                "GH": "Ghana", "NG": "Nigeria", "GB": "United Kingdom",
                "CH": "Switzerland", "BE": "Belgium", "DE": "Germany",
                "IT": "Italy", "ES": "Spain", "NL": "Netherlands",
                "DK": "Denmark", "AT": "Austria", "PL": "Poland",
                "LB": "Lebanon", "JO": "Jordan", "EG": "Egypt",
                "IN": "India", "TH": "Thailand", "PH": "Philippines",
            }
            if detail_country:
                country = country_names.get(
                    detail_country.upper(), detail_country
                )
            elif location and "," in location:
                country = location.rsplit(",", 1)[-1].strip()

            # Les champs flexibles Oracle peuvent préciser la catégorie
            # de recrutement. Ne pas en déduire une mobilité internationale.
            flex_fields = detail.get("requisitionFlexFields") or []
            flex_text = " ".join(
                str(field.get("Value") or "")
                for field in flex_fields
                if isinstance(field, dict)
            ).lower() if isinstance(flex_fields, list) else ""
            recruitment_text = " ".join([
                str(detail.get("RequisitionType") or ""),
                str(detail.get("ContractType") or ""),
                flex_text,
            ]).lower()
            local_recruitment = (
                "local opportunities" in recruitment_text
                or "fta local" in recruitment_text
                or "local recruitment" in recruitment_text
            )
        except Exception as exc:
            logger.warning(
                "Fiche ONU Femmes %s ignorée (%s).",
                identifier,
                type(exc).__name__,
            )
            continue

        deadline = _nrc_date(deadline_value)
        if deadline and deadline < today:
            continue

        parts = [
            clean_description(description_html),
            clean_description(responsibilities),
            clean_description(qualifications),
        ]
        description = "\n\n".join(part for part in parts if part)
        if deadline_value:
            description += (
                "\n\nDate limite publiée par ONU Femmes : "
                + str(deadline_value)
            )
        if country:
            description += "\nPays indiqué par ONU Femmes : " + country
        if local_recruitment:
            description += (
                "\n\nATTENTION — Les champs publiés par ONU Femmes indiquent "
                "un recrutement local. Ne pas considérer cette offre comme "
                "une opportunité de mobilité internationale confirmée ; "
                "vérifier les conditions d'éligibilité sur la fiche officielle."
            )
        description += (
            "\n\nÀ vérifier sur la fiche officielle : éligibilité selon la "
            "nationalité et le type de contrat, droit au travail, visa, "
            "prise en charge du déplacement et possibilité de relocalisation. "
            "Aucune aide à la mobilité n'est présumée."
        )

        raw = {
            "id": identifier,
            "title": title,
            "company": "UN Women (ONU Femmes)",
            "location": location or country or "Non précisé",
            "description": description or title,
            "url": detail_url,
            "publication_date": (
                row.get("PostedDate")
                or detail.get("ExternalPostedStartDate")
            ),
            "job_type": (
                detail.get("ContractType")
                or detail.get("RequisitionType")
                or detail.get("WorkerType")
                or detail.get("JobType")
                or "Non précisé"
            ),
        }
        item = normalize_job(raw, "UN Women Careers")
        if not item:
            continue

        workplace = str(
            detail.get("WorkplaceType")
            or row.get("WorkplaceType")
            or detail.get("WorkplaceTypeCode")
            or row.get("WorkplaceTypeCode")
            or ""
        ).strip().lower()
        if workplace in {"on-site", "onsite", "ora_on_site"}:
            item["work_mode"] = "Présentiel"
        elif workplace in {"hybrid", "ora_hybrid"}:
            item["work_mode"] = "Hybride"
        elif workplace in {
            "remote", "fully remote", "work from home",
            "ora_remote", "ora_work_from_home",
        }:
            item["work_mode"] = "Télétravail"

        item["external_id"] = identifier
        if country:
            item["country"] = country
        if local_recruitment:
            item["recruitment_scope"] = "local"
        jobs.append(item)

    return jobs


# International Rescue Committee (IRC) — API publique Workday.
IRC_BASE_URL = "https://theirc.wd1.myworkdayjobs.com"
IRC_API_BASE = IRC_BASE_URL + "/wday/cxs/theirc/External_Careers"
IRC_PUBLIC_BASE = IRC_BASE_URL + "/en-US/External_Careers"

_IRC_IT_TITLE_RE = re.compile(
    r"\b("
    r"information technology|information systems|IT specialist|IT officer|"
    r"ICT|software engineer|software developer|full.?stack|backend developer|"
    r"back.?end developer|frontend developer|front.?end developer|"
    r"web developer|mobile developer|application developer|applications developer|"
    r"systems engineer|systems analyst|data engineer|data analyst|"
    r"database administrator|database engineer|cybersecurity|cyber security|"
    r"network engineer|cloud engineer|DevOps|developer|programmer|"
    r"digital technology|technology specialist|technology officer|"
    r"business intelligence|information security|IT support|"
    r"digital solutions|software|développeur|développeuse|"
    r"ingénieur logiciel|informatique|cybersécurité|données"
    r")\b",
    re.IGNORECASE,
)


def _irc_is_relevant(title):
    return bool(_IRC_IT_TITLE_RE.search(str(title or "")))


def _irc_parse_deadline(description):
    """Retourne une date uniquement si une échéance explicite est reconnue."""
    from datetime import date

    body = BeautifulSoup(str(description or ""), "html.parser").get_text(" ", strip=True)
    match = re.search(
        r"(?:application\s+)?(?:closing|close|deadline|apply\s+by|date\s+limite)"
        r"(?:\s+date)?\s*[:\-]?\s*"
        r"(\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|"
        r"[A-Za-z]+\s+\d{1,2},?\s+\d{4})",
        body,
        re.IGNORECASE,
    )
    if not match:
        return None

    value = match.group(1).strip()
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


async def collect_irc(client):
    """Collecte les offres IT pertinentes du catalogue public IRC Workday."""
    from datetime import date
    from urllib.parse import urlparse

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "JobCiAddunaAI/0.2 (public job discovery)",
    }
    # Recherche bornée par terme pour réduire la charge et les doublons.
    keywords = (
        "software", "developer", "information technology",
        "ICT", "data", "cybersecurity", "DevOps",
    )
    candidates = {}

    for keyword in keywords:
        offset = 0
        total = None
        for _ in range(5):  # maximum 100 résultats par terme
            try:
                response = await client.post(
                    f"{IRC_API_BASE}/jobs",
                    json={
                        "appliedFacets": {},
                        "limit": 20,
                        "offset": offset,
                        "searchText": keyword,
                    },
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                logger.warning(
                    "IRC Careers : recherche %r indisponible (%s)",
                    keyword, type(exc).__name__,
                )
                break

            postings = payload.get("jobPostings", []) if isinstance(payload, dict) else []
            if not isinstance(postings, list) or not postings:
                break
            try:
                total = int(payload.get("total"))
            except (TypeError, ValueError):
                total = None

            for item in postings:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                path = str(item.get("externalPath") or "").strip()
                if (
                    not title
                    or not _irc_is_relevant(title)
                    or not path.startswith("/job/")
                    or "?" in path
                    or "#" in path
                    or not re.search(r"_JR\d+$", path)
                ):
                    continue
                candidates.setdefault(path, item)

            offset += len(postings)
            if (total is not None and offset >= total) or len(postings) < 20:
                break

    jobs = []
    today = date.today()

    for path, listing in candidates.items():
        try:
            response = await client.get(
                IRC_API_BASE + path,
                headers={
                    "Accept": "application/json",
                    "User-Agent": headers["User-Agent"],
                },
            )
            response.raise_for_status()
            info = response.json()
            if not isinstance(info, dict):
                continue
        except Exception as exc:
            logger.warning(
                "IRC Careers : fiche %s indisponible (%s)",
                path, type(exc).__name__,
            )
            continue

        title = str(info.get("title") or listing.get("title") or "").strip()
        if not _irc_is_relevant(title) or info.get("canApply") is False:
            continue

        description_html = str(info.get("jobDescription") or "")
        deadline = _irc_parse_deadline(description_html)
        if deadline and deadline < today:
            continue

        # Accepter seulement des URL HTTPS du portail officiel IRC.
        external_url = str(info.get("externalUrl") or "").strip()
        parsed = urlparse(external_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "theirc.wd1.myworkdayjobs.com"
            or not parsed.path.startswith("/External_Careers/job/")
            or parsed.query
            or parsed.fragment
        ):
            external_url = IRC_PUBLIC_BASE + path

        req_id = str(info.get("jobReqId") or listing.get("jobReqId") or "").strip()
        if not req_id:
            match = re.search(r"_(JR\d+)$", path)
            req_id = match.group(1) if match else path.rsplit("/", 1)[-1]

        posted = info.get("postedOn") or listing.get("postedOn")
        start_date = info.get("startDate")
        description = clean_description(description_html)
        details = [
            "Source officielle : International Rescue Committee (IRC) Careers.",
            f"Identifiant de réquisition : {req_id}",
            f"Date limite : {deadline.isoformat() if deadline else 'non confirmée ; vérifier la fiche officielle'}",
            f"Publication : {posted or 'date non précisée'}",
            f"Temps de travail : {info.get('timeType') or 'non précisé'}",
            "Vérifier sur la fiche officielle l’éligibilité, les restrictions de nationalité, "
            "le droit au travail, le visa et les conditions de mobilité.",
        ]
        raw = {
            "id": req_id,
            "title": title,
            "company": "International Rescue Committee (IRC)",
            "location": info.get("location") or listing.get("locationsText") or "Non précisé",
            "description": (description or title) + "\n\n" + "\n".join(details),
            "url": external_url,
            "publication_date": start_date,
            "job_type": info.get("timeType") or "Non précisé",
        }
        job = normalize_job(raw, "IRC Careers")
        if job:
            job["external_id"] = req_id
            jobs.append(job)

    logger.info("IRC Careers : %d offres IT retenues parmi %d annonces candidates",
                len(jobs), len(candidates))
    return jobs




# Danish Refugee Council: public HTML job listings and detail pages.
DRC_JOBS_URL = "https://drc.ngo/en/jobs/"
DRC_PUBLIC_BASE = "https://drc.ngo"

_DRC_IT_TITLE_RE = re.compile(
    r"\b(software|developer|développeur|développeuse|"
    r"full[\s-]?stack|front[\s-]?end|front[\s-]?end|back[\s-]?end|"
    r"\bit\b|ict|information technology|information management|"
    r"data engineer|data analyst|data scientist|data manager|"
    r"database|cyber|digital|information systems|systems administrator|"
    r"system administrator|network engineer|cloud|devops|"
    r"programmer|programming|web developer|"
    r"gestionnaire de données|systèmes d'information|"
    r"ingénieur informatique|ingénieur logiciel|"
    r"développeur web|administrateur systèmes)\b",
    re.IGNORECASE,
)


def _drc_is_relevant(title):
    return bool(_DRC_IT_TITLE_RE.search(str(title or "")))


def _drc_parse_date(value):
    """Return an explicit date found in ISO or English DRC date formats."""
    from datetime import date

    text = str(value or "")
    match = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None

    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    match = re.search(
        r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(20\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    month = months.get(match.group(2)[:3].lower())
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _drc_labeled_date(text, label_pattern):
    match = re.search(
        label_pattern + r"\s*:?\s*([^\n|]{1,65})",
        str(text or ""),
        re.IGNORECASE,
    )
    return _drc_parse_date(match.group(1)) if match else None


async def collect_drc(client):
    """Collect relevant IT vacancies from the public DRC careers website."""
    from datetime import date
    from urllib.parse import parse_qs, urljoin, urlparse

    headers = {
        "User-Agent": "JobCiAddunaAI/0.2 (public job discovery)",
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        response = await client.get(DRC_JOBS_URL, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as exc:
        logger.warning("DRC Careers : liste indisponible (%s)", type(exc).__name__)
        return []

    # The public listing currently renders its entries as article.jobList__item.
    candidates = {}
    for article in soup.select("article.jobList__item"):
        link = article.select_one("a.casper[href]")
        if not link:
            continue

        parsed = urlparse(urljoin(DRC_PUBLIC_BASE, link.get("href", "")))
        if (
            parsed.scheme != "https"
            or parsed.hostname != "drc.ngo"
            or parsed.path.rstrip("/") != "/jobs/job"
            or parsed.fragment
        ):
            continue

        job_id = parse_qs(parsed.query).get("id", [""])[0]
        if not job_id.isdigit():
            continue

        heading = article.find(["h1", "h2", "h3", "h4"])
        title = (
            heading.get_text(" ", strip=True) if heading else ""
        ) or link.get("aria-label", "") or link.get("title", "")
        if not title:
            continue
        title = clean_description(title).strip()
        if not _drc_is_relevant(title):
            continue

        candidates.setdefault(job_id, (title, parsed.geturl(), article.get_text(" ", strip=True)))

    jobs = []
    today = date.today()

    for job_id, (listing_title, detail_url, listing_text) in candidates.items():
        try:
            response = await client.get(detail_url, headers=headers)
            response.raise_for_status()
            doc = BeautifulSoup(response.text, "html.parser")
        except Exception as exc:
            logger.warning(
                "DRC Careers : fiche %s indisponible (%s)",
                job_id, type(exc).__name__,
            )
            continue

        title_tag = doc.find("h1")
        og_title = doc.find("meta", property="og:title")
        title = (
            title_tag.get_text(" ", strip=True) if title_tag else ""
        ) or (og_title.get("content", "") if og_title else "") or listing_title
        title = clean_description(title).strip()
        if not _drc_is_relevant(title):
            continue

        main_content = doc.find("main") or doc.find(id="main") or doc.body or doc
        detail_text = main_content.get_text(" ", strip=True)
        combined_text = listing_text + " " + detail_text

        deadline = (
            _drc_labeled_date(detail_text, r"(?:Application\s+)?Deadline|Closing\s+date")
            or _drc_labeled_date(listing_text, r"Deadline")
        )
        if deadline and deadline < today:
            continue

        published = (
            _drc_labeled_date(listing_text, r"Published")
            or _drc_labeled_date(detail_text, r"Published")
        )

        country = ""
        workplace = ""
        location_match = re.search(
            r"\bCountry\s+(.+?)\s+Workplace\s+(.+?)\s+Contract\b",
            combined_text,
            re.IGNORECASE,
        )
        if location_match:
            country = clean_description(location_match.group(1)).strip()
            workplace = clean_description(location_match.group(2)).strip()
        location = ", ".join(part for part in (workplace, country) if part)
        if not location:
            location = "Non précisé"

        contract_match = re.search(
            r"\bContract\s+(.+?)\s+Published\b",
            detail_text,
            re.IGNORECASE,
        )
        contract = clean_description(contract_match.group(1)).strip() if contract_match else "Non précisé"

        apply_url = ""
        for anchor in doc.find_all("a", href=True):
            candidate_url = urlparse(urljoin(detail_url, anchor["href"]))
            if (
                candidate_url.scheme == "https"
                and candidate_url.hostname == "candidate.hr-manager.net"
                and candidate_url.path.rstrip("/") == "/ApplicationInit.aspx"
            ):
                apply_url = candidate_url.geturl()
                break

        description = clean_description(str(main_content))
        extra = [
            "Source officielle : Danish Refugee Council (DRC).",
            f"Identifiant de l'offre : {job_id}",
            f"Date limite : {deadline.isoformat() if deadline else 'non confirmée ; vérifier la fiche officielle'}",
            f"Pays : {country or 'non précisé'}",
            f"Lieu : {workplace or 'non précisé'}",
            f"Date de publication : {published.isoformat() if published else 'non précisée'}",
            f"Lien de candidature : {apply_url or 'non détecté ; consulter la fiche officielle'}",
            "Vérifier l'éligibilité, le droit au travail, le visa et la relocalisation sur l'annonce.",
        ]

        raw = {
            "id": job_id,
            "title": title,
            "company": "Danish Refugee Council (DRC)",
            "location": location,
            "description": (description or title) + "\n\n" + "\n".join(extra),
            "url": detail_url,
            "publication_date": published.isoformat() if published else None,
            "job_type": contract,
        }
        job = normalize_job(raw, "DRC Careers")
        if job:
            job["external_id"] = job_id
            jobs.append(job)

    logger.info(
        "DRC Careers : %d offres IT retenues parmi %d annonces candidates",
        len(jobs), len(candidates),
    )
    return jobs



HI_API_URL = "https://apply.workable.com/api/v1/widget/accounts/hi-jobs?details=true"
HI_PUBLIC_URL = "https://apply.workable.com/hi-jobs/"


def _hi_is_relevant(title, function="", department=""):
    """Retient les fonctions IT identifiables, sans fouiller les descriptions génériques."""
    import re

    title = str(title or "").strip()
    context = " ".join(str(x or "") for x in (function, department))
    title_pattern = (
        r"\b(?:"
        r"software|full[\s-]?stack|front[\s-]?end|back[\s-]?end|"
        r"web developer|developer|programmer|programming|"
        r"information technology|IT specialist|ICT specialist|"
        r"systems? (?:analyst|engineer|administrator)|"
        r"database|network(?:ing)?|cyber[\s-]?security|DevOps|"
        r"cloud engineer|data engineer|data analyst|"
        r"application (?:support|developer|administrator|engineer)|"
        r"technical support|IT support|IT manager|"
        r"information systems|digital (?:solutions|technology|systems)|"
        r"computer science"
        r")\b"
    )
    context_pattern = (
        r"\b(?:information technology|information systems|"
        r"IT department|ICT department|software engineering|"
        r"digital technology|cybersecurity|DevOps)\b"
    )
    return bool(
        re.search(title_pattern, title, re.IGNORECASE)
        or re.search(context_pattern, context, re.IGNORECASE)
    )



ACF_BASE_URL = "https://recrutement.actioncontrelafaim.org"
ACF_LISTING_URL = ACF_BASE_URL + "/en/our-offers/"


def _acf_is_relevant(title):
    """Retient les intitulés explicitement liés aux métiers informatiques."""
    pattern = (
        r"\b(?:"
        r"software (?:engineer|developer|architect|programmer)|"
        r"full[\s-]?stack|front[\s-]?end|back[\s-]?end|"
        r"(?:web|mobile|application) developer|"
        r"developer|programmer|software engineer|"
        r"information technology|information systems (?:manager|analyst|engineer)|"
        r"\bIT (?:specialist|manager|officer|engineer|analyst|administrator|support)\b|"
        r"\bICT (?:specialist|manager|officer|engineer|analyst)\b|"
        r"systems? (?:engineer|administrator|analyst)|"
        r"database (?:administrator|engineer|developer)|"
        r"network (?:engineer|administrator)|"
        r"cyber[\s-]?security|DevOps|cloud engineer|"
        r"data (?:engineer|analyst|scientist)|"
        r"développeur(?:euse)?(?: logiciel| web| mobile)?|"
        r"ingénieur(?:e)? (?:logiciel|informatique|systèmes?)|"
        r"administrateur(?:rice)? systèmes?|"
        r"analyste informatique|"
        r"responsable informatique|"
        r"technicien(?:ne)? informatique|"
        r"sécurité informatique|"
        r"ingénieur données"
        r")\b"
    )
    return bool(re.search(pattern, str(title or ""), re.IGNORECASE))


def _acf_parse_date(text):
    """Parse uniquement les dates explicites, sans déduire d'échéance."""
    from datetime import date

    value = str(text or "")
    match = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", value)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None

    match = re.search(
        r"\b(\d{1,2})[ /.-]+(\d{1,2})[ /.-]+(20\d{2})\b", value
    )
    if match:
        try:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            return None

    months = {
        "jan": 1, "janvier": 1, "feb": 2, "février": 2, "fevrier": 2,
        "mar": 3, "mars": 3, "apr": 4, "avril": 4, "may": 5, "mai": 5,
        "jun": 6, "juin": 6, "jul": 7, "juillet": 7, "aug": 8, "août": 8,
        "aout": 8, "sep": 9, "septembre": 9, "oct": 10, "octobre": 10,
        "nov": 11, "novembre": 11, "dec": 12, "décembre": 12, "decembre": 12,
    }
    match = re.search(
        r"\b(\d{1,2})\s+([A-Za-zÀ-ÿ]{3,12})\.?,?\s+(20\d{2})\b",
        value, re.IGNORECASE,
    )
    if match:
        month_name = match.group(2).lower()
        month = months.get(month_name) or months.get(month_name[:3])
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                pass
    return None


def _acf_labeled_date(text, labels):
    match = re.search(
        r"(?:%s)\s*:?\s*([^\n]{1,100})" % labels,
        str(text or ""), re.IGNORECASE,
    )
    return _acf_parse_date(match.group(1)) if match else None


async def collect_acf(client):
    """Collecte les offres IT depuis le portail public officiel ACF."""
    from datetime import date
    from urllib.parse import urljoin, urlparse

    headers = {
        "User-Agent": "JobCiAddunaAI/0.2 (public job discovery)",
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        response = await client.get(ACF_LISTING_URL, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as exc:
        logger.warning("ACF Careers : liste indisponible (%s)", type(exc).__name__)
        return []

    candidates = {}
    for anchor in soup.select('a[href]'):
        href = anchor.get("href", "").strip()
        parsed = urlparse(urljoin(ACF_BASE_URL, href))
        if (
            parsed.scheme != "https"
            or parsed.hostname != "recrutement.actioncontrelafaim.org"
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(
                r"/(?:en/our-offers|nos-offres)/20\d{2}-\d+/?",
                parsed.path,
            )
        ):
            continue

        title_node = anchor.select_one(".crd__title")
        title = (
            title_node.get_text(" ", strip=True) if title_node else ""
        ) or anchor.get_text(" ", strip=True)
        title = clean_description(title).strip()
        if title:
            candidates.setdefault(parsed.geturl().rstrip("/"), title)

    jobs = []
    today = date.today()

    for detail_url, listing_title in candidates.items():
        if not _acf_is_relevant(listing_title):
            continue
        try:
            response = await client.get(detail_url, headers=headers)
            response.raise_for_status()
            doc = BeautifulSoup(response.text, "html.parser")
        except Exception as exc:
            logger.warning(
                "ACF Careers : fiche indisponible (%s)", type(exc).__name__
            )
            continue

        heading = doc.find("h1")
        title = clean_description(
            heading.get_text(" ", strip=True) if heading else listing_title
        ).strip()
        if not _acf_is_relevant(title):
            continue

        content = doc.find("main") or doc.body or doc
        detail_text = content.get_text("\n", strip=True)
        deadline = _acf_labeled_date(
            detail_text,
            r"(?:application\s+)?deadline|closing date|date limite|"
            r"date de clôture|postuler avant|apply before",
        )
        if deadline and deadline < today:
            continue

        published = _acf_labeled_date(
            detail_text,
            r"published|publication date|date de publication|mis(?:e)? en ligne",
        )

        location = "Non précisé"
        for selector in (".crd__content", "[class*='location']", "[class*='place']"):
            node = doc.select_one(selector)
            if node:
                candidate_location = clean_description(
                    node.get_text(" ", strip=True)
                )
                if candidate_location and len(candidate_location) <= 300:
                    location = candidate_location
                    break

        apply_url = ""
        for anchor in doc.find_all("a", href=True):
            parsed = urlparse(urljoin(detail_url, anchor["href"]))
            if (
                parsed.scheme == "https"
                and parsed.hostname == "actioncontrelafaim-career.talent-soft.com"
            ):
                apply_url = parsed.geturl()
                break

        description = clean_description(str(content))
        metadata = [
            "Source officielle : Action contre la Faim (ACF).",
            f"Date limite : {deadline.isoformat() if deadline else 'non confirmée ; vérifier la fiche officielle'}",
            f"Date de publication : {published.isoformat() if published else 'non précisée'}",
            f"Lien de candidature : {apply_url or 'non détecté ; consulter la fiche officielle'}",
            "Vérifier l'éligibilité, le droit au travail, le visa et la relocalisation sur l'annonce.",
        ]
        raw = {
            "id": detail_url.rstrip("/").rsplit("/", 1)[-1],
            "title": title,
            "company": "Action contre la Faim (ACF)",
            "location": location,
            "description": (description or title) + "\n\n" + "\n".join(metadata),
            "url": detail_url,
            "publication_date": published.isoformat() if published else None,
            "job_type": "Non précisé",
        }
        job = normalize_job(raw, "Action contre la Faim (ACF)")
        if job:
            jobs.append(job)

    return jobs


async def collect_hi(client):
    """Collecte les offres IT pertinentes depuis le tableau public Workable de HI."""
    from urllib.parse import urlparse

    headers = {
        "User-Agent": "JobCiAddunaAI/0.2 (public job discovery)",
        "Accept": "application/json",
    }

    try:
        response = await client.get(HI_API_URL, headers=headers)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning("Handicap International : API indisponible (%s)", type(exc).__name__)
        return []

    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        entries = payload.get("jobs")
        if not isinstance(entries, list):
            entries = payload.get("results", [])
    else:
        entries = []

    if not isinstance(entries, list):
        return []

    jobs = []
    seen = set()

    for item in entries:
        if not isinstance(item, dict):
            continue

        title = clean_description(str(item.get("title") or "")).strip()
        if not title or not _hi_is_relevant(
            title, item.get("function"), item.get("department")
        ):
            continue

        identifier = str(
            item.get("shortcode") or item.get("code") or item.get("id") or ""
        ).strip()
        job_url = str(item.get("url") or item.get("shortlink") or "").strip()
        parsed_job_url = urlparse(job_url)

        # N'accepter que les liens publics officiels Workable.
        if not (
            parsed_job_url.scheme == "https"
            and parsed_job_url.hostname == "apply.workable.com"
            and parsed_job_url.path.startswith("/hi-jobs/")
        ):
            shortcode = str(item.get("shortcode") or "").strip()
            if shortcode:
                job_url = f"https://apply.workable.com/hi-jobs/j/{shortcode}/"
            else:
                continue

        key = identifier or job_url
        if key in seen:
            continue
        seen.add(key)

        city = str(item.get("city") or "").strip()
        country = str(item.get("country") or "").strip()
        locations = item.get("locations")
        if isinstance(locations, list) and not (city or country):
            location_names = [
                str(loc.get("location") or loc.get("city") or "").strip()
                for loc in locations if isinstance(loc, dict)
            ]
            city = ", ".join(x for x in location_names if x)
        location = ", ".join(x for x in (city, country) if x) or "Non précisé"

        apply_url = str(item.get("application_url") or "").strip()
        parsed_apply = urlparse(apply_url)
        if not (
            parsed_apply.scheme == "https"
            and parsed_apply.hostname == "apply.workable.com"
            and parsed_apply.path.startswith("/j/")
        ):
            apply_url = ""

        published = str(item.get("published_on") or item.get("created_at") or "").strip()
        published = published[:10] if published else ""
        if published and not __import__("re").fullmatch(r"\d{4}-\d{2}-\d{2}", published):
            published = ""

        description = clean_description(str(item.get("description") or "")).strip()
        extra = [
            "Source officielle : Handicap International (HI).",
            f"Identifiant de l'offre : {identifier or 'non fourni'}",
            f"Lien de candidature : {apply_url or 'consulter la fiche officielle'}",
            "Vérifier les critères d'éligibilité, le droit au travail, le visa et la relocalisation sur la fiche officielle.",
        ]
        raw = {
            "id": identifier or job_url,
            "title": title,
            "company": "Handicap International (HI)",
            "location": location,
            "description": (description or title) + "\n\n" + "\n".join(extra),
            "url": job_url,
            "publication_date": published or None,
            "job_type": str(item.get("employment_type") or "Non précisé"),
        }
        if item.get("telecommuting"):
            raw["work_mode"] = "Remote"

        job = normalize_job(raw, "Handicap International (HI)")
        if job:
            job["external_id"] = identifier or job_url
            jobs.append(job)

    logger.info(
        "Handicap International : %d offres IT retenues parmi %d annonces publiques",
        len(jobs), len(entries),
    )
    return jobs


async def collect_jobicy(client):
    """Jobicy public remote-jobs API; only recent remote listings are exposed by its public feed."""
    data = await fetch_json(client, 'https://jobicy.com/api/v2/remote-jobs', {'count': 100, 'industry': 'engineering'})
    gathered = []
    for raw in data.get('jobs', []) if isinstance(data, dict) else []:
        raw = {**raw, 'title': raw.get('jobTitle') or raw.get('title') or raw.get('position'),
               'company': raw.get('companyName') or raw.get('company') or raw.get('company_name'),
               'url': raw.get('url') or raw.get('jobUrl'),
               'location': raw.get('jobGeo') or raw.get('location') or raw.get('geo'),
               'description': raw.get('jobDescription') or raw.get('description'),
               'publication_date': raw.get('pubDate') or raw.get('published_at'),
               'job_type': raw.get('jobType') or raw.get('job_type')}
        item = normalize_job(raw, 'Jobicy API')
        if item: gathered.append(item)
    return gathered

async def collect_remote_jobs_api(client):
    """Optional connector to a self-hosted remote-jobs-api service; never guesses a local URL."""
    if not REMOTE_JOBS_API_URL:
        return []
    data = await fetch_json(client, REMOTE_JOBS_API_URL)
    rows = data.get('jobs', data.get('data', [])) if isinstance(data, dict) else data
    gathered = []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, dict):
            continue
        raw = {**raw, 'url': raw.get('url') or raw.get('applyUrl') or raw.get('job_url'),
               'company': raw.get('company') or raw.get('companyName'),
               'location': raw.get('location') or raw.get('remoteRegion'),
               'description': raw.get('description') or raw.get('descriptionText'),
               'publication_date': raw.get('publishedAt') or raw.get('published') or raw.get('date_posted')}
        item = normalize_job(raw, 'Remote Jobs API (agrégateur configuré)')
        if item: gathered.append(item)
    return gathered


def _normalize_optional_record(raw, source):
    """Map optional collector records to the common Job Ci Adduna AI schema."""
    if hasattr(raw, 'to_compact_dict'):
        raw = raw.to_compact_dict()
    elif hasattr(raw, '__dict__') and not isinstance(raw, dict):
        raw = vars(raw)

    if not isinstance(raw, dict):
        return None

    mapped = {
        **raw,
        'title': raw.get('title') or raw.get('position'),
        'url': (
            raw.get('url')
            or raw.get('job_url')
            or raw.get('jobUrl')
            or raw.get('apply_url')
            or raw.get('absolute_url')
        ),
        'company': (
            raw.get('company')
            or raw.get('company_name')
            or raw.get('companyName')
            or raw.get('organization')
        ),
        'location': (
            raw.get('location')
            or raw.get('city')
            or raw.get('country')
            or raw.get('candidate_required_location')
            or ''
        ),
        'description': (
            raw.get('description')
            or raw.get('description_text')
            or raw.get('job_description')
            or ''
        ),
        'publication_date': (
            raw.get('publication_date')
            or raw.get('date_posted')
            or raw.get('datePosted')
            or raw.get('published_at')
            or raw.get('created_at')
        ),
        'job_type': (
            raw.get('job_type')
            or raw.get('employment_type')
            or raw.get('contract_type')
        ),
        'remote': (
            raw.get('remote')
            or str(raw.get('work_mode') or '').strip().lower()
            in {'remote', 'télétravail', 'à distance'}
        ),
    }

    item = normalize_job(mapped, source)
    if item and mapped.get('remote'):
        item['work_mode'] = 'Télétravail'

    return item


async def collect_jobspy():
    """Optional python-jobspy connector. Disabled by default and limited to configured boards."""
    if not JOBSPY_ENABLED:
        return []
    def _run():
        from jobspy import scrape_jobs
        sites = [x.strip() for x in os.getenv('JOBSPY_SITES', 'indeed').split(',') if x.strip()]
        terms = [x.strip() for x in os.getenv('JOBSPY_SEARCH_TERMS', 'full stack developer,mobile developer,Java Spring Boot').split(',') if x.strip()]
        location = os.getenv('JOBSPY_LOCATION', 'Worldwide')
        hours_old = max(1, int(os.getenv('JOBSPY_HOURS_OLD', '720')))
        results = []
        for term in terms:
            country_indeed = os.getenv('JOBSPY_COUNTRY_INDEED', '').strip()
            kwargs = {
                'site_name': sites,
                'search_term': term,
                'location': location,
                'results_wanted': max(1, int(os.getenv('JOBSPY_RESULTS_PER_SOURCE', '20'))),
                'hours_old': hours_old,
                'verbose': 0,
            }
            if country_indeed and 'indeed' in sites:
                kwargs['country_indeed'] = country_indeed
            frame = scrape_jobs(**kwargs)
            if frame is not None:
                for raw in frame.fillna('').to_dict(orient='records'):
                    raw['url'] = raw.get('job_url') or raw.get('url')
                    raw['company'] = raw.get('company') or raw.get('company_name')
                    raw['location'] = ', '.join(str(raw.get(k, '')).strip() for k in ('city','state','country') if str(raw.get(k, '')).strip()) or raw.get('location','')
                    raw['publication_date'] = raw.get('date_posted')
                    raw['description'] = raw.get('description')
                    raw['job_type'] = raw.get('job_type')
                    results.append(raw)
        return results
    raw_jobs = await asyncio.to_thread(_run)
    gathered = []
    for raw in raw_jobs:
        item = _normalize_optional_record(raw, f"JobSpy · {raw.get('site') or 'job board'}")
        if item: gathered.append(item)
    return gathered

async def collect_hirehunt():
    """Optional hirehunt connector; the library and source policies are user-controlled."""
    if not HIREHUNT_ENABLED:
        return []
    def _run():
        from hirehunt import scrape_jobs
        terms = [x.strip() for x in os.getenv('HIREHUNT_SEARCH_TERMS', 'full stack developer,mobile developer,Java Spring Boot').split(',') if x.strip()]
        sources = [x.strip() for x in os.getenv('HIREHUNT_SOURCES', 'google_careers,amazon,apple,microsoft').split(',') if x.strip()]
        location = os.getenv('HIREHUNT_LOCATION', 'Worldwide')
        found = []
        for term in terms:
            result = scrape_jobs(search_term=term, sources=sources, location=location,
                                results_wanted=max(1, int(os.getenv('HIREHUNT_RESULTS_PER_SOURCE', '20'))),
                                request_policy={'retries': 3, 'timeout': 20, 'backoff_base': 2, 'min_delay': 0.5, 'max_delay': 2.0})
            found.extend(list(getattr(result, 'jobs', result if isinstance(result, list) else [])))
        return found
    raw_jobs = await asyncio.to_thread(_run)
    gathered = []
    for raw in raw_jobs:
        item = _normalize_optional_record(raw, f"Hirehunt · {getattr(raw, 'source', 'source configurée')}")
        if item: gathered.append(item)
    return gathered

async def collect_crawl4ai(client=None):
    """Optional crawler for explicitly allowlisted public career URLs; extracts JobPosting JSON-LD."""
    if not CRAWL4AI_ENABLED:
        return []
    urls = [x.strip() for x in os.getenv('CRAWL4AI_SEED_URLS', '').split(',') if x.strip()]
    if not urls:
        return []
    def _run():
        import json as _json
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
        async def _crawl():
            found = []
            async with AsyncWebCrawler() as crawler:
                for url in urls:
                    # Only user-configured public URLs are visited; no login/CAPTCHA bypass.
                    result = await crawler.arun(url=url, config=CrawlerRunConfig(page_timeout=20000))
                    html = getattr(result, 'html', '') or ''
                    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I|re.S):
                        try: payload = _json.loads(block)
                        except Exception: continue
                        objects = payload if isinstance(payload, list) else payload.get('@graph', [payload]) if isinstance(payload, dict) else []
                        for obj in objects:
                            typ = obj.get('@type', []) if isinstance(obj, dict) else []
                            if isinstance(typ, str): typ = [typ]
                            if 'JobPosting' not in typ: continue
                            org = obj.get('hiringOrganization') or {}
                            loc = obj.get('jobLocation') or {}
                            if isinstance(loc, list): loc = loc[0] if loc else {}
                            addr = loc.get('address', {}) if isinstance(loc, dict) else {}
                            location = ', '.join(str(addr.get(k)) for k in ('addressLocality','addressRegion','addressCountry') if addr.get(k))
                            found.append({'title':obj.get('title'), 'company':org.get('name') or 'Employeur non précisé',
                                          'url':obj.get('url') or url, 'location':location,
                                          'description':obj.get('description',''), 'publication_date':obj.get('datePosted'),
                                          'job_type':obj.get('employmentType')})
            return found
        return asyncio.run(_crawl())
    raw_jobs = await asyncio.to_thread(_run)
    return [item for raw in raw_jobs if (item := _normalize_optional_record(raw, 'Crawl4AI · JSON-LD'))]

async def collect_scrapegraphai():
    """ScrapeGraphAI managed cloud API for explicitly configured public job pages."""
    if not SCRAPEGRAPHAI_ENABLED:
        return []
    urls = [x.strip() for x in os.getenv('SCRAPEGRAPHAI_URLS', '').split(',') if x.strip()]
    if not urls:
        return []
    if not os.getenv('SGAI_API_KEY', '').strip():
        raise RuntimeError('ScrapeGraphAI activé mais SGAI_API_KEY absent; ajoutez la clé dans backend/.env')

    def _run():
        from scrapegraph_py import ScrapeGraphAI
        import json as _json
        sgai = ScrapeGraphAI()  # Reads SGAI_API_KEY from the environment.
        # Certaines pages demandent plus de 120 secondes.
        sgai._http.timeout = 240
        found = []
        prompt = (
            'Extract only real software job vacancies visible on this page. Return JSON with a "jobs" array. '
            'Each item must have title, company, location, url, description, publication_date, job_type, '
            'and work_mode. Include only full-stack, Java/Spring, Angular, Flutter or mobile developer roles. '
            'Never invent missing values; use empty strings. Use the original job/application URL when available.'
        )
        schema = {
            'type': 'object', 'properties': {'jobs': {'type': 'array', 'items': {
                'type': 'object', 'properties': {
                    'title': {'type': 'string'}, 'company': {'type': 'string'},
                    'location': {'type': 'string'}, 'url': {'type': 'string'},
                    'description': {'type': 'string'}, 'publication_date': {'type': 'string'},
                    'job_type': {'type': 'string'}, 'work_mode': {'type': 'string'}
                }, 'required': ['title', 'company', 'url']
            }}}}
        for url in urls:
            response = sgai.extract(prompt=prompt, url=url, schema=schema)
            if getattr(response, 'status', None) != 'success':
                logger.warning(
                    'ScrapeGraphAI extraction failed for %s: %s (elapsed_ms=%s)',
                    url,
                    getattr(response, 'error', 'unknown error'),
                    getattr(response, 'elapsed_ms', 'unknown'),
                )
                continue

            # ExtractResponse exposes the structured payload as json_data.
            data = getattr(response, 'data', None)
            if data is not None and hasattr(data, 'json_data'):
                data = data.json_data
            elif hasattr(data, 'model_dump'):
                data = data.model_dump()

            if isinstance(data, str):
                try:
                    data = _json.loads(data)
                except (ValueError, TypeError):
                    data = {}

            if isinstance(data, dict):
                rows = data.get('jobs', [])
                # Accommodate wrapped JSON payloads returned by SDK versions.
                if not rows:
                    for key in ('json_data', 'json', 'result', 'data'):
                        nested = data.get(key)
                        if isinstance(nested, dict) and isinstance(nested.get('jobs'), list):
                            rows = nested['jobs']
                            break
            elif isinstance(data, list):
                rows = data
            else:
                rows = []

            if not isinstance(rows, list):
                logger.warning('ScrapeGraphAI: format jobs invalide pour %s', url)
                continue

            logger.info(
                'ScrapeGraphAI: %s offres brutes extraites depuis %s',
                len(rows), url
            )
            for raw in rows:
                if isinstance(raw, dict):
                    raw.setdefault('url', url)
                    found.append(raw)
        return found

    raw_jobs = await asyncio.to_thread(_run)
    return [item for raw in raw_jobs if (item := _normalize_optional_record(raw, 'ScrapeGraphAI Cloud'))]


async def collect_mesri_jobs(client: httpx.AsyncClient):
    """Collecte prudente des annonces informatiques du portail officiel MESRI."""
    from urllib.parse import urljoin, urlparse
    from datetime import date
    import io
    import unicodedata

    base = "https://espaceuniversitaire.mesrisenegal.sn"
    listing_paths = (
        "/public/communiques",
        "/public/vie-estudiantine/appels-a-candidatures",
        "/public/actualites",
    )
    allowed_article_host = "espaceuniversitaire.mesrisenegal.sn"
    allowed_pdf_hosts = {"www.unchk.sn", "unchk.sn"}
    role_pattern = re.compile(
        r"\b(d[eé]veloppeur|d[eé]veloppeuse|software developer|"
        r"full[\s-]?stack|ing[eé]nieur.{0,25}(logiciel|informatique|syst[eè]me|r[eé]seau)|"
        r"administrateur.{0,25}(syst[eè]me|r[eé]seau|informatique|num[eé]rique)|"
        r"technicien.{0,25}informatique|webmaster|programmeur|"
        r"cybers[eé]curit[eé]|cybersecurity|data analyst|analyste.{0,20}donn[eé]es|"
        r"chef.{0,20}projet.{0,20}informatique|responsable.{0,20}informatique|"
        r"informaticien|informaticienne|it officer|system administrator)",
        re.IGNORECASE,
    )

    def plain(value):
        value = unicodedata.normalize("NFKD", str(value or ""))
        return "".join(c for c in value if not unicodedata.combining(c)).lower()

    def expired_deadline(text):
        # Une date n'est considérée comme échéance que si elle suit une mention explicite.
        months = {
            "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
            "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
            "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
        }
        normalized = plain(text)
        for context in re.finditer(
            r"(?:date limite|au plus tard|jusqu au|avant le|deadline|cloture des candidatures)"
            r"[^.\n]{0,140}",
            normalized,
        ):
            snippet = context.group(0)
            match = re.search(
                r"\b(\d{1,2})\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|"
                r"septembre|octobre|novembre|decembre)\s+(\d{4})\b",
                snippet,
            )
            if not match:
                match = re.search('\\b(\\d{1,2})[/-](\\d{1,2})[/-](\\d{4})\\b', snippet)
                if match:
                    try:
                        deadline = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
                        return deadline < date.today()
                    except ValueError:
                        continue
            if match:
                try:
                    deadline = date(int(match.group(3)), months[match.group(2)], int(match.group(1)))
                    if deadline < date.today():
                        return True
                except (ValueError, KeyError):
                    continue
        return False

    async def get_page(url, limit):
        try:
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
            ):
                return None
            if parsed.hostname not in ({allowed_article_host} | allowed_pdf_hosts):
                return None
        except (TypeError, ValueError):
            return None

        try:
            response = await client.get(url, follow_redirects=False, timeout=20)
            if response.is_redirect or response.status_code != 200:
                return None
            if len(response.content) > limit:
                return None
            return response
        except Exception:
            return None

    article_urls = {}
    for path in listing_paths:
        response = await get_page(urljoin(base, path), 2_000_000)
        if not response:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.select("a[href]"):
            href = urljoin(str(response.url), link.get("href", ""))
            parsed = urlparse(href)
            if (
                parsed.scheme == "https"
                and parsed.hostname == allowed_article_host
                and parsed.path.startswith("/public/actualites/")
            ):
                article_urls[href.split("#")[0]] = True

    found = []
    seen = set()
    for article_url in list(article_urls)[:40]:
        response = await get_page(article_url, 2_000_000)
        if not response:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        heading = soup.find("h1") or soup.find("h2")
        title = heading.get_text(" ", strip=True) if heading else ""
        body = soup.get_text(" ", strip=True)
        if not title or not role_pattern.search(plain(title)):
            continue
        if expired_deadline(body):
            continue
        key = article_url.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        record = normalize_job({
            "title": title,
            "company": "MESRI Sénégal / établissement universitaire",
            "location": "Sénégal",
            "description": body[:12000],
            "url": article_url,
            "publication_date": None,
        }, "MESRI Sénégal")
        if record:
            found.append(record)

    # PDF : lire uniquement les documents liés depuis une page officielle,
    # avec hôte autorisé, taille limitée et échéance explicitement reconnue.
    pdf_urls = set()
    for article_url in list(article_urls)[:40]:
        response = await get_page(article_url, 2_000_000)
        if not response:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.select("a[href]"):
            href = urljoin(str(response.url), link.get("href", ""))
            try:
                parsed = urlparse(href)
                parsed_port = parsed.port
            except (TypeError, ValueError):
                continue

            if (
                parsed.scheme == "https"
                and parsed.hostname in allowed_pdf_hosts
                and parsed.path.lower().endswith(".pdf")
                and not parsed.username and not parsed.password
                and parsed_port in (None, 443)
            ):
                pdf_urls.add(href.split("#")[0])

    for pdf_url in list(pdf_urls)[:10]:
        response = await get_page(pdf_url, 12_000_000)
        if not response or not response.content.startswith(b"%PDF-"):
            continue
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(response.content))
            if len(reader.pages) > 100:
                continue
            pdf_text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            continue
        if not pdf_text.strip():
            continue

        # Regrouper chaque intitule reconnu avec les lignes suivantes.
        offer_blocks = []
        current_block = []
        for line in pdf_text.splitlines():
            candidate = re.sub(r"\s+", " ", line).strip(" \t-•:;")
            role_match = role_pattern.search(plain(candidate))
            is_title = (
                8 <= len(candidate) <= 160
                and role_match is not None
                and role_match.start() <= 20
                and not re.match(
                    r"^(missions?|profil|description|responsabilit[eé]s|"
                    r"comp[eé]tences|conditions|candidature|date limite)\s*:",
                    plain(candidate),
                )
            )
            if is_title:
                if current_block:
                    offer_blocks.append(current_block)
                current_block = [line]
            elif current_block:
                current_block.append(line)

        if current_block:
            offer_blocks.append(current_block)

        for block in offer_blocks:
            title = re.sub(r"\s+", " ", block[0]).strip(" \t-•:;")
            if expired_deadline("\n".join(block)):
                continue
            if plain(title) in seen:
                continue
            seen.add(plain(title))
            record = normalize_job({
                "title": title,
                "company": "MESRI Sénégal / établissement universitaire",
                "location": "Sénégal",
                "description": (
                    "Intitulé extrait d'un PDF officiel lié depuis le portail MESRI. "
                    "Vérifier les conditions et la disponibilité dans le document source."
                ),
                "url": pdf_url + "#poste-" + re.sub(r"[^a-z0-9]+", "-", plain(title)).strip("-")[:60],
                "publication_date": None,
            }, "MESRI Sénégal (PDF)")
            if record:
                # Une même URL PDF peut contenir plusieurs annonces.
                # Une empreinte stable par document et intitulé évite leur fusion.
                stable_key = f"MESRI-PDF:{pdf_url.lower()}:{plain(title)}"
                stable_hash = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()
                record["external_id"] = stable_hash[:32]
                record["content_hash"] = stable_hash
                found.append(record)

    return found


async def run_collection():
    started = utcnow()
    with connect() as db:
        cur = db.execute("INSERT INTO sync_runs(started_at,status) VALUES(?, 'en cours')", (started,)); run_id = cur.lastrowid; db.commit()
    counts = {}; errors = []; collected = []
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            collectors = [
                ('CNRS', lambda: collect_cnrs(client)),
                ('IOM Careers', lambda: collect_iom(client)),
                ('World Bank Group Careers', lambda: collect_world_bank_group(client)),
                ('UNIDO Careers', lambda: collect_unido(client)),
                ('EBRD Careers', lambda: collect_ebrd(client)),
                ('UNDP Careers', lambda: collect_undp(client)),
                ('ITU Careers', lambda: collect_itu(client)),
                ('ICAO Careers', lambda: collect_icao(client)),
                ('WFP Careers', lambda: collect_wfp(client)),
                ('GIZ Careers', lambda: collect_giz(client)),
                ('IsDB Careers', lambda: collect_isdb(client)),
                ('UNFPA Careers', lambda: collect_unfpa(client)),
                ('UN Women Careers', lambda: collect_un_women(client)),
                ('UNICEF Careers', lambda: collect_unicef(client)),
                ('FAO Careers', lambda: collect_fao(client)),
                ('ILO Careers', lambda: collect_ilo(client)),
                ('UNESCO Careers', lambda: collect_unesco(client)),
                ('UNOPS Careers', lambda: collect_unops(client)),
                ('African Union Careers', lambda: collect_african_union(client)),
                ('CEDEAO Careers', lambda: collect_ecowas(client)),
                ('ONU Careers RSS', lambda: collect_un_careers(client)),
                ('Expat-Dakar', lambda: collect_expat_dakar(client)),
                ('Liggey', lambda: collect_liggey(client)),
                ('EmploiSenegal', lambda: collect_emploisenegal(client)),
                ('Emploi Dakar', lambda: collect_emploi_dakar(client)),
                ('MESRI Sénégal', lambda: collect_mesri_jobs(client)),
                ('Senjob', lambda: collect_senjob(client)),
                ('Arbeitnow API', lambda: collect_arbeitnow(client)),
                ('Remotive API', lambda: collect_remotive(client)),
                ('Jobicy API', lambda: collect_jobicy(client)),
                ('SmartRecruiters', lambda: collect_smartrecruiters(client)),
                ('Action contre la Faim (ACF)', lambda: collect_acf(client)),
                ('IRC Careers', lambda: collect_irc(client)),
                ('DRC Careers', lambda: collect_drc(client)),
                ('Handicap International (HI)', lambda: collect_hi(client)),
                ('ICRC Careers', lambda: collect_icrc(client)),
                ('MSF Careers', lambda: collect_msf(client)),
                ('NRC Careers', lambda: collect_nrc(client)),
                ('Remote Jobs API (agrégateur configuré)', lambda: collect_remote_jobs_api(client)),
                ('Greenhouse', lambda: collect_greenhouse(client)),
                ('Lever', lambda: collect_lever(client)),
                ('JobSpy (optionnel)', collect_jobspy),
                ('Hirehunt (optionnel)', collect_hirehunt),
                ('Crawl4AI (URLs configurées)', lambda: collect_crawl4ai(client)),
                ('ScrapeGraphAI (URLs configurées)', collect_scrapegraphai),
            ]
            for name, collector in collectors:
                try:
                    # Optional sources are visible in the run diagnostics even when not configured.
                    enabled = {
                        'Greenhouse': bool(os.getenv('GREENHOUSE_BOARDS', '').strip()),
                        'Lever': bool(os.getenv('LEVER_SITES', '').strip()),
                        'Remote Jobs API (agrégateur configuré)': bool(REMOTE_JOBS_API_URL),
                        'JobSpy (optionnel)': JOBSPY_ENABLED,
                        'Hirehunt (optionnel)': HIREHUNT_ENABLED,
                        'Crawl4AI (URLs configurées)': CRAWL4AI_ENABLED and bool(os.getenv('CRAWL4AI_SEED_URLS', '').strip()),
                        'ScrapeGraphAI (URLs configurées)': SCRAPEGRAPHAI_ENABLED and bool(os.getenv('SCRAPEGRAPHAI_URLS', '').strip()),
                    }.get(name, True)
                    items = await collector() if enabled else []
                    counts[name] = {'received': len(items), 'error': None, 'enabled': enabled}
                    collected.extend(items)
                except Exception as exc:
                    logger.warning('Collecteur %s en échec: %s', name, exc)
                    counts[name] = {'received': 0, 'error': str(exc)[:350], 'enabled': True}
                    errors.append(f'{name}: {str(exc)[:200]}')
        inserted = updated = skipped = 0
        with connect() as db:
            for item in collected:
                skills = ','.join(item['skills'])
                now = utcnow()
                old = db.execute('SELECT id,description,published_at FROM jobs WHERE content_hash=? OR (? IS NOT NULL AND external_id=? AND source=?)',
                                 (item['content_hash'], item['external_id'], item['external_id'], item['source'])).fetchone()
                if old:
                    # Keep manually updated status and notes; enrich the listing with freshest source fields.
                    db.execute('''UPDATE jobs SET title=?,company=?,location=?,country=?,work_mode=?,contract_type=?,description=?,url=?,skills=?,
                        published_at=COALESCE(?,published_at),collected_at=?,source=? WHERE id=?''',
                        (item['title'], item['company'], item['location'], item['country'], item['work_mode'], item['contract_type'], item['description'], item['url'], skills, item['published_at'], now, item['source'], old['id']))
                    updated += 1
                else:
                    try:
                        db.execute('''INSERT INTO jobs(title,company,location,country,work_mode,contract_type,description,url,source,skills,created_at,
                            published_at,collected_at,external_id,content_hash,status,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (item['title'],item['company'],item['location'],item['country'],item['work_mode'],item['contract_type'],item['description'],item['url'],item['source'],skills,now,item['published_at'],now,item['external_id'],item['content_hash'],'À examiner',''))
                        inserted += 1
                    except sqlite3.IntegrityError: skipped += 1
            db.execute('UPDATE sync_runs SET finished_at=?,status=?,inserted=?,updated=?,skipped=?,sources_json=?,error=? WHERE id=?',
                       (utcnow(), 'terminé avec erreurs' if errors else 'terminé', inserted, updated, skipped, json.dumps(counts, ensure_ascii=False), '\n'.join(errors), run_id))
            db.commit()
        return {'run_id':run_id, 'status':'terminé avec erreurs' if errors else 'terminé', 'started_at':started, 'finished_at':utcnow(), 'inserted':inserted, 'updated':updated, 'skipped':skipped, 'sources':counts, 'errors':errors}
    except Exception as exc:
        logger.exception('Erreur de collecte')
        with connect() as db:
            db.execute("UPDATE sync_runs SET finished_at=?,status='échec',error=? WHERE id=?", (utcnow(),str(exc)[:1000],run_id)); db.commit()
        raise

async def wait_until_utc(deadline: datetime):
    """Attend une échéance UTC en revérifiant l'heure au moins chaque minute."""
    while True:
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return
        await asyncio.sleep(min(60.0, remaining))


async def scheduler_loop():
    interval = SYNC_INTERVAL_MINUTES * 60
    next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
    logger.info(
        "Planificateur emplois activé ; prochaine collecte prévue à %s",
        next_run.isoformat()
    )

    while True:
        await wait_until_utc(next_run)
        try:
            logger.info("Démarrage de la collecte automatique des emplois")
            result = await run_collection()
            logger.info(
                "Collecte emplois terminée : %s nouvelles offres, %s mises à jour",
                result["inserted"], result["updated"]
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Collecte automatique des emplois échouée")

        next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
        logger.info("Prochaine collecte emplois prévue à %s", next_run.isoformat())


async def doctoral_scheduler_loop():
    interval = DOCTORAL_SYNC_INTERVAL_HOURS * 3600
    next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
    logger.info(
        "Planificateur doctoral activé ; prochaine synchronisation prévue à %s",
        next_run.isoformat()
    )

    while True:
        await wait_until_utc(next_run)
        try:
            logger.info("Démarrage de la synchronisation automatique des doctorats")
            result = await sync_doctorates()
            logger.info(
                "Collecte doctorale terminée : %s nouvelles offres, "
                "%s doublons, %s erreurs",
                result.get("inserted", 0),
                result.get("duplicates", 0),
                len(result.get("errors", []))
            )
            for error in result.get("errors", []):
                logger.warning("Collecte doctorale : %s", error)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Collecte automatique des doctorats échouée")

        next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
        logger.info(
            "Prochaine synchronisation doctorale prévue à %s",
            next_run.isoformat()
        )

async def recruiter_scheduler_loop():
    interval = RECRUITER_SYNC_INTERVAL_HOURS * 3600
    next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
    logger.info(
        "Planificateur recruteurs activé ; prochaine collecte prévue à %s",
        next_run.isoformat()
    )

    while True:
        await wait_until_utc(next_run)

        # Les collecteurs sont indépendants : une erreur de source ne bloque pas l'autre.
        try:
            logger.info("Démarrage de la collecte Hacker News")
            result = await asyncio.to_thread(
                sync_hackernews_recruiters, limit=30, thread_limit=3
            )
            logger.info(
                "Hacker News terminé : %s nouvelles entrées, %s mises à jour",
                result.get("inserted", 0), result.get("updated", 0)
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Collecte Hacker News échouée")

        try:
            logger.info("Démarrage de la collecte des sites officiels de recruteurs")
            result = await asyncio.to_thread(sync_official_recruiters)
            logger.info(
                "Sites officiels terminés : %s offres vues, %s nouvelles, %s mises à jour",
                result.get("offers_seen", 0),
                result.get("inserted", 0),
                result.get("updated", 0)
            )
            errors = result.get("errors", [])
            if errors:
                logger.warning(
                    "Erreurs de collecte officielle (%s) : %s",
                    len(errors), errors[:5]
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Collecte des sites officiels échouée")

        next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
        logger.info("Prochaine collecte recruteurs prévue à %s", next_run.isoformat())


async def training_scheduler_loop():
    interval = TRAINING_SYNC_INTERVAL_HOURS * 3600
    next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
    logger.info(
        "Planificateur formations FORCE-N activé ; prochaine collecte prévue à %s",
        next_run.isoformat()
    )

    while True:
        await wait_until_utc(next_run)
        try:
            logger.info("Démarrage de la collecte automatique des formations FORCE-N")
            result = await asyncio.to_thread(collect_force_n)
            errors = result.get("errors", [])
            logger.info(
                "Collecte FORCE-N terminée : %s fiches traitées, %s ignorées, %s erreurs",
                result.get("saved", 0),
                result.get("skipped", 0),
                len(errors)
            )
            for error in errors:
                logger.warning("Collecte FORCE-N : %s", error)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Collecte automatique FORCE-N échouée")

        next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
        logger.info(
            "Prochaine collecte FORCE-N prévue à %s",
            next_run.isoformat()
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_doctoral_db()
    init_recruiters_db()
    init_trainings_db()
    tasks = []
    if AUTO_SYNC_ENABLED:
        tasks.append(asyncio.create_task(scheduler_loop()))
    if DOCTORAL_AUTO_SYNC_ENABLED:
        tasks.append(asyncio.create_task(doctoral_scheduler_loop()))
    if RECRUITER_AUTO_SYNC_ENABLED:
        tasks.append(asyncio.create_task(recruiter_scheduler_loop()))
    if TRAINING_AUTO_SYNC_ENABLED:
        tasks.append(asyncio.create_task(training_scheduler_loop()))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

app = FastAPI(title='Job Ci Adduna AI API', version='0.2.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in os.getenv('CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(',') if x.strip()], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.include_router(doctoral_router)
app.include_router(immigration_router)
app.include_router(recruiters_router)
app.include_router(trainings_router)

@app.get('/api/health')
def health(): return {'status':'ok', 'database':str(DB_PATH), 'auto_sync_enabled':AUTO_SYNC_ENABLED, 'sync_interval_minutes':SYNC_INTERVAL_MINUTES}

@app.get('/api/sources')
def source_catalog():
    return {'sources': [
        {'name':'CNRS','type':'Flux RSS officiel','enabled':True,'configuration_required':False,'note':'Postes salariés informatiques pertinents ; mobilité internationale à vérifier sur chaque annonce.'},
        {'name':'ONU Careers RSS','type':'Flux RSS officiel','enabled':True,'configuration_required':False,'note':'Postes informatiques filtrés depuis les annonces officielles ; visa et relocalisation à vérifier annonce par annonce.'},
        {'name':'IOM Careers','type':'API publique officielle Oracle','enabled':True,'configuration_required':False,'note':'Postes informatiques filtrés ; annonces expirées exclues lorsque la date limite est reconnue. Vérifier les conditions de mobilité et d’éligibilité sur la fiche officielle.'},
        {'name':'EBRD Careers','type':'Portail officiel public et fiches de postes','enabled':True,'configuration_required':False,'note':'Postes techniques filtrés depuis les pages publiques EBRD ; les offres expirées sont exclues si la date limite est reconnue. Vérifier l’éligibilité, le visa et la relocalisation sur chaque fiche.'},
        {'name':'UNIDO Careers','type':'Portail public officiel et fiches de postes','enabled':True,'configuration_required':False,'note':'Postes informatiques filtrés sur les intitulés techniques ; annonces expirées exclues si la date limite est reconnue. Les recrutements locaux sont signalés. Vérifier éligibilité, visa et mobilité sur la fiche officielle.'},
        {'name':'World Bank Group Careers','type':'API publique du portail officiel CSOD','enabled':True,'configuration_required':False,'note':'Recherche de postes techniques par plusieurs mots-clés ; annonces expirées exclues lorsque la date est interprétable. Vérifier l’éligibilité internationale, le visa et la relocalisation sur chaque fiche officielle.'},
        {'name':'UNDP Careers','type':'Tableau public officiel et fiches Oracle','enabled':True,'configuration_required':False,'note':'Postes IT filtrés ; annonces expirées exclues lorsque la date limite est disponible et interprétable. Vérifier éligibilité, visa et mobilité sur la fiche officielle.'},
        {'name':'ITU Careers','type':'Portail officiel public et fiches de postes','enabled':True,'configuration_required':False,'note':'Postes informatiques et numériques filtrés depuis les annonces publiques ITU. Les rosters de consultants sont conservés comme missions ; vérifier date limite, éligibilité, rémunération et mobilité sur la fiche officielle.'},
        {'name':'ICAO Careers','type':'Portail public ICAO et liens officiels de candidature Oracle','enabled':True,'configuration_required':False,'note':'Annonces informatiques filtrées depuis le tableau public. Les rosters sont des missions potentielles ; vérifier éligibilité, rémunération, visa et mobilité sur la fiche officielle.'},
        {'name':'WFP Careers','type':'API publique officielle Workday','enabled':True,'configuration_required':False,'note':'Postes informatiques filtrés du catalogue public WFP. Les annonces expirées sont exclues lorsque la date limite est reconnue ; vérifier éligibilité, nationalité et mobilité sur la fiche officielle.'},
        {'name':'GIZ Careers','type':'API publique officielle du portail GIZ','enabled':True,'configuration_required':False,'note':'Offres informatiques filtrées depuis le portail public GIZ. Vérifier la date limite, l’éligibilité internationale, le visa et la mobilité sur la fiche officielle.'},
        {'name':'IsDB Careers','type':'Portail officiel public et fiches de postes','enabled':True,'configuration_required':False,'note':'Postes informatiques filtrés depuis les fiches publiques ; les annonces expirées sont exclues lorsque la date limite est reconnue. Vérifier éligibilité, visa et mobilité sur la fiche officielle.'},
        {'name':'UN Women Careers','type':'API publique officielle Oracle Recruiting','enabled':True,'configuration_required':False,'note':'Offres IT filtrées depuis le portail officiel ONU Femmes ; annonces dont la date limite passée est reconnue exclues. Vérifier nationalité, éligibilité, visa et mobilité sur la fiche officielle.'},
        {'name':'UNFPA Careers','type':'Portail public officiel et fiches de postes','enabled':True,'configuration_required':False,'note':'Offres informatiques filtrées depuis le portail officiel ; annonces dont la date de clôture est reconnue comme passée exclues. Les dates manquantes, restrictions de nationalité, conditions de visa et possibilités de mobilité doivent être vérifiées sur la fiche officielle.'},
        {'name':'UNICEF Careers','type':'Portail public officiel et fiches de postes','enabled':True,'configuration_required':False,'note':'Postes IT filtrés ; annonces expirées exclues lorsque la date limite est interprétable. Les dates absentes et les restrictions de nationalité ou de permis doivent être vérifiées sur la fiche officielle.'},
        {'name':'FAO Careers','type':'Portail public officiel Taleo','enabled':True,'configuration_required':False,'note':'Offres informatiques filtrées sur la première page publique ; rechercher le numéro de réquisition sur le portail FAO. Vérifier disponibilité, éligibilité et mobilité sur la fiche officielle.'},
        {'name':'ILO Careers','type':'Flux RSS officiel','enabled':True,'configuration_required':False,'note':'Offres informatiques filtrées depuis le flux RSS public ; vérifier date limite, éligibilité et mobilité sur chaque fiche officielle.'},
        {'name':'UNESCO Careers','type':'Flux RSS officiel','enabled':True,'configuration_required':False,'note':'Offres IT filtrées sur les intitulés ; vérifier disponibilité, éligibilité, date limite et mobilité sur la fiche officielle.'},
        {'name':'UNOPS Careers','type':'Portail officiel de recrutement et fiches de postes','enabled':True,'configuration_required':False,'note':'Postes IT filtrés depuis le portail officiel ; annonces expirées exclues lorsque la date limite est reconnue. Vérifier éligibilité, contrat, langue et mobilité.'},
        {'name':'African Union Careers','type':'API publique officielle et fiches de postes','enabled':True,'configuration_required':False,'note':'Postes informatiques filtrés ; annonces expirées exclues lorsque la date limite est reconnue. Vérifier grade, éligibilité et mobilité.'},
        {'name':'CEDEAO Careers','type':'Pages publiques officielles paginées et fiches de postes','enabled':True,'configuration_required':False,'note':'Postes IT filtrés ; dates limites et conditions de candidature à vérifier sur chaque fiche officielle.'},
        {'name':'EURAXESS','type':'Pages publiques de recherche','enabled':False,'configuration_required':False,'note':'Jusqu’à trois pages publiques ; offres liées à l’informatique filtrées. Conditions de travail, financement et mobilité à vérifier sur chaque annonce.'},
        {'name':'Expat-Dakar','type':'Sitemaps publics et pages d’annonces','enabled':True,'configuration_required':False,'note':'Annonces informatiques publiques au Sénégal ; employeur et conditions à vérifier sur l’annonce.'},
        {'name':'Liggey','type':'Page publique et données JobPosting structurées','enabled':True,'configuration_required':False,'note':'Offres IT publiques filtrées depuis la catégorie Développement IT de Dakar ; les annonces et leur disponibilité restent à vérifier sur le site.'},
        {'name':'EmploiSenegal','type':'Flux RSS public','enabled':True,'configuration_required':False,'note':'Offres IT extraites du flux RSS ; employeur, fraîcheur et disponibilité à vérifier sur l’annonce.'},
        {'name':'Emploi Dakar','type':'Sitemap public et données JobPosting structurées','enabled':True,'configuration_required':False,'note':'Offres IT publiques filtrées ; disponibilité, date limite et conditions à vérifier sur chaque annonce.'},
        {'name':'MESRI Sénégal','type':'Portail officiel et PDF liés aux annonces','enabled':True,'configuration_required':False,'note':'Annonces informatiques repérées sur le portail universitaire officiel et dans certains PDF autorisés ; vérifier la date limite et la disponibilité sur le document original.'},
        {'name':'Senjob','type':'Pages publiques de catégories et métadonnées HTML','enabled':True,'configuration_required':False,'note':'Offres informatiques publiques ; description, employeur, disponibilité et conditions à vérifier sur chaque annonce.'},
        {'name':'Arbeitnow API','type':'API publique','enabled':True,'configuration_required':False},
        {'name':'Remotive API','type':'API publique','enabled':True,'configuration_required':False,'note':'Respecter les conditions Remotive et attribuer la source.'},
        {'name':'Jobicy API','type':'API publique','enabled':True,'configuration_required':False},
        {'name':'SmartRecruiters','type':'API publique de recrutement','enabled':True,'configuration_required':False,'note':'Collecteur générique ; entreprises configurables via SMARTRECRUITERS_COMPANIES. Catalogue extensible, non exhaustif.'},
        {'name':'MSF Careers','type':'Portail officiel MSF et fiches de postes','enabled':True,'configuration_required':False,'note':'Postes IT et numériques filtrés depuis les offres publiques MSF. Les dates limites reconnues comme passées sont exclues ; vérifier sur chaque fiche l’éligibilité, le droit au travail, le visa et la relocalisation.'},
        {'name':'Handicap International (HI)','type':'API publique officielle Workable','enabled':True,'configuration_required':False,'note':'Offres IT filtrées depuis le tableau public Workable de HI. Les descriptions génériques ne suffisent pas à retenir une annonce ; vérifier éligibilité, visa et mobilité sur la fiche officielle.'},
        {'name':'DRC Careers','type':'Portail public HTML officiel et fiches de postes','enabled':True,'configuration_required':False,'note':'Offres IT filtrées depuis le portail public DRC. Les échéances passées sont exclues lorsqu’elles sont reconnues ; vérifier éligibilité, visa et mobilité sur la fiche officielle.'},
        {'name':'IRC Careers','type':'API publique officielle Workday','enabled':True,'configuration_required':False,'note':'Offres IT et numériques filtrées depuis le portail public IRC Workday. Date limite non supposée lorsqu’elle est absente ; vérifier sur chaque fiche l’éligibilité, le droit au travail, le visa et la relocalisation.'},
        {'name':'ICRC Careers','type':'Portail officiel public SAP SuccessFactors','enabled':True,'configuration_required':False,'note':'Postes informatiques et numériques filtrés depuis le portail officiel du CICR. Vérifier sur chaque fiche la date limite, le statut mobile ou résident, les restrictions de nationalité, le visa et la relocalisation.'},
        {'name':'NRC Careers','type':'API publique officielle Oracle Recruiting','enabled':True,'configuration_required':False,'note':'Offres IT, développement, données et numérique filtrées depuis le portail officiel NRC. Les dates limites passées sont exclues si elles sont reconnues ; vérifier sur chaque fiche l’expérience requise, les restrictions de droit au travail, le visa et la relocalisation.'},
        {'name':'Action contre la Faim (ACF)','type':'Portail public officiel et fiches de postes','enabled':True,'configuration_required':False,'note':'Offres informatiques filtrées depuis le portail public ACF ; les échéances passées sont exclues lorsqu’elles sont reconnues. Vérifier éligibilité, visa et mobilité sur chaque fiche officielle.'},
        {'name':'Greenhouse','type':'API carrière','enabled':bool(os.getenv('GREENHOUSE_BOARDS','').strip()),'configuration_required':True},
        {'name':'Lever','type':'API carrière','enabled':bool(os.getenv('LEVER_SITES','').strip()),'configuration_required':True},
        {'name':'Remote Jobs API','type':'Agrégateur HTTP auto-hébergé','enabled':bool(REMOTE_JOBS_API_URL),'configuration_required':True},
        {'name':'JobSpy','type':'Connecteur Python optionnel','enabled':JOBSPY_ENABLED,'configuration_required':True,'note':'Activer uniquement les sites dont les conditions autorisent cet usage.'},
        {'name':'Hirehunt','type':'Connecteur Python optionnel','enabled':HIREHUNT_ENABLED,'configuration_required':True},
        {'name':'Crawl4AI','type':'Crawler de pages publiques configurées','enabled':CRAWL4AI_ENABLED,'configuration_required':True},
        {'name':'ScrapeGraphAI','type':'Extraction IA sur pages configurées','enabled':SCRAPEGRAPHAI_ENABLED,'configuration_required':True,'requires_llm_key':True},
    ]}

@app.get('/api/profile')
def get_profile(): return PROFILE

@app.get('/api/jobs')
def list_jobs(q: str = '', country: str = '', work_mode: str = '', min_score: int = 0, source: str = ''):
    with connect() as db: rows = db.execute('SELECT * FROM jobs ORDER BY COALESCE(published_at, collected_at, created_at) DESC, id DESC').fetchall()
    jobs = [row_to_job(r) for r in rows]
    if q:
        needle=q.lower(); jobs=[j for j in jobs if needle in (j['title']+' '+j['company']+' '+j['description']+' '+' '.join(j['skills'])).lower()]
    if country: jobs=[j for j in jobs if country.lower() in (j.get('country') or '').lower() or country.lower() in (j.get('location') or '').lower()]
    if work_mode: jobs=[j for j in jobs if work_mode.lower() in (j.get('work_mode') or '').lower()]
    if source: jobs=[j for j in jobs if source.lower() in (j.get('source') or '').lower()]
    return [j for j in jobs if j['match_score'] >= min_score]

@app.post('/api/jobs', status_code=201)
def create_job(job: JobIn):
    now=utcnow(); payload=job.model_dump(); payload['content_hash']=hashlib.sha256(((job.url or f'{job.title}|{job.company}').lower()).encode()).hexdigest()
    with connect() as db:
        cur=db.execute('''INSERT INTO jobs(title,company,location,country,work_mode,contract_type,description,url,source,skills,created_at,published_at,collected_at,content_hash)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(job.title,job.company,job.location,job.country,job.work_mode,job.contract_type,job.description,job.url,job.source,','.join(job.skills),now,job.published_at,now,payload['content_hash']))
        db.commit(); row=db.execute('SELECT * FROM jobs WHERE id=?',(cur.lastrowid,)).fetchone()
    return row_to_job(row)

@app.delete('/api/jobs/{job_id}', status_code=204)
def delete_job(job_id: int):
    with connect() as db:
        cur=db.execute('DELETE FROM jobs WHERE id=?',(job_id,)); db.commit()
        if cur.rowcount == 0: raise HTTPException(404,'Offre introuvable')

@app.patch('/api/jobs/{job_id}/application')
def update_application(job_id: int, update: ApplicationUpdate):
    allowed={'À examiner','À candidater','Candidature préparée','Candidature envoyée','Entretien','Refus','Acceptée'}
    if update.status not in allowed: raise HTTPException(400,'Statut non autorisé')
    with connect() as db:
        cur=db.execute('UPDATE jobs SET status=?, notes=? WHERE id=?',(update.status,update.notes,job_id)); db.commit()
        if not cur.rowcount: raise HTTPException(404,'Offre introuvable')
        row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
    return row_to_job(row)

@app.post('/api/drafts')
def draft_application(req: DraftRequest):
    with connect() as db: row=db.execute('SELECT * FROM jobs WHERE id=?',(req.job_id,)).fetchone()
    if not row: raise HTTPException(404,'Offre introuvable')
    job=row_to_job(row)
    matched=[s for s in PROFILE['skills'] if s.lower() in (job['title']+' '+job['description']+' '+' '.join(job['skills'])).lower()]
    skill_text=', '.join(matched[:6]) if matched else 'développement logiciel et conception d’API'
    cv_note=' Le CV fourni doit être vérifié et adapté avant envoi.' if req.cv_text.strip() else ' Ajoutez votre CV pour une adaptation plus précise.'
    letter=f"Madame, Monsieur,\n\nJe vous propose ma candidature au poste de {job['title']} chez {job['company']}. Ingénieur logiciel Full Stack, je possède plus de cinq ans d’expérience en développement d’applications, API et solutions métiers, notamment dans le secteur bancaire.\n\nMon expérience avec {skill_text} me permet de contribuer à la conception, au développement et à la maintenance de solutions robustes, en collaboration avec les équipes produit et techniques. Je souhaite échanger avec vous sur les besoins du poste et la valeur que je pourrais apporter à votre équipe.\n\nJe vous remercie pour votre attention et reste disponible pour un entretien.\n\nCordialement,\nFallou Ndiaye\nfallou.ndiaye95@univ-thies.sn\nhttps://www.linkedin.com/in/fallou-ndiaye-85448b191/\n\nNote de préparation : cette lettre est un brouillon à vérifier. Ne l’envoyez qu’après validation des faits et personnalisation.{cv_note}"
    english = bool(re.search(r'\b(developer|engineer|software|mobile|full.?stack|apply|requirements|responsibilities|job description)\b', (job['title'] + ' ' + job['description'][:1600]).lower())) and not bool(re.search(r'\b(développeur|ingénieur|expérience|candidature|responsabilités|compétences requises)\b', (job['title'] + ' ' + job['description'][:1600]).lower()))
    if english:
        letter = f"Dear Hiring Team,\n\nI am writing to apply for the {job['title']} position at {job['company']}. I am a Full Stack Software Engineer with more than five years of experience building and maintaining business applications and APIs, including solutions in the banking sector.\n\nMy experience with {skill_text} would allow me to contribute to the design, development, and maintenance of reliable software in collaboration with product and engineering teams. I would welcome the opportunity to discuss how my background aligns with your needs.\n\nKind regards,\nFallou Ndiaye\nfallou.ndiaye95@univ-thies.sn\nhttps://www.linkedin.com/in/fallou-ndiaye-85448b191/\n\nPreparation note: this is a draft. Verify all statements and personalize it before sending.{cv_note}"
        email_subject=f"Application – {job['title']}"
        email=f"Dear Hiring Team,\n\nI would like to apply for the {job['title']} position at {job['company']}. My Full Stack background, including Java/Spring Boot, Angular, and API development, may be relevant to your needs.\n\nPlease find my CV attached. I would be glad to discuss my application with you.\n\nKind regards,\nFallou Ndiaye"
    else:
        email_subject=f"Candidature – {job['title']}"
        email=f"Bonjour,\n\nJe vous contacte pour vous proposer ma candidature au poste de {job['title']} chez {job['company']}. Mon profil Full Stack (Java/Spring Boot, Angular et développement d’API) pourrait correspondre à vos besoins.\n\nVous trouverez mon CV en pièce jointe. Je serais heureux d’échanger avec vous.\n\nCordialement,\nFallou Ndiaye"
    return {'job':job,'subject':email_subject,'email':email,'letter':letter,'language':'en' if english else 'fr','cv_suggestion':'CV anglais' if english else 'CV français','requires_human_approval':True,'warning':'Brouillon généré à partir du profil de base. Vérifiez chaque affirmation, choisissez le CV correspondant à la langue de l’annonce et validez manuellement avant tout envoi.'}

@app.get('/api/sync/status')
def sync_status():
    with connect() as db:
        latest=db.execute('SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1').fetchone()
        total=db.execute("SELECT COUNT(*) AS n FROM jobs WHERE source != 'Ajout manuel'").fetchone()['n']
    if not latest: return {'auto_sync_enabled':AUTO_SYNC_ENABLED,'interval_minutes':SYNC_INTERVAL_MINUTES,'collected_offers':total,'last_run':None}
    d=dict(latest)
    try: d['sources']=json.loads(d.pop('sources_json') or '{}')
    except ValueError: d['sources']={}
    return {'auto_sync_enabled':AUTO_SYNC_ENABLED,'interval_minutes':SYNC_INTERVAL_MINUTES,'collected_offers':total,'last_run':d}

@app.post('/api/sync/run')
async def sync_now():
    try: return await run_collection()
    except Exception as exc: raise HTTPException(502, f'La collecte a échoué: {str(exc)[:400]}')

@app.get('/api/stats')
def stats():
    with connect() as db:
        rows=db.execute('SELECT status,country,source FROM jobs').fetchall()
    statuses={}; countries={}; sources={}
    for r in rows:
        statuses[r['status'] or 'À examiner']=statuses.get(r['status'] or 'À examiner',0)+1
        countries[r['country'] or 'Non précisé']=countries.get(r['country'] or 'Non précisé',0)+1
        sources[r['source'] or 'Inconnue']=sources.get(r['source'] or 'Inconnue',0)+1
    return {'total':len(rows),'statuses':statuses,'countries':countries,'sources':sources}
