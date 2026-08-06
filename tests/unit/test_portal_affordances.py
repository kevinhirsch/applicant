"""Static-surface assertions for kind-aware Portal affordances (issue #833, slice 1)."""

from __future__ import annotations

import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TODAY = _REPO_ROOT / "a0-applicant" / "webui" / "today.html"

_ALLOWED_KINDS = (
    "digest_approval",
    "material_review",
    "final_approval",
    "missing_attr",
    "integral_change",
)

_DEEP_LINK_PANELS = (
    "digest.html",
    "documents.html",
    "attributes.html",
    "compare.html",
)


def _today_text() -> str:
    assert _TODAY.exists(), "a0-applicant/webui/today.html not found"
    return _TODAY.read_text(encoding="utf-8")


def test_affordance_map_present() -> None:
    """today.html contains a KIND_AFFORDANCE map referencing all five pending kinds."""
    text = _today_text()
    assert "KIND_AFFORDANCE" in text
    for kind in _ALLOWED_KINDS:
        assert f"{kind}:" in text


def test_deep_link_targets() -> None:
    """today.html references each deep-link target panel used by the affordances."""
    text = _today_text()
    for panel in _DEEP_LINK_PANELS:
        assert panel in text


def test_uses_openModal() -> None:
    """The affordance opens via window.openModal('/plugins/applicant/webui/' + ...)."""
    text = _today_text()
    assert "window.openModal(\"/plugins/applicant/webui/\" + a.panel)" in text


def test_resolve_and_snooze_retained() -> None:
    """The universal Resolve and Snooze fallbacks remain on every item."""
    text = _today_text()
    assert "resolveItem(item.id)" in text
    assert "snoozeItem(item.id)" in text


def test_no_inline_resolve_body() -> None:
    """No inline answer/decision resolve body: inline handling is out of scope for this slice."""
    text = _today_text()
    assert '"answer"' not in text
    assert '"decision"' not in text
