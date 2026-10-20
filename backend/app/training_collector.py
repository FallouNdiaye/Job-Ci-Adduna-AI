"""Collecteur prudent des formations informatiques du catalogue FORCE-N."""

import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.trainings import TrainingIn, save_training

logger = logging.getLogger("jobhunter.training_collector")

CATALOG_URL = "https://force-n.sn/catalogue"
ALLOWED_HOSTS = {"force-n.sn", "www.force-n.sn"}

IT_KEYWORDS = (
    "informatique", "intelligence artificielle", "cybersécurité",
    "cybersecurite", "data", "internet", "iot", "développement",
    "developpement", "python", "java", "php", "front-end", "frontend",
    "back-end", "backend", "web 3", "web3", "ux/ui", "uxui",
    "no code", "low code", "logiciel", "mobile", "programmation",
    "cloud", "réseau", "reseau", "digital", "numérique", "numerique",
    "traitement de données", "traitement de donnees",
)

FREE_PATTERNS = (
    r"\bformation\s+(?:est\s+)?100\s*%\s+gratuite\b",
    r"\bformation\s+entièrement\s+gratuite\b",
    r"\bformation\s+totalement\s+gratuite\b",
    r"\bformation\s+entièrement\s+offerte\s+par\s+la\s+fondation\s+mastercard\b",
    r"\bformation\s+entierement\s+offerte\s+par\s+la\s+fondation\s+mastercard\b",
)


def official_url(url):
    """Accepter uniquement les URL HTTPS du domaine officiel."""
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in ALLOWED_HOSTS
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        return False


def get_page(client, url):
    if not official_url(url):
        raise ValueError("URL hors du domaine officiel FORCE-N")

    response = client.get(url)
    if response.status_code != 200:
        raise ValueError(f"HTTP {response.status_code}")
    if not official_url(str(response.url)):
        raise ValueError("Redirection hors du domaine officiel")

    return BeautifulSoup(response.text, "html.parser")


def extract_text(element):
    if element is None:
        return ""
    return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()


def extract_application_url(page, base_url):
    """Extraire un lien HTTPS explicitement identifié comme préinscription."""
    if not official_url(base_url):
        return ""

    for anchor in page.select("a[href]"):
        label = extract_text(anchor).casefold()
        if not re.search(r"\bpr[eé][\s-]*inscri(?:re|ption)\b", label):
            continue

        href = urljoin(base_url, anchor.get("href", ""))
        try:
            parsed = urlparse(href)
            host = (parsed.hostname or "").lower()
            if (
                parsed.scheme == "https"
                and host in (ALLOWED_HOSTS | {"urlz.fr"})
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
                and not parsed.fragment
            ):
                return href
        except ValueError:
            continue

    return ""


def is_it_related(text):
    normalized = text.casefold()
    return any(keyword in normalized for keyword in IT_KEYWORDS)


def find_cards(soup):
    """Repérer les cartes du catalogue sans dépendre du texte du bouton."""
    cards = soup.select(".pad")
    if cards:
        return cards

    # Repli si la structure CSS du catalogue évolue.
    return soup.select("h3.name")


def card_has_explicit_free_badge(card):
    """Détecter un libellé autonome « Gratuit » sur une carte officielle."""
    return any(
        re.fullmatch(r"\s*gratuit\s*", str(node), flags=re.IGNORECASE)
        for node in card.find_all(string=True)
    )


def extract_card_link(card, base_url):
    anchor = card.select_one("h3.name a[href]")
    if anchor is None:
        anchor = card.select_one('a[href*="/certificat/"]')

    if anchor is None and getattr(card, "name", None) == "h3":
        anchor = card.select_one("a[href]")

    if anchor is None:
        return None, "", ""

    url = urljoin(base_url, anchor.get("href", ""))
    parsed = urlparse(url)
    if not official_url(url) or not parsed.path.startswith("/certificat/"):
        return None, "", ""

    title = extract_text(card.select_one("h3.name")) or extract_text(anchor)
    summary = extract_text(card.select_one(".desc.prez"))
    return url, title, summary


