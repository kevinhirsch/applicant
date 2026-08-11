"""AZ2 (#842) — the vault panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/vault.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestVaultPanel:
    """Source-level assertions for the vault panel."""

    def test_drives_the_engine_through_vault_proxy(self, html):
        assert 'callJsonApi("vault", {' in html and 'action: "list"' in html

    def test_add_form_present(self, html):
        assert 'action: "add"' in html and 'tenant_key' in html and 'secret' in html

    def test_campaign_picker_present(self, html):
        assert 'callJsonApi("campaigns",' in html and 'action: "list"' in html

    def test_empty_state_present(self, html):
        assert 'No saved sign-ins' in html or 'empty' in html.lower()

    def test_error_line_present(self, html):
        assert 'fatalError' in html or 'Couldn\'t reach the vault' in html
