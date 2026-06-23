"""Computer-use (desktop control) guards — ``FR-CUA-3/5/6`` (docs/spec/computer-use.md).

Pure domain rules (no IO) enforcing the safety machinery on the bounded desktop
action vocabulary, lifted from the Hermes Agent (MIT) computer-use guardrails:

* **FR-CUA-5 — hard blocks (server-side).** Dangerous ``type`` patterns
  (``curl … | bash``, ``sudo rm -rf /``, fork bombs) and dangerous key combos
  (lock / log-out / empty-trash / force-delete) are denied **regardless of approval
  state** and regardless of any caller flag. The denylist lives here in the core, not
  in a prompt.
* **FR-CUA-6 — no secret typing.** Computer use never types passwords/secrets; the
  vault is the only credential source. The adapter passes the value's PROVENANCE
  (``is_secret``) — derived ground truth, not a caller bypass — and a secret value is
  refused.
* **FR-CUA-3 — inherits the stop-boundary.** Any desktop action that would constitute
  an account-create / CAPTCHA / verification / final submit is mapped onto
  :func:`applicant.core.rules.prefill_boundary.ensure_action_allowed` so computer use
  inherits the same stop-boundary as browser pre-fill. The engine still cannot
  self-authorize a final submit, and a caller-supplied flag can never opt past it.

These are pure: the adapters in ``adapters/sandbox/computer_use/`` MUST call them
before any side effect (even the ``noop`` adapter does, so a blocked action raises in
tests too).
"""

from __future__ import annotations

import re
from enum import Enum

from applicant.core.errors import ComputerUseBlocked
from applicant.core.rules.prefill_boundary import StepKind, ensure_action_allowed


class DesktopAction(str, Enum):
    """The bounded desktop-action vocabulary (FR-CUA, spec §4).

    Domain vocabulary — defined in the pure core so the guards below depend on
    nothing outward; the ``ComputerUsePort`` re-exports it for adapters/callers.
    """

    #: Read-only screenshot/AX capture — always allowed (no boundary).
    CAPTURE = "capture"
    #: Activate a control (element/coord) — approval-gated (FR-CUA-4).
    CLICK = "click"
    #: Enter text — approval-gated + pattern-blocked (FR-CUA-5) + no-secrets (FR-CUA-6).
    TYPE_TEXT = "type_text"
    #: Press a key/chord — approval-gated + combo-blocked (FR-CUA-5).
    KEY = "key"
    #: Scroll the view — approval-gated.
    SCROLL = "scroll"
    #: Drag/move — approval-gated.
    DRAG = "drag"
    #: Target a window in the BACKGROUND (no foreground steal) — approval-gated (FR-CUA-7).
    FOCUS_APP = "focus_app"


class CaptureMode(str, Enum):
    """Capture rendering mode (FR-CUA-11)."""

    #: Screenshot with numbered elements (Set-of-Marks). The default.
    SOM = "som"
    #: Accessibility-tree only (text), the degraded path when the model lacks vision.
    AX = "ax"

#: Destructive desktop actions — every one is approval-gated (FR-CUA-4) and subject to
#: the hard-block / no-secret / stop-boundary guards below. ``capture`` is read-only and
#: deliberately excluded (always allowed).
DESTRUCTIVE_ACTIONS: frozenset[DesktopAction] = frozenset(
    {
        DesktopAction.CLICK,
        DesktopAction.TYPE_TEXT,
        DesktopAction.KEY,
        DesktopAction.SCROLL,
        DesktopAction.DRAG,
        DesktopAction.FOCUS_APP,
    }
)


#: Hard-blocked ``type`` patterns (FR-CUA-5). Matched case-insensitively against the
#: whitespace-normalized text. These are denied regardless of approval/authorization.
_BLOCKED_TYPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # curl/wget … | sh|bash  — remote-exec a downloaded script.
    re.compile(r"\b(?:curl|wget)\b.*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b", re.IGNORECASE),
    # sudo rm -rf /  — recursive force-delete from root.
    re.compile(r"\brm\b\s+-[a-z]*r[a-z]*f[a-z]*\s+/(?:\s|$|\*)", re.IGNORECASE),
    re.compile(r"\brm\b\s+-[a-z]*f[a-z]*r[a-z]*\s+/(?:\s|$|\*)", re.IGNORECASE),
    # :(){ :|:& };:  — the classic bash fork bomb (and spacing variants).
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.IGNORECASE),
    # mkfs / dd to a raw disk — destructive disk writes.
    re.compile(r"\bmkfs(?:\.\w+)?\b\s+/dev/", re.IGNORECASE),
    re.compile(r"\bdd\b\s+if=.*\bof=/dev/", re.IGNORECASE),
)


#: Hard-blocked key-combo tokens (FR-CUA-5). Each entry is a normalized set of the
#: chord's keys; a chord whose key-set is a superset of any entry is denied. Covers
#: lock / log-out / empty-trash / force-delete combos across the supported desktops.
_BLOCKED_KEY_COMBOS: tuple[frozenset[str], ...] = (
    frozenset({"super", "l"}),  # GNOME/Cinnamon lock screen
    frozenset({"ctrl", "alt", "l"}),  # XFCE/Cinnamon lock screen
    frozenset({"ctrl", "alt", "delete"}),  # log-out / security screen
    frozenset({"ctrl", "alt", "end"}),  # remote log-out
    frozenset({"super", "d"}),  # show-desktop / hide-all (focus disruption)
    frozenset({"shift", "delete"}),  # permanent (force) delete, bypasses trash
    frozenset({"cmd", "shift", "delete"}),  # empty trash (mac-style binding)
    frozenset({"meta", "shift", "delete"}),
    frozenset({"super", "shift", "delete"}),
)

