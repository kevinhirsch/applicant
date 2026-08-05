"""
STEP 2 — create the test file.
"""

from __future__ import annotations

import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CHIP = _REPO_ROOT / "a0-applicant" / "extensions" / "webui" / "chat-input-bottom-actions-end" / "save-a-job.html"


def test_chip_component_exists() -> None:
    """Guard: the chip extension file must exist so content assertions can't silently pass."""
    assert _CHIP.exists(), "a0-applicant/extensions/webui/chat-input-bottom-actions-end/save-a-job.html not found"


def test_chip_has_extension_id() -> None:
    """The root wrapper carries the fork's extension id (required for breakpoint injection)."""
    text = _CHIP.read_text(encoding="utf-8")
    assert 'data-extension-id="applicant-save-a-job"' in text


def test_chip_label_and_intent() -> None:
    """Chip shows the Save-a-job label and carries the exact composer prefill intent."""
    text = _CHIP.read_text(encoding="utf-8")
    assert "Save a job" in text
    assert "Save this job: " in text


def test_chip_prefills_via_store_and_is_not_submit() -> None:
    """Click prefills via $store.chatInput.message/focus() and the button is type=button."""
    text = _CHIP.read_text(encoding="utf-8")
    assert "$store.chatInput.message" in text
    assert "$store.chatInput.focus()" in text
    assert 'type="button"' in text


def test_chip_adds_no_new_css_or_core_edits() -> None:
    """The chip reuses .text-button and injects only - no <style>, no core path."""
    text = _CHIP.read_text(encoding="utf-8")
    assert "<style" not in text
    assert "/a0/webui" not in text
