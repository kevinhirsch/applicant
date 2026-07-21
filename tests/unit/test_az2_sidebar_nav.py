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

    def test_opens_mind_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/mind.html')" in html

    def test_has_mind_label(self, html):
        assert "Mind" in html

    def test_opens_gallery_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/gallery.html')" in html

    def test_has_gallery_label(self, html):
        assert "Gallery" in html

    def test_opens_criteria_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/criteria.html')" in html

    def test_has_criteria_label(self, html):
        assert "Criteria" in html

    def test_opens_compare_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/compare.html')" in html

    def test_has_compare_label(self, html):
        assert "Compare" in html

    def test_opens_fonts_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/fonts.html')" in html

    def test_has_fonts_label(self, html):
        assert "Fonts" in html

    def test_opens_discovery_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/discovery.html')" in html

    def test_has_discovery_label(self, html):
        assert "Discovery" in html

    def test_opens_tracker_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/tracker.html')" in html

    def test_has_tracker_label(self, html):
        assert "Tracker" in html

    def test_opens_research_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/research.html')" in html

    def test_has_research_label(self, html):
        assert "Research" in html

    def test_opens_feedback_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/feedback.html')" in html

    def test_has_feedback_label(self, html):
        assert "Feedback" in html

    def test_opens_chat_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/chat.html')" in html

    def test_has_chat_label(self, html):
        assert "Chat" in html

    def test_opens_documents_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/documents.html')" in html

    def test_has_documents_label(self, html):
        assert "Documents" in html

    def test_opens_takeover_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/takeover.html')" in html

    def test_has_takeover_label(self, html):
        assert "Live session" in html

    def test_opens_ops_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/ops.html')" in html

    def test_has_ops_label(self, html):
        assert "Ops" in html

    def test_opens_channels_panel(self, html):
        assert "window.openModal('/plugins/applicant/webui/channels.html')" in html

    def test_has_channels_label(self, html):
        assert "Channels" in html