def collect_force_n():
    """Enregistrer les fiches informatiques accessibles sans inventer de données."""
    result = {"seen": 0, "saved": 0, "skipped": 0, "errors": []}

    try:
        with httpx.Client(
            timeout=20,
            follow_redirects=False,
            headers={"User-Agent": "JobCiAddunaAI/1.0 (public training catalogue)"},
        ) as client:
            catalogue = get_page(client, CATALOG_URL)
            links = {}

            for card in find_cards(catalogue):
                url, title, summary = extract_card_link(card, CATALOG_URL)
                if not url:
                    continue

                # Ne retenir que les fiches liées à l'informatique.
                if not is_it_related(f"{title} {summary}"):
                    result["skipped"] += 1
                    continue

                links[url] = {
                    "title": title,
                    "summary": summary,
                    "free_badge": card_has_explicit_free_badge(card),
                }

            for url, card_data in sorted(links.items()):
                result["seen"] += 1
                try:
                    page = get_page(client, url)
                    heading = page.find("h1")
                    title = extract_text(heading) or card_data["title"]

                    root = page.select_one("main") or page.select_one("article") or page.body
                    if root:
                        for unwanted in root.select(
                            "script, style, nav, footer, header, aside, form"
                        ):
                            unwanted.decompose()
                    description = extract_text(root) if root else ""
                    if not description:
                        description = card_data["summary"] or title

                    text = description.casefold()
                    funding_status = "UNKNOWN"
                    funding_evidence = ""
                    cost_details = ""

                    for pattern in FREE_PATTERNS:
                        match = re.search(pattern, text, flags=re.IGNORECASE)
                        if match:
                            funding_status = "CONFIRMED_FULL"
                            funding_evidence = match.group(0)
                            cost_details = "Gratuité explicitement annoncée sur la fiche officielle."
                            break

                    # Le catalogue officiel peut afficher « Gratuit » uniquement
                    # sur la carte, sans répéter cette information dans la fiche.
                    if funding_status == "UNKNOWN" and card_data.get("free_badge"):
                        funding_status = "CONFIRMED_FULL"
                        funding_evidence = "Gratuit (carte du catalogue officiel)"
                        cost_details = (
                            "Libellé « Gratuit » affiché sur la carte officielle "
                            "du catalogue FORCE-N."
                        )

                    eligibility = ""
                    match = re.search(
                        r"public cible\s*:?\s*(.*?)(?=\s+(?:liste\s+\(?indicative|"
                        r"modalités pédagogiques|conditions d'admission|"
                        r"prérequis|pré-requis|contact)\b|$)",
                        description,
                        flags=re.IGNORECASE,
                    )
                    if match:
                        eligibility = match.group(1).strip()[:2000]

                    mode_text = " ".join(
                        [
                            text,
                            extract_text(page.select_one(".desc.mode")).casefold(),
                        ]
                    )
                    if "hybride" in mode_text:
                        delivery_mode = "Hybride"
                    elif "en ligne" in mode_text or "à distance" in mode_text:
                        delivery_mode = "En ligne"
                    elif "présentiel" in mode_text:
                        delivery_mode = "Présentiel"
                    else:
                        delivery_mode = "Non précisé"

                    application_url = extract_application_url(page, url)
                    item = TrainingIn(
                        title=title[:400],
                        provider="FORCE-N",
                        category="formation",
                        country="Sénégal",
                        delivery_mode=delivery_mode,
                        eligibility=eligibility,
                        description=description[:12000],
                        official_url=url,
                        application_url=application_url,
                        funding_status=funding_status,
                        funding_evidence=funding_evidence,
                        cost_details=cost_details,
                        deadline=None,
                        source_name="FORCE-N",
                    )
                    save_training(item)
                    result["saved"] += 1

                except Exception as exc:
                    message = f"{url}: {exc}"
                    result["errors"].append(message)
                    logger.warning("Formation FORCE-N ignorée : %s", message)

    except Exception as exc:
        result["errors"].append(f"Catalogue FORCE-N : {exc}")
        logger.exception("Collecte du catalogue FORCE-N impossible")

    return result
