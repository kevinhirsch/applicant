"""B-review-deep-link — the "Review" button must land the user directly on the
clicked application, not leave the picker at "Select an application…".

Entry points that deep-link into ``documents.html`` with a real
``?application_id=&campaign_id=`` query on the panel's OWN path (e.g. the
Pending-Reviews "Review" button on the landing page —
``a0-webui/components/welcome/welcome-screen.html``'s ``review()``, which
builds exactly ``/plugins/applicant/webui/documents.html?application_id=...``)
previously had nothing read that query at all. Only ``window.__applicantReview``
(set by ``digest.html`` right before ``window.openModal()``) drove any
auto-selection, and even that only fed the Review & Refine surface
(``rvApplicationId``) — never the Application ``<select>`` itself, so
"Documents" / "Résumé Variant Library" / "Submission Snapshot" / "JD Match"
never loaded either.

The panel is browser-rendered HTML/Alpine (full E2E belongs in the P0-6
Playwright harness), so — like ``test_rux_review_panel.py`` /
``test_az2_documents_panel.py`` for this same file — most of this is a
source-level contract pin. ``TestDeepLinkParserBehavior`` additionally drives
the extracted pure helper through real ``node`` execution (skips gracefully
when ``node`` isn't on PATH, mirroring ``workspace/tests/test_compare_js.py``).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PANEL = PROJECT_ROOT / "a0-applicant" / "webui" / "documents.html"
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _init_body(html: str) -> str:
    start = html.index("async init()")
    end = html.index("async onCampaignSelect()")
    assert start < end
    return html[start:end]


class TestDeepLinkParserDefined:
    def test_parse_helper_defined(self, html):
        assert "function parseReviewDeepLink(" in html

    def test_modal_path_reader_defined(self):
        pass  # see TestModalPathReader below (kept separate for clarity)


class TestModalPathReader:
    """modals.js stores the opened path as a plain JS property (``.path``) on
    the ``.modal`` ancestor it creates (see ``createModalElement``/``openModal``
    in ``agent-zero/webui/js/modals.js`` — that property assignment is NOT an
    HTML attribute, so a loaded fragment can only read it back off the live DOM
    element, never from ``window.location`` (the panel is fetched into a modal
    body, never navigated to)."""

    def test_reader_method_defined(self, html):
        assert "_rvModalPath()" in html

    def test_reader_climbs_to_the_modal_ancestor(self, html):
        assert '.closest(".modal")' in html

    def test_reader_reads_the_path_property(self, html):
        # modalEl.path -- the JS property modals.js assigns, not an attribute.
        assert "modalEl.path" in html

    def test_reader_falls_back_to_window_location_search(self, html):
        # Backward-compat / hypothetical non-modal full-page open.
        assert "window.location" in html and "search" in html


class TestDeepLinkWiredIntoContext:
    def test_read_context_calls_the_parser_with_the_modal_path(self, html):
        assert "parseReviewDeepLink(this._rvModalPath())" in html

    def test_application_id_prefers_handoff_then_falls_back_to_deep_link(self, html):
        # window.__applicantReview (ctx) still wins when present (digest.html's
        # flow); the query-param value is the fallback for entry points that
        # never set that global (welcome-screen.html's review()).
        #
        # Bug fix (P1, 404 "no such application"): this used to also fall back to
        # ctx.posting_id, silently handing a posting id off as an application id
        # whenever ctx.application_id was absent (digest.html's flow, before its own
        # fix, left application_id unset on every pre-application posting). That
        # fallback is gone -- digest.html's Review button now always drafts a real
        # application first, so ctx.application_id is always genuine here.
        assert re.search(
            r"this\.rvApplicationId\s*=\s*ctx\.application_id\s*\|\|\s*deep\.application_id\s*\|\|\s*\"\"",
            html,
        ), "rvApplicationId must fall back to the deep-linked application_id"
        assert not re.search(
            r"this\.rvApplicationId\s*=\s*ctx\.application_id\s*\|\|\s*ctx\.posting_id",
            html,
        ), "rvApplicationId must never fall back to ctx.posting_id (that 404s)"

    def test_campaign_id_falls_back_to_deep_link(self, html):
        assert re.search(
            r"this\.rvCampaignId\s*=\s*ctx\.campaign_id\s*\|\|\s*deep\.campaign_id\s*\|\|\s*\"__system__\"",
            html,
        ), "rvCampaignId must fall back to the deep-linked campaign_id"

    def test_handoff_global_not_removed(self, html):
        # Regression guard: the digest.html flow must keep working.
        assert "window.__applicantReview" in html


class TestAutoSelectOnInit:
    """init() must not just populate rvApplicationId (drives the Review &
    Refine surface) -- it must also select the Application <select> and load
    the rest of the panel, exactly as picking it by hand would."""

    def test_init_guards_on_actual_membership_before_selecting(self, html):
        # Never blindly assign a deep-linked id the loaded campaign doesn't
        # actually contain -- that would fire loads for a nonexistent pairing
        # and leave the UI in a half-selected state.
        body = _init_body(html)
        assert "this.applications.some(" in body

    def test_init_sets_selected_application_id_from_the_deep_link(self, html):
        body = _init_body(html)
        assert "this.selectedApplicationId = this.rvApplicationId" in body

    def test_init_loads_documents_snapshot_and_jd_match_on_auto_select(self, html):
        # Mirrors what onApplicationSelect() does for a manual pick.
        body = _init_body(html)
        assert "this.loadDocuments()" in body
        assert "this.loadSnapshot()" in body
        assert "this.loadJdMatch()" in body

    def test_review_still_loads_for_a_deep_linked_application(self, html):
        # RUX sections (rvSections, /api/review/{id}/sections) must still
        # populate once an application is auto-selected.
        body = _init_body(html)
        assert "await this.loadReview();" in body


class TestDeepLinkParserBehavior:
    """Real JS execution of the extracted pure helper (skips without node)."""

    @staticmethod
    def _extract_parser(src: str) -> str:
        marker = "function parseReviewDeepLink("
        start = src.index(marker)
        brace_open = src.index("{", start)
        depth = 0
        for i in range(brace_open, len(src)):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    return src[start : i + 1]
        raise AssertionError("unbalanced braces while extracting parseReviewDeepLink")

    def _run(self, html: str, call: str) -> dict:
        fn_src = self._extract_parser(html)
        script = textwrap.dedent(
            f"""
            {fn_src}
            console.log(JSON.stringify({call}));
            """
        )
        res = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            timeout=15,
            text=True,
        )
        if res.returncode != 0:
            raise AssertionError(f"node failed:\n{res.stderr}")
        lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
        if not lines:
            raise AssertionError("node produced no stdout")
        return json.loads(lines[-1])

    def test_extracts_application_id_from_a_full_deep_link_path(self, html, node_available):
        out = self._run(
            html,
            'parseReviewDeepLink("/plugins/applicant/webui/documents.html?application_id=abc123")',
        )
        assert out == {"application_id": "abc123", "campaign_id": ""}

    def test_extracts_both_application_id_and_campaign_id(self, html, node_available):
        out = self._run(
            html,
            'parseReviewDeepLink("/plugins/applicant/webui/documents.html?application_id=abc123&campaign_id=camp-1")',
        )
        assert out == {"application_id": "abc123", "campaign_id": "camp-1"}

    def test_url_decodes_encoded_values(self, html, node_available):
        out = self._run(
            html,
            'parseReviewDeepLink("/x.html?application_id=" + encodeURIComponent("a b/c"))',
        )
        assert out["application_id"] == "a b/c"

    def test_no_query_returns_empty_strings(self, html, node_available):
        out = self._run(
            html, 'parseReviewDeepLink("/plugins/applicant/webui/documents.html")'
        )
        assert out == {"application_id": "", "campaign_id": ""}

    def test_strips_a_trailing_hash_fragment(self, html, node_available):
        out = self._run(
            html, 'parseReviewDeepLink("/x.html?application_id=abc123#section-2")'
        )
        assert out == {"application_id": "abc123", "campaign_id": ""}

    def test_handles_blank_and_null_path(self, html, node_available):
        assert self._run(html, 'parseReviewDeepLink("")') == {
            "application_id": "",
            "campaign_id": "",
        }
        assert self._run(html, "parseReviewDeepLink(null)") == {
            "application_id": "",
            "campaign_id": "",
        }
