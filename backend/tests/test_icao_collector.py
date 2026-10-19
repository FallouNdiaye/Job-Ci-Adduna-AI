from datetime import date

from app.main import _icao_extract_jobs, _icao_is_relevant, _icao_parse_deadline


def test_icao_accepts_clear_it_roles():
    assert _icao_is_relevant("ICAO Roster-Computer IT Engineer Expert")
    assert _icao_is_relevant("Software Developer")
    assert _icao_is_relevant("Cybersecurity Specialist")


def test_icao_rejects_unrelated_roles():
    assert not _icao_is_relevant("Human Resources Officer")
    assert not _icao_is_relevant("Digital Marketing & Communications Intern")


def test_icao_parses_deadlines():
    assert _icao_parse_deadline("31/12/2027") == date(2027, 12, 31)
    assert _icao_parse_deadline("2027-12-31") == date(2027, 12, 31)
    assert _icao_parse_deadline("To be confirmed") is None


def test_icao_extracts_only_relevant_future_official_listings():
    html = """
    <table>
      <tr><th>Title</th><th>Grade</th><th>Job ID</th><th>Location</th><th>Deadline</th></tr>
      <tr>
        <td><a href="https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions/job/20345">ICAO Roster-Computer IT Engineer Expert</a></td>
        <td>Consultant</td><td>20345</td><td>Multiple</td><td>31/12/2027</td>
      </tr>
      <tr>
        <td><a href="https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions/job/10001">Human Resources Officer</a></td>
        <td>P</td><td>10001</td><td>Montreal</td><td>31/12/2027</td>
      </tr>
      <tr>
        <td><a href="https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions/job/10002">Software Engineer</a></td>
        <td>P</td><td>10002</td><td>Montreal</td><td>01/01/2020</td>
      </tr>
      <tr>
        <td><a href="https://example.com/job/99999">IT Engineer</a></td>
        <td>P</td><td>99999</td><td>Remote</td><td>31/12/2027</td>
      </tr>
    </table>
    """
    jobs = _icao_extract_jobs(html, today=date(2026, 10, 17))
    assert len(jobs) == 1
    assert jobs[0]["id"] == "20345"
    assert jobs[0]["location"] == "Multiple"
    assert jobs[0]["deadline"] == "2027-12-31"
    assert jobs[0]["job_type"] == "Roster / mission potentielle"



def test_icao_roster_four_column_table_does_not_treat_job_id_as_grade():
    html = """
    <table>
      <tr><th>Title</th><th>Job ID</th><th>Location</th><th>Deadline</th></tr>
      <tr>
        <td><a href="https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions/job/20345">ICAO Roster-Computer IT Engineer Expert</a></td>
        <td>20345</td><td>Multiple</td><td>31/12/2027</td>
      </tr>
    </table>
    """
    jobs = _icao_extract_jobs(html, today=date(2026, 10, 17))
    assert len(jobs) == 1
    assert jobs[0]["location"] == "Multiple"
    assert "Grade affiché" not in jobs[0]["description"]
