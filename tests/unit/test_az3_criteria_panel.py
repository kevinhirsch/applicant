"""AZ3 (#840) — the criteria panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/criteria.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestCriteriaPanel:
    """Source-level assertions for the criteria panel."""

    def test_list_campaigns_via_callJsonApi(self, html):
        assert 'callJsonApi("campaigns", { action: "list" }' in html

    def test_view_criteria_via_callJsonApi(self, html):
        assert 'callJsonApi("criteria", { action: "view", campaign_id:' in html

    def test_signature_via_callJsonApi(self, html):
        assert 'callJsonApi("criteria", { action: "signature", campaign_id:' in html

    def test_apply_learned_via_callJsonApi(self, html):
        assert 'action: "apply_learned"' in html

    def test_has_error_line(self, html):
        assert "fatalError" in html

    def test_empty_campaigns(self, html):
        assert "No campaigns" in html

    def test_empty_signature(self, html):
        assert "No converting-role signature data yet" in html

    # --- edit form (Kevin can change criteria and save them) --------------

    def test_edit_button_present(self, html):
        assert "startEditCriteria()" in html

    def test_edit_form_fields_bound(self, html):
        assert 'x-model="editForm.titles"' in html
        assert 'x-model="editForm.locations"' in html
        assert 'x-model="editForm.work_modes"' in html
        assert 'x-model="editForm.keywords"' in html
        assert 'x-model="editForm.salary_floor"' in html

    def test_save_and_cancel_buttons_present(self, html):
        assert "saveCriteria()" in html
        assert "cancelEditCriteria()" in html

    def test_save_uses_update_action(self, html):
        assert 'body = { action: "update", campaign_id: cid }' in html

    def test_save_diffs_before_sending(self, html):
        # Only changed fields should be forwarded, so an edit to one field doesn't
        # spuriously re-trigger the integral confirm gate on unrelated fields.
        assert "sameList(newTitles, d.titles)" in html
        assert "sameList(newKeywords, d.keywords)" in html

    def test_confirm_retry_on_409(self, html):
        assert "r.status === 409" in html
        assert "window.confirm(" in html

    def test_start_edit_prefills_from_criteria_data(self, html):
        assert "startEditCriteria() {" in html
        assert "this.editingCriteria = true;" in html
