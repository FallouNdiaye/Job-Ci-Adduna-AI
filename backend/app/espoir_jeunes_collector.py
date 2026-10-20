"""Extraction prudente du catalogue officiel 3FPT Espoir Jeunes.

Ce module ne modifie pas la base de données et ne crée aucune offre active.
L'OCR reste facultatif.
"""

import io
import logging
import re
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader

logger = logging.getLogger("jobciadduna.espoir_jeunes")

SOURCE_URL = (
    "https://espoirjeunes.3fpt.sn/wp-content/uploads/2024/05/"
    "ISEP-catalogue-Formation.pdf"
)
ALLOWED_HOST = "espoirjeunes.3fpt.sn"
MAX_PDF_BYTES = 12 * 1024 * 1024
MAX_PAGES = 30

IT_KEYWORDS = (
    "informatique",
    "développement logiciel",
    "developpement logiciel",
    "développement web",
    "developpement web",
    "programmation",
    "cybersécurité",
    "cybersecurite",
    "réseau informatique",
    "reseau informatique",
    "base de données",
    "base de donnees",
    "intelligence artificielle",
    "système informatique",
    "systeme informatique",
    "maintenance informatique",
    "technicien informatique",
    "numérique",
    "numerique",
    "logiciel",
    "python",
    "java",
    "javascript",
    "développeur",
    "developpeur",
    "webmaster",
    "data",
)

# Ce catalogue identifié date de 2024. Il ne constitue pas une preuve
# qu'une inscription est ouverte en 2026.
CATALOGUE_HISTORICAL = True


def validate_source_url(url: str) -> bool:
    """N'autoriser que le PDF HTTPS du domaine officiel."""
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == ALLOWED_HOST
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        return False


def download_catalogue(url: str = SOURCE_URL) -> bytes:
    """Télécharger le PDF officiel avec une limite de taille stricte."""
    if not validate_source_url(url):
        raise ValueError("URL non autorisée pour le catalogue Espoir Jeunes.")

    with httpx.Client(
        timeout=30,
        follow_redirects=False,
        headers={"User-Agent": "JobCiAddunaAI/1.0 (public training catalogue)"},
    ) as client:
        with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise ValueError(f"Téléchargement impossible : HTTP {response.status_code}")

            if not validate_source_url(str(response.url)):
                raise ValueError("URL finale non autorisée.")

            content_type = response.headers.get("content-type", "").lower()
            if "pdf" not in content_type and not url.lower().endswith(".pdf"):
                raise ValueError("La ressource ne semble pas être un PDF.")

            chunks = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise ValueError("PDF refusé : taille supérieure à la limite autorisée.")
                chunks.append(chunk)

    content = b"".join(chunks)
    if not content.startswith(b"%PDF-"):
        raise ValueError("Le contenu téléchargé n'est pas un PDF valide.")

    return content


def extract_pdf_text(pdf_bytes: bytes, *, enable_ocr: bool = True) -> dict:
    """Extraire le texte du PDF, avec OCR facultatif pour les pages scannées."""
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("Le contenu fourni n'est pas un PDF valide.")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError("PDF refusé : taille supérieure à la limite autorisée.")

    reader = PdfReader(io.BytesIO(pdf_bytes), strict=True)
    if len(reader.pages) > MAX_PAGES:
        raise ValueError("PDF refusé : nombre de pages supérieur à la limite.")

    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text_pages = sum(bool(text) for text in pages)
    ocr_pages = 0
    ocr_available = False

    # Ne charger les bibliothèques lourdes que si l'OCR est nécessaire.
    if enable_ocr and text_pages < len(pages):
        try:
            import numpy as np
            import pymupdf
            from rapidocr import RapidOCR

            ocr_available = True
            engine = RapidOCR()
            document = pymupdf.open(stream=pdf_bytes, filetype="pdf")

            try:
                for index, existing_text in enumerate(pages):
                    if existing_text:
                        continue

                    pixmap = document[index].get_pixmap(
                        matrix=pymupdf.Matrix(1.5, 1.5),
                        alpha=False,
                    )
                    image = np.frombuffer(
                        pixmap.samples, dtype=np.uint8
                    ).reshape(pixmap.height, pixmap.width, pixmap.n)

                    result = engine(image)
                    # Compatibilité avec les retours tuple et objet des versions
                    # de RapidOCR. Les éléments reconnus ne sont jamais supposés
                    # être des offres structurées.
                    if isinstance(result, tuple):
                        result = result[0]

                    lines = []
                    if result is not None:
                        texts = getattr(result, "txts", None)
                        if texts is not None:
                            lines.extend(str(item) for item in texts)
                        elif isinstance(result, (list, tuple)):
                            for item in result:
                                if isinstance(item, (list, tuple)) and len(item) >= 2:
                                    lines.append(str(item[1]))

                    pages[index] = "\n".join(lines).strip()
                    if pages[index]:
                        ocr_pages += 1
            finally:
                document.close()

        except ImportError:
            logger.info("OCR indisponible : installer les dépendances facultatives.")
        except Exception:
            logger.exception("Échec de l'extraction OCR du catalogue.")

    combined_text = "\n\n".join(
        f"[Page {index + 1}]\n{text}"
        for index, text in enumerate(pages)
        if text
    )

    return {
        "text": combined_text,
        "page_count": len(pages),
        "text_pages": text_pages,
        "ocr_pages": ocr_pages,
        "ocr_available": ocr_available,
        "historical_catalogue": CATALOGUE_HISTORICAL,
        "source_url": SOURCE_URL,
    }


def find_it_related_lines(text: str) -> list[str]:
    """Repérer des lignes informatiques à examiner, sans créer d'offres."""
    matches = []
    seen = set()

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" \t-•")
        if len(line) < 4 or len(line) > 500:
            continue

        normalized = line.casefold()
        if any(keyword in normalized for keyword in IT_KEYWORDS):
            key = normalized
            if key not in seen:
                seen.add(key)
                matches.append(line)

    return matches


def inspect_catalogue(pdf_bytes: bytes, *, enable_ocr: bool = True) -> dict:
    """Retourner les résultats d'analyse, sans insertion en base."""
    extraction = extract_pdf_text(pdf_bytes, enable_ocr=enable_ocr)
    candidates = find_it_related_lines(extraction["text"])

    return {
        **extraction,
        "it_related_lines": candidates,
        "candidate_count": len(candidates),
        "saved_to_database": False,
        "application_status": "À vérifier — catalogue historique",
        "funding_status": "UNKNOWN",
        "warning": (
            "Les lignes détectées ne sont pas des offres vérifiées. "
            "Les dates, conditions et financements doivent être confirmés "
            "sur une publication officielle actuelle."
        ),
    }
