import asyncio
import json

from app import main


def test_run_collection_isolates_collector_errors_and_saves_results(
    tmp_path, monkeypatch
):
    # Base SQLite strictement temporaire : la base réelle reste intacte.
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "jobs_test.db")
    main.init_db()

    calls = []

    async def failing_collector(*args, **kwargs):
        calls.append("failing")
        raise RuntimeError("erreur simulée")

    async def successful_collector(*args, **kwargs):
        calls.append("successful")
        return [{
            "title": "Java Software Engineer",
            "company": "Test Company",
            "location": "Dakar",
            "country": "Sénégal",
            "work_mode": "Non précisé",
            "contract_type": "CDI",
            "description": "Développement Java et Spring Boot.",
            "url": "https://example.test/jobs/java",
            "source": "Test source",
            "skills": ["Java", "Spring Boot"],
            "published_at": None,
            "external_id": "test-java-001",
            "content_hash": "test-hash-java-001",
        }]

    async def no_op_collector():
        return []

    original_collectors = [
        ("Failing test collector", failing_collector),
        ("Successful test collector", successful_collector),
    ]

    # Remplace temporairement la construction de la liste des sources.
    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: FakeAsyncClient())

    # Les collecteurs de run_collection sont définis dans la fonction.
    # On remplace les fonctions référencées pour éviter tout accès réseau.
    collector_names = [
        "collect_cnrs", "collect_iom", "collect_world_bank_group",
        "collect_unido", "collect_ebrd", "collect_undp", "collect_itu",
        "collect_icao", "collect_wfp", "collect_giz", "collect_isdb",
        "collect_unfpa", "collect_un_women", "collect_unicef", "collect_fao",
        "collect_ilo", "collect_unesco", "collect_unops", "collect_african_union",
        "collect_ecowas", "collect_un_careers", "collect_expat_dakar",
        "collect_liggey", "collect_emploisenegal", "collect_emploi_dakar", "collect_mesri_jobs",
        "collect_senjob", "collect_arbeitnow", "collect_remotive", "collect_jobicy",
        "collect_smartrecruiters", "collect_acf", "collect_irc", "collect_drc",
        "collect_hi", "collect_icrc", "collect_msf", "collect_nrc",
        "collect_remote_jobs_api", "collect_greenhouse", "collect_lever",
        "collect_jobspy", "collect_hirehunt", "collect_crawl4ai",
        "collect_scrapegraphai",
    ]

    async def empty_collector(*args, **kwargs):
        return []

    for name in collector_names:
        if hasattr(main, name):
            monkeypatch.setattr(main, name, empty_collector)

    # La première source échoue ; la seconde fournit une offre.
    monkeypatch.setattr(main, "collect_cnrs", failing_collector)
    monkeypatch.setattr(main, "collect_iom", successful_collector)

    result = asyncio.run(main.run_collection())

    assert calls == ["failing", "successful"]
    assert result["status"] == "terminé avec erreurs"
    assert result["inserted"] == 1
    assert any("CNRS" in error for error in result["errors"])

    with main.connect() as db:
        jobs = db.execute("SELECT title, url FROM jobs").fetchall()
        run = db.execute(
            "SELECT status, sources_json, error FROM sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Java Software Engineer"
    assert jobs[0]["url"] == "https://example.test/jobs/java"
    assert run["status"] == "terminé avec erreurs"
    assert "CNRS" in run["sources_json"]
    assert "erreur simulée" in run["error"]


def test_source_catalog_contains_mesri():
    catalog = main.source_catalog()
    mesri = next(
        (item for item in catalog["sources"] if item["name"] == "MESRI Sénégal"),
        None,
    )
    assert mesri is not None
    assert mesri["enabled"] is True
    assert mesri["configuration_required"] is False
