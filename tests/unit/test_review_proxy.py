"""EPIC REVIEW-UX — review proxy dispatch/forward routing (Integrate step).

The proxy is an a0-applicant api handler that runs in the A0 shell, so we load just
its module with the framework imports stubbed and exercise the pure ``dispatch``
routing (hermetic — ``_forward`` is patched, no engine call). Mirrors
``test_model_config_proxy.py`` / ``test_digest_proxy.py``.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/review.py"


@pytest.fixture()
def mod():
    api = types.ModuleType("helpers.api")

    class _AH:
        def __init__(self, *a, **k):
            pass

    api.ApiHandler = _AH
    helpers = sys.modules.setdefault("helpers", types.ModuleType("helpers"))
    helpers.api = api
    sys.modules["helpers.api"] = api
    flask = sys.modules.setdefault("flask", types.ModuleType("flask"))
    flask.Request = object

    spec = importlib.util.spec_from_file_location("_az_review", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture(mod):
    """Patch _forward so no engine call happens; record the last call + stub campaigns."""
    seen: dict = {}

    def fake(method, path, body=None, timeout=30):
        # Let the campaign resolver read a stubbed active campaign, but record the
        # real (review) forward the action performs.
        if path == "/api/campaigns" and method == "GET":
            return {"ok": True, "status": 200, "data": [{"id": "camp-1", "active": True}]}
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    return seen, fake


class TestReviewProxy:
    def test_get_forwards_to_source(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "get", "application_id": "app-1"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/review/app-1/source"
        assert r["ok"] is True

    def test_snapshot_forwards_to_source(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch({"action": "snapshot", "application_id": "app-1"})
        assert seen["path"] == "/api/review/app-1/source"

    def test_get_requires_application_id(self, mod):
        r = mod.dispatch({"action": "get"})
        assert r["ok"] is False and r["status"] == 400

    def test_decide_continue_forwards_post(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch(
                {"action": "decide", "application_id": "app-1", "decision": "continue"}
            )
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/review/app-1/continue"

    def test_decide_save_for_later_forwards_body(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch(
                {
                    "action": "decide",
                    "application_id": "app-1",
                    "decision": "save_for_later",
                    "posting_id": "post-9",
                    "campaign_id": "__system__",
                }
            )
        assert seen["path"] == "/api/review/app-1/save-for-later"
        # __system__ resolves to the stubbed active campaign.
        assert seen["body"]["campaign_id"] == "camp-1"
        assert seen["body"]["posting_id"] == "post-9"

    def test_decide_discard_requires_reason(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            r = mod.dispatch(
                {"action": "decide", "application_id": "app-1", "decision": "discard"}
            )
        assert r["ok"] is False and r["status"] == 400

    def test_decide_discard_forwards_reason(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch(
                {
                    "action": "decide",
                    "application_id": "app-1",
                    "decision": "discard",
                    "reason": "wrong seniority",
                    "campaign_id": "camp-x",
                }
            )
        assert seen["path"] == "/api/review/app-1/discard"
        assert seen["body"] == {
            "campaign_id": "camp-x",
            "reason": "wrong seniority",
            "posting_id": None,
        }

    def test_regenerate_section_maps_to_apply_instruction(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch(
                {
                    "action": "regenerate_section",
                    "application_id": "app-1",
                    "section_id": "doc-7",
                    "feedback": "make it punchier",
                    "campaign_id": "camp-x",
                }
            )
        assert seen["path"] == "/api/review/app-1/apply-instruction"
        assert seen["body"]["instruction"] == "make it punchier"
        assert seen["body"]["document_ids"] == ["doc-7"]

    def test_apply_feedback_fans_across_sections(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch(
                {
                    "action": "apply_feedback",
                    "application_id": "app-1",
                    "feedback": "tighten everything",
                    "campaign_id": "camp-x",
                }
            )
        assert seen["path"] == "/api/review/app-1/apply-instruction"
        assert seen["body"]["document_ids"] == []  # empty -> ALL sections

    def test_regenerate_all_maps_to_apply_instruction(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch(
                {
                    "action": "regenerate_all",
                    "application_id": "app-1",
                    "feedback": "redo it",
                    "campaign_id": "camp-x",
                }
            )
        assert seen["path"] == "/api/review/app-1/apply-instruction"
        assert seen["body"]["instruction"] == "redo it"

    def test_saved_bucket_uses_resolved_campaign(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch({"action": "saved", "campaign_id": "__system__"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/review/camp-1/saved"

    def test_profile_feedback_folds_into_learning(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch(
                {
                    "action": "profile_feedback",
                    "application_id": "app-1",
                    "feedback": "prefer earlier-stage startups",
                    "campaign_id": "camp-x",
                }
            )
        assert seen["path"] == "/api/feedback/freetext"
        assert seen["body"] == {"campaign_id": "camp-x", "text": "prefer earlier-stage startups"}

    def test_edit_section_is_graceful_501(self, mod):
        r = mod.dispatch(
            {"action": "edit_section", "application_id": "app-1", "section_id": "d", "content": "x"}
        )
        assert r["ok"] is False and r["status"] == 501

    def test_revert_feedback_is_graceful_501(self, mod):
        r = mod.dispatch({"action": "revert_feedback", "campaign_id": "camp-x", "adjustment_id": "a"})
        assert r["ok"] is False and r["status"] == 501

    def test_index_default(self, mod):
        seen, fake = _capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch({})
        assert seen["path"] == "/api/review"

    def test_unknown_action_is_400(self, mod):
        r = mod.dispatch({"action": "bogus"})
        assert r["ok"] is False and r["status"] == 400
