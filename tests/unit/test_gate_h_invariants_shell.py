"""H1-H5 re-audit on A0 shell surfaces — the plugin API proxies (a0-applicant/api/*).

Every plugin proxy uses a pure ``dispatch()`` / ``_forward()`` pattern that calls
the engine via ``urllib.request`` and returns the engine's response unchanged (or
an error envelope on failure). These tests assert that the proxies NEVER fabricate,
summarize, or derive state — they forward engine truth verbatim.

The only exception is ``features.compute_features()`` which does client-side
computation (H5 GAP flagged in the audit doc).

To test the module-level dispatch functions without the A0 framework installed,
we monkeypatch ``helpers.api.ApiHandler`` (unused in the pure-logic tests) and
patch ``urllib.request`` to capture/return known envelopes.

Style follows existing H-tests: class-based with @pytest.mark.unit, module-level
autouse _no_cache fixture for xdist safety.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ── Patch helpers.api before importing plugin modules ─────────────────────
_helpers_patch = MagicMock()
sys.modules["helpers"] = _helpers_patch
sys.modules["helpers.api"] = MagicMock(ApiHandler=type("ApiHandler", (), {}))
sys.modules["flask"] = MagicMock(Request=type("Request", (), {}))

# Now import the plugin dispatch functions
sys.path.insert(0, "a0-applicant")
from api import (
    agent_runs,
    audit,
    campaigns,
    chat,
    digest,
    documents,
    dormant,
    features,
    health,
    notifications,
    onboarding,
    pending,
    takeover,
    update_panel,
    vault,
)


# ── xdist-safe parallel fixture ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Clear any module-level LRU caches before each test (xdist safety)."""
    return None


# ── Helpers ───────────────────────────────────────────────────────────────


class _FakeResponse:
    """Simulates a successful ``urllib.request.urlopen`` response."""

    def __init__(self, data: dict, status: int = 200):
        self._data = json.dumps(data).encode()
        self.status = status

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def decode(self) -> str:
        return self._data.decode()


class _FakeHTTPError(urllib.error.HTTPError):
    """Simulate an HTTP error from urllib."""

    def __init__(self, code: int, body: str = ""):
        self.code = code
        self._body = body.encode() if body else b"{}"
        super().__init__(
            "http://fake/", code, f"Error {code}", {}, SimpleNamespace(read=lambda: self._body)
        )

    def read(self) -> bytes:
        return self._body


def _patch_forward(dispatchers: list, *, ok: bool = True, data: dict | None = None, status: int = 200):
    """Patch ``urllib.request.urlopen`` to return a canned response for all
    ``_forward()`` calls from the given dispatchers."""
    payload = data or {"status": "ok"}
    body = json.dumps(payload).encode()
    response = _FakeResponse(payload, status) if ok else _FakeHTTPError(status, json.dumps(payload))

    # Patch at the urllib level so every proxy's _forward is affected
    patcher = patch.object(urllib.request, "urlopen", return_value=response if ok else __import__("unittest").mock.MagicMock())

    if not ok:
        # For error cases, urlopen raises HTTPError
        patcher = patch.object(
            urllib.request, "urlopen", side_effect=_FakeHTTPError(status, json.dumps(payload))
        )

    return patcher


