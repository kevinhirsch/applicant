"""P1-4 — Notifications out of the box: front-door pins.

Engine-side coverage lives in ``tests/unit/test_p1_4_notifications_oob.py``
(per-channel test endpoint, honest failure propagation, failed-push inbox
notes). This file pins the FRONT-DOOR pieces the story added:

* each channel row in the Notifications panel (wizard step AND Settings tab —
  same renderer) has its own Send-test button wired to the per-channel
  ``POST /channels/test {channel}`` lane, with the save-first + dry-run-honesty
  behaviors of the existing all-channels button;
* the in-app inbox is described as zero-config (always on) right in the panel;
* Today's setup-essentials checklist gives the optional notifications item its
  own one-tap "Set up" jump into Settings → Notifications (the wizard's
  "Finish setup" button can't reach it — channels are not a wizard step).

The JS assertions follow the established harness pattern: slice the real
function bodies out of the shipped source and execute them under node.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent  # workspace/
TODAY_JS = _REPO / "static" / "js" / "applicantToday.js"
ONBOARDING_JS = _REPO / "static" / "js" / "applicantOnboarding.js"
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def _run_node(script: str) -> dict:
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO,
        capture_output=True,
        timeout=15,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    if not out_lines:
        raise AssertionError("node produced no stdout")
    return json.loads(out_lines[-1])


def _esc_stub() -> str:
    return (
        "function esc(s) { return (s == null ? '' : String(s)).replace(/[&<>\"']/g, "
        "(c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c])); }"
    )


def _channels_block() -> str:
    return _slice_between(
        _read(ONBOARDING_JS),
        "async function _renderChannels()",
        "// ── STEP 2.5: Automation sandbox",
    )


# ===========================================================================
# Per-channel Send test (wizard step + Settings tab share this renderer)
# ===========================================================================


def test_every_channel_row_has_its_own_send_test_button():
    block = _channels_block()
    for btn in ("ao-ch-test-discord", "ao-ch-test-email", "ao-ch-test-ntfy"):
        assert f'id="{btn}"' in block, f"missing per-channel test button {btn}"
        assert f'id="{btn}-msg"' in block, f"missing status span for {btn}"
    # The all-channels test button survives (fan-out sanity check).
    assert 'id="ao-ch-test"' in block


def test_per_channel_test_posts_the_channel_name():
    block = _channels_block()
    # One shared handler, wired once per channel with the engine channel name.
    assert "_wireChannelTest('ao-ch-test-discord', 'discord'" in block
    assert "_wireChannelTest('ao-ch-test-email', 'email'" in block
    assert "_wireChannelTest('ao-ch-test-ntfy', 'ntfy'" in block
    assert "channels/test`, { channel })" in block, (
        "the per-channel handler must POST the single-channel body"
    )


def test_per_channel_test_saves_first_but_only_when_something_is_typed():
    block = _channels_block()
    handler = _slice_between(
        block, "const _wireChannelTest", "_wireChannelTest('ao-ch-test-discord'"
    )
    # Save precedes the test so the freshly-typed value is what gets tested —
    # but an all-empty save is skipped (the engine rejects it, and testing an
    # already-saved channel needs no re-save).
    assert "body.discord_webhook_url || body.apprise_urls || body.ntfy_url" in handler
    assert "channels`, body)" in handler
    # Dry-run honesty is reported per channel, same as the all-channels button.
    assert "res.live === false" in handler
    # A delivery failure reports on the row, in plain language.
    assert "didn’t send" in handler


def test_already_saved_channels_are_testable_with_blank_fields():
    block = _channels_block()
    # The hasValue guards accept the persisted flags (cur.*_configured) so a
    # user can re-test a saved channel without re-typing its secret.
    assert "cur.discord_configured" in block
    assert "cur.email_configured" in block
    assert "cur.ntfy_configured" in block


def test_panel_says_in_app_inbox_is_zero_config():
    block = _channels_block()
    assert "always on with zero setup" in block, (
        "the panel must say the in-app inbox needs no configuration"
    )


# ===========================================================================
# Today checklist: the notifications item gets a one-tap Set up jump
# ===========================================================================


def _essentials_block() -> str:
    return _slice_between(
        _read(TODAY_JS),
        "export function _essentialsChecklistHTML(essentials)",
        "function _renderComplete(wrap, item)",
    )


def test_unchecked_notifications_row_carries_a_setup_link(node_available):
    block = _essentials_block()
    script = textwrap.dedent(f"""
        {_esc_stub()}
        {block}
        const out = {{}};
        out.undone = _essentialsChecklistHTML([
          {{ key: 'model', label: 'Connect a model', done: false }},
          {{ key: 'notifications', label: 'Notifications (optional)', done: false }},
        ]);
        out.done = _essentialsChecklistHTML([
          {{ key: 'notifications', label: 'Notifications (optional)', done: true }},
        ]);
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert 'data-role="essential-notifications"' in out["undone"]
    assert "Set up" in out["undone"]
    # Only the notifications row gets the jump — the model row is wizard-owned.
    assert out["undone"].count("data-role=") == 1
    # A configured channel needs no jump.
    assert 'data-role="essential-notifications"' not in out["done"]


def test_setup_link_opens_settings_notifications_tab():
    block = _essentials_block()
    wiring = _slice_between(
        block, "function _wireEssentialsSetupLink(host)", "}\n"
    )
    assert "settingsModule.open('notifications')" in wiring or (
        "settingsModule.open('notifications')" in block
    )
    src = _read(TODAY_JS)
    # Both hosts that render the checklist wire the link on their fresh HTML.
    complete = _slice_between(src, "function _renderComplete(wrap, item)", "const _AFFORDANCE_RENDERERS")
    assert "_wireEssentialsSetupLink(wrap)" in complete
    gated = _slice_between(src, "function _renderGated(host, data)", "// ── Cost & pace guardrails")
    assert "_wireEssentialsSetupLink(host)" in gated
