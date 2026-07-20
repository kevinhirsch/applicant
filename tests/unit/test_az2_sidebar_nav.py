"""AZ2 sidebar — the applicant-panel launcher contract (source assertions).

The sidebar x-extension is static HTML rendered by the WebUI; we pin the
load-bearing contract at the source level, like the repo's other JS/HTML gates.
"""
from pathlib import Path

import pytest

PANEL = (
    Path(__file__).resolve().parents[2]
    / "a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html"
)


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestSidebarLauncher:
    """The x-extension must launch all three applicant panels via the working
    global window.openModal, and must NOT use the dead $store.app.showPanel."""

    def test_no_dead_show_panel(self, html):
        """Regression pin: the bug is that showPanel does not exist in A0's webui."""
        assert "showPanel" not in html

    def test_opens_main_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/main.html')" in html

    def test_opens_today_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/today.html')" in html

    def test_opens_update_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/update.html')" in html

    def test_has_setup_label(self, html):
        assert "Setup" in html

    def test_has_today_label(self, html):
        assert "Today" in html

    def test_has_update_label(self, html):
        assert "Update" in html

    def test_opens_campaigns_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/campaigns.html')" in html

    def test_has_campaigns_label(self, html):
        assert "Campaigns" in html

    def test_opens_activity_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/activity.html')" in html

    def test_has_activity_label(self, html):
        assert "Activity" in html

    def test_opens_attributes_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/attributes.html')" in html

    def test_has_profile_label(self, html):
        assert "Profile" in html

    def test_opens_notifications_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/notifications.html')" in html

    def test_has_notifications_label(self, html):
        assert "Notifications" in html

    def test_opens_digest_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/digest.html')" in html

    def test_has_digest_label(self, html):
        assert "Digest" in html

    def test_opens_health_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/health.html')" in html

    def test_has_health_label(self, html):
        assert "Health" in html
