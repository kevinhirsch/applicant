"""Model-endpoints panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/model_endpoints.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestModelEndpointsPanel:
    """Source-level assertions for the model_endpoints panel."""

    def test_drives_the_engine_through_model_endpoints_proxy(self, html):
        assert 'callJsonApi("model_endpoints", {' in html and 'action: "list"' in html

    def test_add_form_present(self, html):
        assert 'action: "add"' in html and 'base_url' in html and 'api_key' in html

    def test_test_button_wired(self, html):
        assert '@click="testEndpoint' in html or 'testEndpoint(' in html

    def test_remove_button_wired(self, html):
        assert '@click="removeEndpoint' in html or 'removeEndpoint(' in html

    def test_models_button_wired(self, html):
        assert '@click="loadModels' in html or 'loadModels(' in html

    def test_empty_state_present(self, html):
        assert 'No endpoints yet' in html

    def test_error_line_present(self, html):
        assert 'fatalError' in html or "Couldn't reach the model endpoints engine" in html

    def test_loading_spinner_present(self, html):
        assert 'spinner' in html

    def test_campaign_picker_present(self, html):
        assert 'callJsonApi("campaigns",' in html and 'action: "list"' in html