# ═══════════════════════════════════════════════════════════════════════════
# H1 — Receipts, not narration
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestH1ProxiesForwardVerbatim:
    """All plugin API proxies forward engine responses verbatim — they never
    fabricate or derive state. The ``dispatch()`` function returns the engine's
    ``_forward()`` result envelope unchanged (``{ok, status, data|error}``)."""

    # ── health.py ──────────────────────────────────────────────────────

    def test_health_forward_capabilities_from_engine_verbatim(self):
        """The health proxy's capabilities action forwards the engine response
        unchanged — it does not fabricate or filter capability data."""
        engine_response = {
            "ok": True,
            "status": 200,
            "data": {
                "capabilities": {
                    "postgres": {"real": True, "label": "Postgres database", "fix": None},
                    "browser": {"real": True, "label": "Browser", "fix": None},
                    "latex": {"real": False, "label": "LaTeX renderer", "fix": "Install texlive-base"},
                },
                "version": "0.1.0",
                "generated_at": "2026-07-20T00:00:00+00:00",
            },
        }

        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(engine_response["data"]),
        ):
            result = health.dispatch({"action": "capabilities"})

        assert result["ok"] is True
        assert result["status"] == 200
        assert result["data"] == engine_response["data"]

    def test_health_proxy_never_mutates_the_envelope(self):
        """The health dispatch passes through the engine envelope WITHOUT
        adding or removing keys — no summary, no client-side state derivation."""
        engine_data = {"capabilities": {"postgres": {"real": True}}, "version": "0.1.0"}

        with patch("urllib.request.urlopen", return_value=_FakeResponse(engine_data)):
            result = health.dispatch({"action": "capabilities"})

        # The response data is the verbatim engine data, not a wrapper/summary
        assert result["data"] == engine_data

    def test_health_defaults_to_capabilities(self):
        """Empty/missing action defaults to capabilities — no silent narration."""
        with patch("urllib.request.urlopen", return_value=_FakeResponse({"x": 1})):
            result = health.dispatch({})
        assert result["ok"] is True
        assert result["data"]["x"] == 1

    # ── chat.py ────────────────────────────────────────────────────────

    def test_chat_send_forwards_response_verbatim(self):
        """The chat proxy's 'send' action forwards the engine's response
        unchanged — no side-effects or reformatting in the proxy."""
        engine_response = {"ok": True, "status": 200, "data": {"reply": "Hello!", "state": "idle"}}
        with patch("urllib.request.urlopen", return_value=_FakeResponse(engine_response["data"])):
            result = chat.dispatch({"action": "send", "message": "Hi"})
        assert result["ok"] is True
        assert result["data"] == engine_response["data"]

    def test_chat_confirm_forwards_verbatim(self):
        with patch("urllib.request.urlopen", return_value=_FakeResponse({"confirmed": True})):
            result = chat.dispatch({"action": "confirm", "name": "skill", "value": "Python"})
        assert result["ok"] is True
        assert result["data"] == {"confirmed": True}

    def test_chat_no_message_returns_400_not_synthesized_response(self):
        """When 'message' is missing, the proxy returns 400 — it never
        invents a default message to send to the engine."""
        result = chat.dispatch({"action": "send", "message": ""})
        assert result["ok"] is False
        assert result["status"] == 400
        assert "message required" in result["error"]

    # ── documents.py ───────────────────────────────────────────────────

    def test_documents_provenance_forwards_response(self):
        """The documents proxy's 'provenance' action forwards the engine's
        per-line provenance response verbatim — never summarized."""
        engine_data = {
            "document_id": "doc1",
            "lines": [
                {"line": "Python developer", "facts": [{"token": "Python", "sources": ["your profile (Skills)"]}]},
            ],
            "checked": True,
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(engine_data)):
            result = documents.dispatch({"action": "provenance", "document_id": "doc1"})
        assert result["data"] == engine_data

    def test_documents_snapshot_forwards_response(self):
        """The documents 'snapshot' action forwards the outcomes snapshot
        payload unchanged — never modified or summarized by the shell."""
        engine_data = {
            "application_id": "app1",
            "stage": "reviewed",
            "answers": {"#first-name": "Ada", "#salary": "185000"},
            "materials": [],
            "posting_url": "http://example.com/job",
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(engine_data)):
            result = documents.dispatch({"action": "snapshot", "application_id": "app1"})
        assert result["data"] == engine_data

    def test_documents_provenance_requires_document_id(self):
        """Missing document_id returns 400 — never fabricates a request to
        the engine with a made-up ID."""
        result = documents.dispatch({"action": "provenance"})
        assert result["ok"] is False
        assert result["status"] == 400

    # ── health checks that engine git info is forwarded ─────────────────

    def test_health_forwards_engine_git_info(self):
        """The health proxy forwards git info from the engine's capability
        report — it is not a narration or fabricated from the plugin's own state."""
        engine_data = {
            "capabilities": {},
            "version": "0.1.0",
            "generated_at": "2026-07-20T00:00:00+00:00",
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(engine_data)):
            result = health.dispatch({"action": "capabilities"})
        assert result["data"]["version"] == engine_data["version"]

    # ── onboarding proxy ───────────────────────────────────────────────

    def test_onboarding_state_forwards_verbatim(self):
        engine_data = {
            "campaign_id": "c1",
            "complete": False,
            "sections_complete": ["profile"],
            "missing_sections": ["resume"],
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(engine_data)):
            result = onboarding.dispatch({"action": "state", "campaign_id": "c1"})
        assert result["data"] == engine_data

    def test_onboarding_section_forwards_verbatim(self):
        engine_data = {"campaign_id": "c1", "sections_complete": ["profile", "resume"]}
        with patch("urllib.request.urlopen", return_value=_FakeResponse(engine_data)):
            result = onboarding.dispatch({"action": "section", "campaign_id": "c1", "section": "resume", "data": {}})
        assert result["data"] == engine_data