#: Aliases normalized to a canonical key token before combo matching.
_KEY_ALIASES: dict[str, str] = {
    "control": "ctrl",
    "del": "delete",
    "win": "super",
    "windows": "super",
    "command": "cmd",
    "option": "alt",
    "return": "enter",
    "esc": "escape",
}


def _normalize_combo(keys: str) -> frozenset[str]:
    """Split a chord string (``"Ctrl+Alt+L"``/``"super l"``) into canonical key tokens."""
    raw = re.split(r"[+\-\s]+", (keys or "").strip().lower())
    tokens = {_KEY_ALIASES.get(tok, tok) for tok in raw if tok}
    return frozenset(tokens)


def ensure_type_text_allowed(text: str) -> None:
    """Raise ``ComputerUseBlocked`` if ``text`` matches a hard-blocked pattern (FR-CUA-5).

    Server-side denylist (not a prompt). Denied regardless of approval state.
    """
    normalized = " ".join((text or "").split())
    for pattern in _BLOCKED_TYPE_PATTERNS:
        if pattern.search(text or "") or pattern.search(normalized):
            raise ComputerUseBlocked(
                "Refusing to type a dangerous command into the desktop."
            )


def ensure_key_combo_allowed(keys: str) -> None:
    """Raise ``ComputerUseBlocked`` if ``keys`` is a hard-blocked combo (FR-CUA-5).

    A chord is blocked when its key-set covers any blocked combo (so extra modifiers
    cannot smuggle a lock/log-out/force-delete past the gate).
    """
    combo = _normalize_combo(keys)
    if not combo:
        return
    for blocked in _BLOCKED_KEY_COMBOS:
        if blocked <= combo:
            raise ComputerUseBlocked(
                "Refusing to press a blocked key combination on the desktop."
            )


def no_secret_typing(*, is_secret: bool) -> None:
    """Raise ``ComputerUseBlocked`` if a secret/credential value is about to be typed.

    FR-CUA-6: computer use never types passwords/secrets — the vault is the only
    credential source. ``is_secret`` is the adapter-derived provenance of the value
    (vault / sensitive-field), NOT a caller bypass; a secret value is always refused.
    """
    if is_secret:
        raise ComputerUseBlocked(
            "Refusing to type a credential on the desktop; secrets come from the vault."
        )


#: Desktop actions that, by their intent label, constitute an irreducible/boundary step
#: and so MUST be routed through the pre-fill stop-boundary (FR-CUA-3). Keyed by a free
#: ``intent`` string the adapter derives from the targeted control (never a caller flag).
_INTENT_TO_STEP: dict[str, StepKind] = {
    "account_create_submit": StepKind.ACCOUNT_CREATE_SUBMIT,
    "account_create": StepKind.ACCOUNT_CREATE_SUBMIT,
    "create_account": StepKind.ACCOUNT_CREATE_SUBMIT,
    "captcha": StepKind.CAPTCHA,
    "turnstile": StepKind.CAPTCHA,
    "email_verify": StepKind.EMAIL_VERIFY,
    "sms_verify": StepKind.SMS_VERIFY,
    "verify": StepKind.EMAIL_VERIFY,
    "final_submit": StepKind.FINAL_SUBMIT,
    "submit_application": StepKind.FINAL_SUBMIT,
}


def step_for_intent(intent: str | None) -> StepKind | None:
    """Map an adapter-derived control ``intent`` to a boundary :class:`StepKind`, or None."""
    if not intent:
        return None
    return _INTENT_TO_STEP.get(intent.strip().lower())


def ensure_desktop_action_allowed(
    action: DesktopAction,
    *,
    intent: str | None = None,
    step_kind: StepKind | None = None,
    engine_submit_authorized: bool = False,
    automated_accounts_enabled: bool = False,
) -> None:
    """Gate a desktop ``action`` against the pre-fill stop-boundary (FR-CUA-3).

    Computer use INHERITS the browser pre-fill stop-boundary: a desktop action that
    would create an account, clear a CAPTCHA/verification, or perform a final submit is
    routed through :func:`prefill_boundary.ensure_action_allowed` and denied the same
    way the browser path is. ``capture`` (read-only) is never gated.

    The boundary step is derived from server-side ground truth — either an explicit
    ``step_kind`` the adapter inferred, or an ``intent`` label resolved against
    :func:`step_for_intent`. There is **no** caller-supplied flag that opts a desktop
    action past the boundary (FR-CUA-3); ``engine_submit_authorized`` /
    ``automated_accounts_enabled`` are server-derived config threaded in by the adapter,
    mirroring the browser path's contract.
    """
    if action is DesktopAction.CAPTURE:
        return
    resolved = step_kind or step_for_intent(intent)
    if resolved is None:
        # An ordinary destructive action (click/type/scroll/...) that does not map to a
        # boundary step. It is still approval-gated (FR-CUA-4) + hard-block/no-secret
        # gated elsewhere, but it does not trip the stop-boundary.
        return
    ensure_action_allowed(
        resolved,
        engine_submit_authorized=engine_submit_authorized,
        automated_accounts_enabled=automated_accounts_enabled,
    )
