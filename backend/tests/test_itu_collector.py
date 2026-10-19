from datetime import date

from app.main import _itu_is_relevant, _itu_parse_deadline


def test_itu_accepts_software_and_digital_roles():
    assert _itu_is_relevant("Software Engineer")
    assert _itu_is_relevant("Digital Inclusion Consultant", "ICT accessibility projects")


def test_itu_rejects_unrelated_roles():
    assert not _itu_is_relevant("Human Resources Officer", "Recruitment and payroll")


def test_itu_parses_english_deadline():
    assert _itu_parse_deadline("31 December 2026") == date(2026, 12, 31)
    assert _itu_parse_deadline("December 31, 2026") == date(2026, 12, 31)


def test_itu_keeps_unknown_deadline_unparsed():
    assert _itu_parse_deadline("To be confirmed") is None
    assert _itu_parse_deadline(None) is None