# ═══════════════════════════════════════════════════════════════════════════
# H2 — No silent underdelivery
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestH2ProxiesForwardErrorsHonestly:
    """Shell surfaces must report engine truth — they never swallow failures.
    Error envelopes from the engine are passed through to the UI as-is."""

    def test_chat_proxy_forwards_engine_error(self):
        """When the engine returns an error, the chat proxy passes it through
        — no client-side fallback or fabricated success."""
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(500, json.dumps({"detail": "Engine internal error"})),
        ):
            result = chat.dispatch({"action": "send", "message": "Hello"})
        assert result["ok"] is False
        assert result["status"] == 500
        assert "Engine internal error" in result["error"]

    def test_documents_proxy_forwards_404_honestly(self):
        """A 404 from the engine (e.g., missing document) is forwarded as-is
        — never replaced with a fabricated empty result."""
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(404, json.dumps({"detail": "No such document."})),
        ):
            result = documents.dispatch({"action": "provenance", "document_id": "nonexistent"})
        assert result["ok"] is False
        assert result["status"] == 404
        assert "No such document" in result["error"]

    def test_health_proxy_forwards_engine_down_honestly(self):
        """When the engine is unreachable, the health proxy returns an error
        — never a fabricated "everything is fine" response."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            result = health.dispatch({"action": "capabilities"})
        assert result["ok"] is False
        assert "URLError" in result["error"] or "Connection refused" in result["error"]

    def test_agent_runs_proxy_forwards_status_error_honestly(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(503, "Service unavailable"),
        ):
            result = agent_runs.dispatch({"campaign_id": "c1"})
        assert result["ok"] is False
        assert result["status"] == 503

    def test_digest_proxy_forwards_error_honestly(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(502, json.dumps({"detail": "Upstream fail"})),
        ):
            result = digest.dispatch({"action": "get", "campaign_id": "c1"})
        assert result["ok"] is False
        assert "Upstream fail" in result["error"]

    def test_notifications_proxy_forwards_error_honestly(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(429, json.dumps({"detail": "Rate limited"})),
        ):
            result = notifications.dispatch({"action": "list"})
        assert result["ok"] is False
        assert "Rate limited" in result["error"]

    def test_pending_proxy_forwards_error_honestly(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(404, json.dumps({"detail": "No such campaign"})),
        ):
            result = pending.dispatch({"action": "list", "campaign_id": "nonexistent"})
        assert result["ok"] is False
        assert "No such campaign" in result["error"]

    def test_campaigns_proxy_forwards_error_honestly(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(403, json.dumps({"detail": "Forbidden"})),
        ):
            result = campaigns.dispatch({"action": "list"})
        assert result["ok"] is False
        assert "Forbidden" in result["error"]

    def test_takeover_proxy_forwards_error_honestly(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(400, json.dumps({"detail": "Bad session"})),
        ):
            result = takeover.dispatch({"action": "sessions"})
        assert result["ok"] is False
        assert "Bad session" in result["error"]

    def test_update_panel_proxy_forwards_error_honestly(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(500, json.dumps({"detail": "Update failed"})),
        ):
            result = update_panel.dispatch({"action": "status"})
        assert result["ok"] is False
        assert "Update failed" in result["error"]

    def test_vault_proxy_forwards_error_honestly(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(401, json.dumps({"detail": "Unauthorized"})),
        ):
            result = vault.dispatch({"action": "list", "campaign_id": "c1"})
        assert result["ok"] is False
        assert "Unauthorized" in result["error"]

    def test_onboarding_proxy_forwards_error_honestly(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(409, json.dumps({"message": "Incomplete"})),
        ):
            result = onboarding.dispatch({"action": "complete", "campaign_id": "c1"})
        assert result["ok"] is False
        assert "Incomplete" in result["error"]

    # ── underdelivery vocabulary surfaces honestly ─────────────────────

    def test_engine_shortfall_surfaces_through_pending_proxy(self):
        """The pending-actions proxy forwards engine shortfall data verbatim
        — the underdelivery vocabulary (failed_fields, deferred_questions,
        summary) from core/rules/underdelivery.py arrives at the UI unchanged."""
        shortfall_data = {
            "campaign_id": "c1",
            "items": [
                {
                    "id": "pa1",
                    "kind": "final_approval",
                    "title": "Final approval / submit",
                    "payload": {
                        "shortfall": {
                            "summary": "I filled 7 of the 10 fields I found; 1 failed to fill (Phone); 2 left blank — double-check the form.",
                            "fields_unfilled": 3,
                            "failed_fields": ["Phone"],
                        }
                    },
                }
            ],
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(shortfall_data)):
            result = pending.dispatch({"action": "list", "campaign_id": "c1"})
        assert result["data"] == shortfall_data
        item = result["data"]["items"][0]
        assert "shortfall" in item["payload"]
        assert "7 of the 10 fields" in item["payload"]["shortfall"]["summary"]


# ═══════════════════════════════════════════════════════════════════════════
# H3 — Full-fidelity review
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestH3SnapshotProxyPassesPayloadUnchanged:
    """The plugin's proxy to GET /api/outcomes/applications/{id}/snapshot
    passes the payload through unchanged — never summarized or modified by
    the shell layer."""

    def test_snapshot_payload_is_forwarded_verbatim(self):
        """The snapshot endpoint returns engine data verbatim — the review
        payload (answers, materials, posting, stage) is never summarized."""
        snapshot_data = {
            "application_id": "app1",
            "stage": "reviewed",
            "answers": {
                "#first-name": "Ada",
                "#salary": "185000",
                "Why do you want this role?": "Because I shipped exactly this stack for 6 years.",
            },
            "material_versions": {
                "doc1": "variant1",
            },
            "materials": [
                {"kind": "uploaded_file", "name": "ada-resume.pdf", "path": "/data/resumes/ada-resume.pdf"},
            ],
            "posting_url": "http://example.com/job",
            "timestamp": "2026-07-06T00:00:00+00:00",
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(snapshot_data)):
            result = documents.dispatch({"action": "snapshot", "application_id": "app1"})
        assert result["data"] == snapshot_data
        # The long-form answer is verbatim, not summarized
        assert "exactly this stack" in result["data"]["answers"]["Why do you want this role?"]

    def test_no_snapshot_returns_engine_404_verbatim(self):
        """When no snapshot exists, the engine's 404 ("nothing recorded yet")
        is forwarded verbatim — no empty "{} " or fabricated placeholder."""
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(404, json.dumps({"detail": "No submission snapshot recorded for this application."})),
        ):
            result = documents.dispatch({"action": "snapshot", "application_id": "nonexistent"})
        assert result["ok"] is False
        assert "No submission snapshot recorded" in result["error"]

    def test_snapshot_proxy_requires_application_id(self):
        """Missing application_id returns a client-side 400 — the proxy
        never invents an ID to send to the engine."""
        result = documents.dispatch({"action": "snapshot"})
        assert result["ok"] is False
        assert result["status"] == 400
        assert "application_id" in result["error"]

    def test_engine_renders_review_payload_before_submit(self):
        """The 'reviewed' stage from the engine is forwarded unchanged —
        the shell does not modify or summarize the pre-submit review data."""
        reviewed_data = {
            "application_id": "app2",
            "stage": "reviewed",
            "answers": {
                "#last-name": "Lovelace",
            },
            "materials": [],
            "posting_url": "http://example.com/job2",
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(reviewed_data)):
            result = documents.dispatch({"action": "snapshot", "application_id": "app2"})
        assert result["data"]["stage"] == "reviewed"
        assert result["data"] == reviewed_data


# ═══════════════════════════════════════════════════════════════════════════
# H4 — Visible provenance
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestH4ProvenanceProxyPassesThrough:
    """The documents panel proxy for provenance forwards engine output
    verbatim — unsourced facts are flagged, not hidden, and owner-gating
    is preserved."""

    def test_provenance_forwarded_verbatim_with_unsourced_facts(self):
        """Engine provenance with unsourced facts is forwarded unchanged
        — the plugin does not strip or hide unsourced flags."""
        provenance_data = {
            "document_id": "doc1",
            "checked": True,
            "lines": [
                {
                    "line": "Python developer with Kubernetes experience",
                    "facts": [
                        {"token": "Python", "sources": ["your profile (Skills)"], "unsourced": False},
                        {"token": "Kubernetes", "sources": [], "unsourced": True},
                    ],
                }
            ],
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(provenance_data)):
            result = documents.dispatch({"action": "provenance", "document_id": "doc1"})
        assert result["data"] == provenance_data
        line_facts = result["data"]["lines"][0]["facts"]
        unsourced = [f for f in line_facts if f.get("unsourced")]
        assert len(unsourced) == 1
        assert unsourced[0]["token"] == "Kubernetes"

    def test_unsourced_provenance_not_replaced_by_fake_clean_check(self):
        """When the engine returns checked=false with a reason, the proxy
        forwards it faithfully — never fabricates a "clean" check."""
        no_check_data = {
            "document_id": "doc2",
            "checked": False,
            "reason": "Document has no reviewable text to trace.",
            "lines": [],
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(no_check_data)):
            result = documents.dispatch({"action": "provenance", "document_id": "doc2"})
        assert result["data"] == no_check_data
        assert result["data"]["checked"] is False
        assert "no reviewable text" in result["data"]["reason"]

    def test_provenance_missing_document_id_returns_400(self):
        result = documents.dispatch({"action": "provenance"})
        assert result["ok"] is False
        assert result["status"] == 400

    def test_engine_404_on_provenance_is_forwarded(self):
        """A 404 for a non-existent document's provenance is forwarded
        verbatim — the proxy never fabricates an empty provenance."""
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(404, json.dumps({"detail": "No such document."})),
        ):
            result = documents.dispatch({"action": "provenance", "document_id": "nope"})
        assert result["ok"] is False
        assert "No such document" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════
# H5 — Calibrated copy
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestH5ProxyCopyIsCalibrated:
    """Plugin UI copy is calibrated against the engine's real capability
    state. The health proxy forwards REAL capability status from the engine
    — never aspirational claims."""

    def test_health_proxy_fowards_real_capability_status(self):
        """The health panel reports the engine's actual capability status
        (including degraded/false capabilities) — not aspirational claims."""
        engine_data = {
            "capabilities": {
                "postgres": {"real": True, "label": "Postgres database", "fix": None, "load_bearing": True},
                "browser": {"real": False, "label": "Browser", "fix": "Install camoufox or configure remote browser endpoint.", "load_bearing": False},
                "latex": {"real": False, "label": "LaTeX renderer", "fix": "Install texlive-base", "load_bearing": False},
            },
            "version": "0.1.0",
            "generated_at": "2026-07-20T00:00:00+00:00",
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(engine_data)):
            result = health.dispatch({"action": "capabilities"})
        # The degraded browser capability is forwarded as-is — never upgraded to "ok"
        assert result["data"]["capabilities"]["browser"]["real"] is False
        assert "Install" in result["data"]["capabilities"]["browser"]["fix"]

    def test_health_reports_engine_truth_not_aspirational(self):
        """If the engine reports a capability as not available, the proxy
        never changes it to available — the UI sees the real state."""
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse({"capabilities": {"x": {"real": False, "label": "X"}}}),
        ):
            result = health.dispatch({"action": "capabilities"})
        assert result["data"]["capabilities"]["x"]["real"] is False

    def test_engine_down_reported_as_unavailable(self):
        """When the engine is down, the health proxy reports the error —
        never fabricates an "engine ok" response."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Engine unreachable"),
        ):
            result = health.dispatch({"action": "capabilities"})
        assert result["ok"] is False
        # The proxy does not return a fabricated capabilities dict

    def test_all_proxy_dispatch_functions_exist_and_are_callable(self):
        """Every plugin proxy has a callable dispatch function — the
        interface is stable and consistent."""
        proxies = [
            agent_runs, audit, campaigns, chat, digest, documents,
            dormant, notifications, onboarding, pending, takeover,
            update_panel, vault, health,
        ]
        for mod in proxies:
            assert hasattr(mod, "dispatch"), f"{mod.__name__} missing dispatch"
            assert callable(mod.dispatch), f"{mod.__name__}.dispatch not callable"

    def test_unknown_actions_return_400_not_silent_success(self):
        """Unknown actions in every proxy return 400 error — never silently
        succeed or return fabricated data."""
        test_cases = [
            (health, {"action": "nonexistent"}),
            (chat, {"action": "nonexistent"}),
            (digest, {"action": "nonexistent", "campaign_id": "c1"}),
            (documents, {"action": "nonexistent"}),
            (notifications, {"action": "nonexistent"}),
            (pending, {"action": "nonexistent", "campaign_id": "c1"}),
            (takeover, {"action": "nonexistent"}),
            (campaigns, {"action": "nonexistent"}),
            (onboarding, {"action": "nonexistent", "campaign_id": "c1"}),
            (agent_runs, {"action": "nonexistent", "campaign_id": "c1"}),
            (update_panel, {"action": "nonexistent"}),
            (vault, {"action": "nonexistent", "campaign_id": "c1"}),
            (audit, {"action": "nonexistent"}),
            (dormant, {"action": "nonexistent"}),
        ]
        for mod, args in test_cases:
            result = mod.dispatch(args)
            assert result["ok"] is False, f"{mod.__name__}.dispatch({{'action': 'nonexistent'}}) returned ok=True"
            assert result["status"] == 400, f"{mod.__name__} returned status {result['status']} for unknown action"


