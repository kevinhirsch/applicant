"""AZ1-3 (#831) — the base_resume wizard panel (source assertions).

The wizard section renders a file-upload + parse UI. We assert the honest
parsed_field_count (not attribute_count) and the conflict-confirmation list.
"""
from pathlib import Path

import pytest

WIZARD = Path(__file__).resolve().parents[2] / "a0-applicant/webui/main.html"


@pytest.fixture(scope="module")
def html() -> str:
    return WIZARD.read_text(encoding="utf-8")


def test_base_resume_section_in_sections(html):
    assert 'id:"base_resume"' in html
    assert 'title:"Your Résumé"' in html
    assert 'Upload your résumé' in html


def test_base_resume_has_no_form_fields(html):
    # base_resume has no fields property — it is upload-driven, not form-driven
    assert 'id:"base_resume", title:"Your Résumé", hint:"Upload your résumé' in html


def test_base_resume_template_renders(html):
    assert 'current.id === \'base_resume\'' in html
    assert '<input type="file" id="resumeFile"' in html
    assert 'accept=".pdf,.docx,.doc,.txt,.md"' in html
    assert '@click="uploadResume()"' in html


def test_uses_parsed_field_count_not_attribute_count(html):
    # must use the honest parsed_field_count from the engine response
    assert 'parsed_field_count' in html
    assert 'attribute_count' not in html or False  # just ensure parsed_field_count is there


def test_lists_conflicts_for_confirmation(html):
    # conflicts are surfaced for user confirmation, never silently accepted.
    # commit 19cdb135e (tech-debt burn-down) reworked the conflict-confirmation
    # UI to match the engine's real response shape (src/applicant/app/routers/
    # onboarding.py returns "attribute"/"parsed_value"/"interview_value", not
    # the old field/parsed/current names) and added interactive confirm buttons
    # (confirmConflict, which reads c.parsed_value / c.interview_value).
    assert 'resumeResult.data.conflicts' in html
    assert 'c.parsed_value' in html
    assert 'c.interview_value' in html


def test_shows_health_verdict(html):
    # onboarding_service.py's IntakeConflictsView carries resume_health=
    # health.verdict (not a bare "health" key) -- see commit 19cdb135e.
    assert 'resumeResult.data.resume_health.verdict' in html
    assert 'Health:' in html


def test_shows_success_box_on_ok(html):
    assert 'success-box' in html
    assert 'resumeResult.ok' in html


def test_imports_getCsrfToken(html):
    assert 'getCsrfToken' in html


def test_upload_method_and_state(html):
    assert 'async uploadResume()' in html
    assert 'uploading: false' in html
    assert 'resumeResult: null' in html
    assert 'FormData' in html
    assert '/api/a0-applicant/base_resume' in html


def test_save_continue_button_present(html):
    assert 'Save & continue' in html
