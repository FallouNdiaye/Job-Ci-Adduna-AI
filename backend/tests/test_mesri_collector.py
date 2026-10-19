import asyncio

from app.main import collect_mesri_jobs


BASE = "https://espaceuniversitaire.mesrisenegal.sn"
LISTING_PATHS = (
    "/public/communiques",
    "/public/vie-estudiantine/appels-a-candidatures",
    "/public/actualites",
)
ARTICLE_URL = BASE + "/public/actualites/developpeur-full-stack"


class FakeResponse:
    def __init__(self, url, body, status_code=200, is_redirect=False):
        self.url = url
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.text = (
            self.content.decode("utf-8", errors="replace")
            if isinstance(self.content, bytes)
            else str(self.content)
        )
        self.status_code = status_code
        self.is_redirect = is_redirect


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url not in self.pages:
            raise AssertionError(f"Requête inattendue : {url}")
        return self.pages[url]


def make_client(article_html, listing_html=None):
    if listing_html is None:
        listing_html = (
            '<a href="/public/actualites/developpeur-full-stack">'
            "Voir l'annonce</a>"
        )

    pages = {
        BASE + path: FakeResponse(
            BASE + path, listing_html
        )
        for path in LISTING_PATHS
    }
    pages[ARTICLE_URL] = FakeResponse(ARTICLE_URL, article_html)
    return FakeClient(pages)


def test_mesri_collects_official_it_article_and_deduplicates_listing_links():
    listing = """
    <a href="/public/actualites/developpeur-full-stack">Annonce</a>
    <a href="/public/actualites/developpeur-full-stack">Annonce répétée</a>
    """
    article = """
    <html><body>
      <h1>Développeur Full Stack</h1>
      <p>Recrutement informatique au Sénégal.</p>
      <p>Compétences : Python, API et développement logiciel.</p>
      <p>Date limite de candidature : 31 décembre 2099</p>
    </body></html>
    """
    client = make_client(article, listing)

    jobs = asyncio.run(collect_mesri_jobs(client))

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Développeur Full Stack"
    assert jobs[0]["source"] == "MESRI Sénégal"
    assert jobs[0]["url"] == ARTICLE_URL
    assert "développement logiciel" in jobs[0]["description"].lower()
    assert sum(url == ARTICLE_URL for url, _ in client.calls) == 2
    assert all(kwargs.get("follow_redirects") is False
               for _, kwargs in client.calls)


def test_mesri_excludes_article_with_explicit_expired_deadline():
    article = """
    <html><body>
      <h1>Développeur Full Stack</h1>
      <p>Date limite de candidature : 01 janvier 2020</p>
      <p>Développement de logiciels et systèmes informatiques.</p>
    </body></html>
    """
    client = make_client(article)

    assert asyncio.run(collect_mesri_jobs(client)) == []


def test_mesri_rejects_external_article_links():
    listing = """
    <a href="https://example.com/public/actualites/developpeur">
      Développeur Full Stack
    </a>
    """
    client = make_client("<h1>Développeur Full Stack</h1>", listing)

    assert asyncio.run(collect_mesri_jobs(client)) == []
    assert all(
        "example.com" not in url
        for url, _ in client.calls
    )


def test_mesri_rejects_article_url_with_invalid_port():
    listing = """
    <a href="https://espaceuniversitaire.mesrisenegal.sn:99999/public/actualites/developpeur">
      Développeur Full Stack
    </a>
    """
    client = make_client("<h1>Développeur Full Stack</h1>", listing)

    assert asyncio.run(collect_mesri_jobs(client)) == []
    assert all(":99999" not in url for url, _ in client.calls)


def make_minimal_pdf(lines):
    """Construit un PDF ASCII minimal en mémoire, sans dépendance supplémentaire."""
    commands = ["BT", "/F1 12 Tf", "50 750 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -20 Td")
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode()
        + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())

    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(pdf)


def make_pdf_client(pdf_lines):
    pdf_url = "https://www.unchk.sn/offres-recrutement.pdf"
    article = """
    <html><body>
      <h1>Communiqué de recrutement</h1>
      <p>Consulter le document officiel.</p>
      <a href="https://www.unchk.sn/offres-recrutement.pdf">
        Télécharger le PDF
      </a>
    </body></html>
    """
    client = make_client(article)
    client.pages[pdf_url] = FakeResponse(pdf_url, make_minimal_pdf(pdf_lines))
    return client


def test_mesri_pdf_collects_multiple_distinct_it_offers_with_stable_ids():
    lines = [
        "Developpeur Full Stack",
        "Administrateur systemes et reseaux",
    ]
    first_run = asyncio.run(collect_mesri_jobs(make_pdf_client(lines)))
    second_run = asyncio.run(collect_mesri_jobs(make_pdf_client(lines)))

    assert len(first_run) == 2
    assert {job["title"] for job in first_run} == set(lines)
    assert all(job["source"] == "MESRI Sénégal (PDF)" for job in first_run)

    first_by_title = {job["title"]: job for job in first_run}
    second_by_title = {job["title"]: job for job in second_run}

    assert first_by_title.keys() == second_by_title.keys()
    for title in lines:
        assert first_by_title[title]["external_id"] == second_by_title[title]["external_id"]
        assert first_by_title[title]["content_hash"] == second_by_title[title]["content_hash"]

    assert first_by_title[lines[0]]["external_id"] != first_by_title[lines[1]]["external_id"]
    assert first_by_title[lines[0]]["content_hash"] != first_by_title[lines[1]]["content_hash"]


def test_mesri_pdf_with_explicit_expired_deadline_is_excluded():
    lines = [
        "Developpeur Full Stack",
        "Date limite de candidature : 01 janvier 2020",
    ]
    client = make_pdf_client(lines)

    assert asyncio.run(collect_mesri_jobs(client)) == []


def test_mesri_pdf_keeps_open_offer_when_another_offer_is_expired():
    lines = [
        "Developpeur Full Stack",
        "Date limite de candidature : 01 janvier 2020",
        "Administrateur systemes et reseaux",
        "Date limite de candidature : 31 decembre 2099",
    ]
    client = make_pdf_client(lines)

    jobs = asyncio.run(collect_mesri_jobs(client))
    titles = {job["title"] for job in jobs}

    assert "Administrateur systemes et reseaux" in titles
    assert "Developpeur Full Stack" not in titles


def test_mesri_pdf_does_not_split_offer_on_role_mentioned_in_description():
    lines = [
        "Developpeur Full Stack",
        "Missions : collaborer avec un Administrateur systemes et reseaux.",
        "Date limite de candidature : 01 janvier 2020",
    ]
    client = make_pdf_client(lines)

    jobs = asyncio.run(collect_mesri_jobs(client))

    assert jobs == []