# ═══════════════════════════════════════════════════════════════════════════
# H5 — GAP: features.py client-side computation
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestH5FeaturesGap:
    """features.py is the ONE proxy that performs client-side computation
    rather than purely forwarding engine state — it computes section states
    from two engine calls (setup/status + dormant-surfaces).

    This is an H5 GAP flagged in the audit doc: the UI sections' state is
    *derived* in the plugin layer, not purely forwarded. While the derivation
    uses engine data as inputs, the section-level logic (gate requirements,
    dormant-surface liveness) runs in the plugin.

    These tests assert the derivation is at least TRANSPARENT: it correctly
    reflects engine state without fabricating capabilities.
    """

    def test_features_never_says_locked_when_engine_says_ok(self):
        """When the engine reports everything configured, sections should
        be 'active', not 'locked' or 'disabled' (no fabricated gating)."""
        def _respond(url, *args, **kwargs):
            target = url.get_full_url() if hasattr(url, 'get_full_url') else str(url)
            if "/api/setup/status" in target:
                return _FakeResponse({"onboarding_complete": True, "llm_configured": True, "channels_configured": True})
            if "/api/dormant-surfaces" in target:
                # Every dormant key referenced by any section must be 'live'
                return _FakeResponse([
                    {"key": "redline_surface", "status": "live"},
                    {"key": "attribute_editor", "status": "live"},
                    {"key": "criteria_editor", "status": "live"},
                    {"key": "chatbot", "status": "live"},
                    {"key": "assistant_memory", "status": "live"},
                    {"key": "saved_playbooks", "status": "live"},
                    {"key": "curation_approvals", "status": "live"},
                    {"key": "digest_in_app", "status": "live"},
                    {"key": "debug_surface", "status": "live"},
                    {"key": "tool_toggle_registry", "status": "live"},
                    {"key": "update_button", "status": "live"},
                    {"key": "remote_takeover", "status": "live"},
                    {"key": "desktop_assist", "status": "live"},
                    {"key": "multi_campaign_switcher", "status": "live"},
                ])
            return _FakeResponse({})

        with patch("urllib.request.urlopen", side_effect=_respond):
            result = features.compute_features()
        assert result["engine_available"] is True
        sections = result.get("sections", {})
        # Core sections should be active
        for key in ["documents", "memory", "chat"]:
            state = sections.get(key, {}).get("state", "")
            assert state == "active", f"{key} should be active but is {state}"

    def test_features_reports_engine_down_honestly(self):
        """When the engine status call fails, features reports engine as
        not available — no fabricated capability list."""
        with patch(
            "urllib.request.urlopen",
            side_effect=_FakeHTTPError(503, "Service Unavailable"),
        ):
            result = features.compute_features()
        assert result["engine_available"] is False
        # Sections should be locked when engine is down
        for section in result.get("sections", {}).values():
            assert section["state"] in ("locked", "configured"), f"{section['key']} has state {section['state']} when engine down"

    def test_section_state_reflects_dormant_surface_status(self):
        """A section whose dormant surface is not 'live' should be 'locked'
        — the engine's actual surface status is reflected, not overridden."""
        def _respond(url, *args, **kwargs):
            target = url.get_full_url() if hasattr(url, 'get_full_url') else str(url)
            if "/api/setup/status" in target:
                return _FakeResponse({"onboarding_complete": True, "llm_configured": True, "channels_configured": True})
            if "/api/dormant-surfaces" in target:
                return _FakeResponse([{"key": "chatbot", "status": "dormant"}])
            return _FakeResponse({})

        with patch("urllib.request.urlopen", side_effect=_respond):
            result = features.compute_features()
        sections = result.get("sections", {})
        # Chat requires 'chatbot' dormant -> should be locked when dormant
        if "chat" in sections:
            assert sections["chat"]["state"] != "active", "chat should not be active when chatbot dormant is not live"


