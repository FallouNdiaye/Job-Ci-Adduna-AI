from datetime import date

from app.main import _isdb_is_relevant, _isdb_parse_deadline


def test_isdb_detects_it_title():
    assert _isdb_is_relevant(
        "Software Engineer",
        "General responsibilities",
    )


def test_isdb_detects_it_department_in_job_details():
    assert _isdb_is_relevant(
        "Collaboration Operations Specialist",
        "Department: Information Management and Disruptive Technology "
        "Division: Technology Operations",
    )


def test_isdb_rejects_unrelated_job():
    assert not _isdb_is_relevant(
        "Portfolio Manager",
        "Manage development projects in health and education.",
    )


def test_isdb_parses_portal_closing_date():
    assert _isdb_parse_deadline("11-Nov-2026") == date(2026, 11, 11)


def test_isdb_keeps_unknown_date_unparsed():
    assert _isdb_parse_deadline("To be confirmed") is None