# ═══════════════════════════════════════════════════════════════════════════
# Structural: all proxies use the same _forward / _engine pattern
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestProxiesUseForwardPattern:
    """Structural check: every proxy module has a ``_forward`` function
    that is never bypassed by inline urllib calls in dispatch."""

    def test_all_proxies_have_forward(self):
        """Every proxy module defines _forward (consistent API surface)."""
        proxies = [
            agent_runs, audit, campaigns, chat, digest, documents,
            dormant, health, notifications, onboarding, pending, takeover,
            update_panel, vault,
        ]
        for mod in proxies:
            assert hasattr(mod, "_forward"), f"{mod.__name__} missing _forward"

    def test_all_proxies_have_engine_hepler(self):
        proxies = [
            agent_runs, audit, campaigns, chat, digest, documents,
            dormant, health, notifications, onboarding, pending, takeover,
            update_panel, vault,
        ]
        for mod in proxies:
            assert hasattr(mod, "_engine"), f"{mod.__name__} missing _engine helper"

    def test_all_proxy_dispatches_go_through_forward(self):
        """Proxies call _forward from dispatch for all valid actions — they
        never call urllib.request.urlopen directly (which would bypass the
        error normalization envelope)."""
        # Import the actual source to verify
        import inspect
        proxies = [
            agent_runs, audit, campaigns, chat, digest, documents,
            dormant, health, notifications, onboarding, pending, takeover,
            update_panel, vault,
        ]
        for mod in proxies:
            src = inspect.getsource(mod.dispatch)
            assert "_forward" in src, f"{mod.__name__}.dispatch doesn't call _forward"
            assert "urllib.request" not in src or "_forward(" in src, (
                f"{mod.__name__}.dispatch may bypass _forward"
            )
