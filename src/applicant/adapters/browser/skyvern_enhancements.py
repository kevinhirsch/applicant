"""Skyvern-parity enhancements: iframe/shadow DOM field penetration, adaptive
waiting, and error recovery (Issue #351).

These enhancements bridge the gap between the current engine and Skyvern-level
autonomous form-filling capability. They are designed as composable helpers
that the PlaywrightPageSource (and its fake counterpart) can use.

Key capabilities:
1. iframe penetration — traverse cross-origin and same-origin iframes to
   detect fields nested inside them.
2. Shadow DOM penetration — recursively open closed shadow roots to detect
   fields inside web components.
3. Adaptive waiting — smart polling for element visibility that adapts based
   on page behavior.
4. Error recovery — self-correcting re-plan on broken selectors instead of
   aborting.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── iframe / shadow DOM field penetration ──────────────────────────────────


@dataclass(frozen=True)
class PenetratedField:
    """A field detected through iframe or shadow DOM penetration.

    Carries enough context for the planner to build a PlanOp targeting it.
    """

    selector: str
    """The Playwright selector that can reach this field, e.g.
    ``iframe[name='iframe1'] >>> [name='field']`` or
    ``[data-testid='root'] >>> [name='field']``."""

    label: str
    """Human-readable label resolved from the field's context."""

    field_type: str
    """The HTML field type (text, select, textarea, listbox, etc.)."""

    required: bool
    """Whether the field is marked required."""

    source: str
    """Where the field was found: 'main', 'iframe', 'shadow_dom', or
    'iframe_shadow_dom'."""

    frame_selector: str | None = None
    """The iframe selector path, if the field is inside an iframe."""


def penetrate_iframes(
    page: Any,
    *,
    max_depth: int = 3,
) -> list[PenetratedField]:
    """Detect fields inside iframes up to ``max_depth`` levels deep.

    Traverses same-origin iframes (which Playwright can access) recursively.
    Cross-origin iframes are noted but their fields cannot be read — they
    are skipped with a warning.

    Args:
        page: A Playwright page object.
        max_depth: Maximum iframe nesting depth (default 3).

    Returns:
        List of PenetratedField instances found inside iframes.
    """
    fields: list[PenetratedField] = []

    def _recurse(frame: Any, depth: int, path: list[str]) -> None:
        if depth > max_depth:
            return
        try:
            child_frames = frame.child_frames
        except Exception:
            return
        for child in child_frames:
            try:
                name = child.name or ""
            except Exception:
                name = ""
            frame_path = path + [name or f"iframe_{depth}"]
            frame_selector = " >> ".join(
                f"iframe[name='{p}']" if p else "iframe"
                for p in frame_path
            )
            # Try to detect fields in the child iframe
            try:
                # Playwright can query elements inside same-origin iframes
                for handle in child.query_selector_all("input, select, textarea"):
                    f_name = handle.get_attribute("name") or ""
                    f_id = handle.get_attribute("id") or ""
                    selector = (
                        f'[name="{f_name}"]'
                        if f_name
                        else f'[id="{f_id}"]' if f_id else ""
                    )
                    if not selector:
                        continue
                    # Prepend the iframe path to the selector
                    full_selector = f"{frame_selector} >>> {selector}"
                    label = (
                        handle.get_attribute("aria-label")
                        or f_name
                        or f_id
                    )
                    ftype = handle.get_attribute("type") or "text"
                    fields.append(
                        PenetratedField(
                            selector=full_selector,
                            label=label,
                            field_type=ftype,
                            required=(
                                handle.get_attribute("required") is not None
                            ),
                            source="iframe",
                            frame_selector=frame_selector,
                        )
                    )
                # Recurse into nested iframes
                _recurse(child, depth + 1, frame_path)
            except Exception:
                # Cross-origin iframe — cannot access fields
                logger.debug(
                    "Cannot access iframe %s (likely cross-origin), skipping",
                    frame_selector,
                )
                continue

    _recurse(page, 1, [])
    return fields


def penetrate_shadow_dom(
    page: Any,
    *,
    max_depth: int = 5,
) -> list[PenetratedField]:
    """Detect fields inside shadow DOM roots recursively.

    Uses JavaScript evaluation to traverse open shadow roots (``mode: open``)
    and find input/select/textarea elements inside web components.

    Args:
        page: A Playwright page object.
        max_depth: Maximum shadow DOM nesting depth (default 5).

    Returns:
        List of PenetratedField instances found inside shadow DOM.
    """
    fields: list[PenetratedField] = []

    try:
        results = page.evaluate(
            """
            (maxDepth) => {
                const results = [];

                function penetrateShadow(root, depth, path) {
                    if (depth > maxDepth) return;
                    const elements = root.querySelectorAll('input, select, textarea');
                    elements.forEach(el => {
                        const name = el.getAttribute('name') || '';
                        const id = el.getAttribute('id') || '';
                        const label = el.getAttribute('aria-label') || name || id;
                        const ftype = el.getAttribute('type') || el.tagName.toLowerCase();
                        results.push({
                            selector: path ? `${path} >>> ${name ? '[name="${name}"]' : '[id="${id}"]'}` : (name ? '[name="${name}"]' : '[id="${id}"]'),
                            label: label,
                            fieldType: ftype,
                            required: el.hasAttribute('required'),
                            source: 'shadow_dom',
                        });
                    });

                    // Recurse into shadow hosts
                    const hosts = root.querySelectorAll('*');
                    hosts.forEach(host => {
                        if (host.shadowRoot) {
                            const newPath = path
                                ? `${path} >>> ${host.tagName.toLowerCase()}`
                                : host.tagName.toLowerCase();
                            penetrateShadow(host.shadowRoot, depth + 1, newPath);
                        }
                    });
                }

                penetrateShadow(document, 0, '');
                return results;
            }
            """,
            max_depth,
        )
    except Exception:
        logger.warning("Shadow DOM penetration failed (may not be supported)")
        return []

    for r in results:
        fields.append(
            PenetratedField(
                selector=r.get("selector", ""),
                label=r.get("label", ""),
                field_type=r.get("fieldType", "text"),
                required=r.get("required", False),
                source=r.get("source", "shadow_dom"),
            )
        )

    return fields


def detect_fields_with_penetration(
    page: Any,
    *,
    detect_iframes: bool = True,
    detect_shadow_dom: bool = True,
    iframe_max_depth: int = 3,
    shadow_max_depth: int = 5,
) -> list[PenetratedField]:
    """Detect all fields on the page, including those inside iframes and shadow DOM.

    Combines main-document field detection with iframe and shadow DOM penetration.
    De-duplicates by selector.

    Args:
        page: A Playwright page object.
        detect_iframes: Whether to penetrate iframes (default True).
        detect_shadow_dom: Whether to penetrate shadow DOM (default True).
        iframe_max_depth: Maximum iframe nesting depth.
        shadow_max_depth: Maximum shadow DOM nesting depth.

    Returns:
        Combined list of PenetratedField instances from all sources.
    """
    all_fields: list[PenetratedField] = []
    seen_selectors: set[str] = set()

    # Main document fields
    for handle in page.query_selector_all("input, select, textarea"):
        name = handle.get_attribute("name") or ""
        elem_id = handle.get_attribute("id") or ""
        selector = (
            f'[name="{name}"]'
            if name
            else f'[id="{elem_id}"]' if elem_id
            else ""
        )
        if not selector or selector in seen_selectors:
            continue
        seen_selectors.add(selector)
        all_fields.append(
            PenetratedField(
                selector=selector,
                label=handle.get_attribute("aria-label") or name or elem_id,
                field_type=handle.get_attribute("type") or "text",
                required=handle.get_attribute("required") is not None,
                source="main",
            )
        )

    # iframe penetration
    if detect_iframes:
        for f in penetrate_iframes(page, max_depth=iframe_max_depth):
            if f.selector not in seen_selectors:
                seen_selectors.add(f.selector)
                all_fields.append(f)

    # Shadow DOM penetration
    if detect_shadow_dom:
        for f in penetrate_shadow_dom(page, max_depth=shadow_max_depth):
            if f.selector not in seen_selectors:
                seen_selectors.add(f.selector)
                all_fields.append(f)

    return all_fields


# ── Adaptive waiting ───────────────────────────────────────────────────────


@dataclass
class AdaptiveWaitConfig:
    """Configuration for adaptive element waiting."""

    initial_timeout_s: float = 2.0
    """Initial timeout for element detection (seconds)."""

    max_timeout_s: float = 30.0
    """Maximum timeout after adaptation (seconds)."""

    poll_interval_s: float = 0.2
    """Polling interval (seconds)."""

    adapt_multiplier: float = 1.5
    """Multiplier for adaptive timeout increase."""

    max_adaptations: int = 3
    """Maximum number of adaptive timeout increases."""


@dataclass
class AdaptiveWaitResult:
    """Result of an adaptive wait operation."""

    found: bool
    """True if the element was found within the adapted timeout."""

    total_waited_s: float
    """Total time waited (seconds)."""

    adaptations: int
    """Number of times the timeout was adapted."""

    element: Any | None = None
    """The found element, if any."""


def adaptive_wait_for_element(
    page: Any,
    selector: str,
    *,
    config: AdaptiveWaitConfig | None = None,
    condition: str = "visible",
) -> AdaptiveWaitResult:
    """Wait for an element with adaptive timeout.

    Starts with a short timeout. If the element is not found, increases the
    timeout and retries. This allows fast success on quick pages while still
    handling slow-loading SPA content.

    Args:
        page: A Playwright page object.
        selector: The selector to wait for.
        config: Adaptive wait configuration (uses defaults if None).
        condition: The wait condition ('visible', 'attached', 'stable').

    Returns:
        AdaptiveWaitResult indicating whether the element was found.
    """
    cfg = config or AdaptiveWaitConfig()
    timeout = cfg.initial_timeout_s
    total_waited = 0.0
    adaptations = 0

    for attempt in range(cfg.max_adaptations + 1):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if condition == "visible":
                    el = page.query_selector(selector)
                    if el is not None and el.is_visible():
                        _waited = total_waited + (deadline - time.monotonic())
                        return AdaptiveWaitResult(
                            found=True,
                            total_waited_s=cfg.initial_timeout_s
                            + (timeout * attempt),
                            adaptations=adaptations,
                            element=el,
                        )
                elif condition == "attached":
                    el = page.query_selector(selector)
                    if el is not None:
                        _waited = total_waited + (deadline - time.monotonic())
                        return AdaptiveWaitResult(
                            found=True,
                            total_waited_s=cfg.initial_timeout_s
                            + (timeout * attempt),
                            adaptations=adaptations,
                            element=el,
                        )
                elif condition == "stable":
                    # Wait for the element to be present and not changing
                    el = page.query_selector(selector)
                    if el is not None:
                        # Check stability: attribute count doesn't change
                        try:
                            initial_count = el.evaluate("e => e.attributes.length")
                            time.sleep(0.3)
                            new_count = el.evaluate("e => e.attributes.length")
                            if initial_count == new_count and el.is_visible():
                                _waited = total_waited + (deadline - time.monotonic())
                                return AdaptiveWaitResult(
                                    found=True,
                                    total_waited_s=cfg.initial_timeout_s
                                    + (timeout * attempt),
                                    adaptations=adaptations,
                                    element=el,
                                )
                        except Exception:
                            if el.is_visible():
                                return AdaptiveWaitResult(
                                    found=True,
                                    total_waited_s=cfg.initial_timeout_s
                                    + (timeout * attempt),
                                    adaptations=adaptations,
                                    element=el,
                                )
            except Exception:
                pass
            time.sleep(cfg.poll_interval_s)

        total_waited += timeout
        if attempt < cfg.max_adaptations:
            timeout = min(timeout * cfg.adapt_multiplier, cfg.max_timeout_s)
            adaptations += 1

    return AdaptiveWaitResult(
        found=False,
        total_waited_s=total_waited,
        adaptations=adaptations,
    )


# ── Error recovery / self-healing ──────────────────────────────────────────


@dataclass
class RecoveryAttempt:
    """Record of a single recovery attempt."""

    strategy: str
    """The recovery strategy used (e.g. 'retry', 'replan', 'fallback_selector')."""

    success: bool
    """Whether the recovery was successful."""

    duration_s: float
    """How long the recovery took (seconds)."""

    detail: str = ""
    """Additional detail about the attempt."""


@dataclass
class RecoveryResult:
    """Result of an error recovery operation."""

    recovered: bool
    """True if the operation was successfully recovered."""

    attempts: list[RecoveryAttempt] = field(default_factory=list)
    """List of recovery attempts made."""

    alternative_selector: str | None = None
    """An alternative selector that worked, if found."""


def recover_broken_selector(
    page: Any,
    original_selector: str,
    field_label: str | None = None,
    *,
    max_attempts: int = 3,
    wait_config: AdaptiveWaitConfig | None = None,
) -> RecoveryResult:
    """Attempt to recover from a broken selector by trying alternative strategies.

    Strategies:
    1. Retry with adaptive wait (the element may just not have loaded yet).
    2. Try alternative selectors based on the field label.
    3. Look for nearby elements with similar attributes.
    4. Try to find the element by text content.

    Args:
        page: A Playwright page object.
        original_selector: The selector that failed.
        field_label: Optional human-readable field label to guide recovery.
        max_attempts: Maximum number of recovery attempts.
        wait_config: Adaptive-wait tuning for strategy 1. A caller on the hot pre-fill
            path passes a SHORT config so a stale selector is declared broken quickly
            instead of blocking the walk on the default multi-second ladder.

    Returns:
        RecoveryResult indicating whether recovery succeeded and how.
    """
    attempts: list[RecoveryAttempt] = []
    _start = time.monotonic()

    # Strategy 1: Retry with adaptive wait
    wait_result = adaptive_wait_for_element(page, original_selector, config=wait_config)
    attempts.append(
        RecoveryAttempt(
            strategy="adaptive_retry",
            success=wait_result.found,
            duration_s=wait_result.total_waited_s,
            detail=f"waited {wait_result.total_waited_s:.1f}s, "
            f"adapted {wait_result.adaptations}x",
        )
    )
    if wait_result.found:
        return RecoveryResult(
            recovered=True,
            attempts=attempts,
        )

    # Strategy 2: Try alternative selectors based on the field label
    if field_label:
        alt_selectors = _build_alternative_selectors(original_selector, field_label)
        for alt_sel in alt_selectors[:max_attempts]:
            _ts = time.monotonic()
            try:
                el = page.query_selector(alt_sel)
                if el is not None and el.is_visible():
                    duration = time.monotonic() - _ts
                    attempts.append(
                        RecoveryAttempt(
                            strategy="fallback_selector",
                            success=True,
                            duration_s=duration,
                            detail=f"found with alternative selector {alt_sel}",
                        )
                    )
                    return RecoveryResult(
                        recovered=True,
                        attempts=attempts,
                        alternative_selector=alt_sel,
                    )
            except Exception:
                pass
            duration = time.monotonic() - _ts
            attempts.append(
                RecoveryAttempt(
                    strategy="fallback_selector",
                    success=False,
                    duration_s=duration,
                    detail=f"alternative {alt_sel} not found",
                )
            )

    # Strategy 3: Look for elements by text content
    if field_label:
        _ts = time.monotonic()
        try:
            # Look for a label with this text, then get its for/id target
            label_el = page.query_selector(
                f"label:has-text('{_escape_css_string(field_label)}')"
            )
            if label_el is not None:
                for_attr = label_el.get_attribute("for")
                if for_attr:
                    target = page.query_selector(f"#{for_attr}")
                    if target is not None:
                        duration = time.monotonic() - _ts
                        attempts.append(
                            RecoveryAttempt(
                                strategy="label_for_attribute",
                                success=True,
                                duration_s=duration,
                                detail=f"found via label[for={for_attr}]",
                            )
                        )
                        return RecoveryResult(
                            recovered=True,
                            attempts=attempts,
                            alternative_selector=f"#{for_attr}",
                        )
        except Exception:
            pass

    # All strategies failed
    return RecoveryResult(recovered=False, attempts=attempts)


def _build_alternative_selectors(
    original: str, label: str
) -> list[str]:
    """Build alternative selectors based on the original and field label."""
    alternatives: list[str] = []

    # Try common attribute patterns
    safe_label = _escape_css_string(label)
    alternatives.append(f'[aria-label="{safe_label}"]')
    alternatives.append(f'[placeholder="{safe_label}"]')
    alternatives.append(f'[title="{safe_label}"]')

    # Try data attributes
    alt_id = label.lower().replace(" ", "_")
    alternatives.append(f'[data-automation-id="{alt_id}"]')
    alternatives.append(f'[data-testid="{alt_id}"]')
    alternatives.append(f'[id="{alt_id}"]')
    alternatives.append(f'[name="{alt_id}"]')

    # Try partial id match from original (handles both single and double quotes)
    if "name=" in original:
        import re as _re
        m = _re.search(r'name=["\']([^"\']+)["\']', original)
        if m:
            name_val = m.group(1)
            alternatives.append(f'[id="{name_val}"]')
            alternatives.append(f'[data-automation-id="{name_val}"]')

    return alternatives


def _escape_css_string(value: str) -> str:
    """Escape a string for use in a CSS attribute selector."""
    # Escape backslashes first, then double-quotes
    return value.replace("\\", "\\\\").replace('"', '\\"')


# ── Stop-boundary guard (safety for self-heal + date-fill) ─────────────────
#
# A self-healed selector (gap #5) or a calendar day-cell (gap #3) is a RE-LOCATION
# of the intended fillable field. It must never resolve onto a submit /
# account-create / final-submit control — the review-before-submit / pre-fill
# stop-boundary (``core/rules/prefill_boundary.py``) is untouched by recovery. This
# guard is the server-side refusal: if a recovered target looks like such a control,
# the caller refuses to act on it (issue #351 safety).

#: Case-insensitive identity markers of a submit / account-create / final-submit
#: control. A recovered / re-located target whose identity matches one of these is
#: refused so the stop-boundary can never be crossed by a retarget.
_BOUNDARY_CONTROL_MARKERS: tuple[str, ...] = (
    "submit",
    "sign up",
    "signup",
    "sign-up",
    "create account",
    "create-account",
    "createaccount",
    "register",
    "apply now",
    "apply-now",
    "send application",
    "submit application",
    "review and submit",
    "confirm and submit",
    "finish and submit",
    "final submit",
)

#: ``type`` values that are inherently submit controls (never a fill target). ``button``
#: is deliberately EXCLUDED — a calendar day is often ``<button>7</button>`` — so a bare
#: button is judged by its identity text, not its tag.
_SUBMIT_INPUT_TYPES: frozenset[str] = frozenset({"submit", "image", "reset"})


def _element_identity_text(element: Any) -> str:
    """Concatenate an element's identity-bearing attributes + visible text (lowercased).

    Defensive: any attribute/text read that raises is skipped so the guard never
    crashes the fill loop.
    """
    parts: list[str] = []
    for attr in (
        "type", "id", "name", "value", "aria-label",
        "data-automation-id", "data-testid", "title", "role",
    ):
        try:
            v = element.get_attribute(attr)
        except Exception:
            v = None
        if v:
            parts.append(str(v))
    for reader in ("inner_text", "text_content"):
        fn = getattr(element, reader, None)
        if callable(fn):
            try:
                t = fn()
            except Exception:
                continue
            if t:
                parts.append(str(t))
            break
    return " ".join(parts).lower()


def is_boundary_control(element: Any) -> bool:
    """True if ``element`` looks like a submit / account-create / final-submit control.

    Pure + defensive. A self-heal recovery (gap #5) or a calendar day-click (gap #3)
    that resolves to such a control is REFUSED so the review-before-submit / pre-fill
    stop-boundary is never crossed by a retarget. ``None`` is not a control.
    """
    if element is None:
        return False
    try:
        typ = (element.get_attribute("type") or "").strip().lower()
    except Exception:
        typ = ""
    if typ in _SUBMIT_INPUT_TYPES:
        return True
    text = _element_identity_text(element)
    return any(marker in text for marker in _BOUNDARY_CONTROL_MARKERS)


@dataclass
class HealResult:
    """Outcome of a self-heal attempt on a fill selector."""

    selector: str | None
    """The selector to fill — original when still valid, a healed alternative when
    recovered, or ``None`` when nothing usable/safe was found."""

    healed: bool = False
    """True when ``selector`` is a RECOVERED alternative (differs from the original)."""

    refused: bool = False
    """True when recovery found a target but it resolves to a stop-boundary control,
    so the caller must NOT act on it."""

    reason: str = ""
    """Human-readable detail (strategy used, or refusal cause)."""


def heal_fill_selector(
    page: Any,
    selector: str,
    field_label: str | None = None,
    *,
    wait_config: AdaptiveWaitConfig | None = None,
) -> HealResult:
    """Self-heal a broken/stale fill selector on the DEFAULT deterministic path.

    Returns the ORIGINAL selector when it still resolves; otherwise runs
    :func:`recover_broken_selector` and returns a healed alternative — but ONLY when
    that alternative does NOT resolve to a submit / account-create / final-submit
    control (the pre-fill stop-boundary). A recovery that would land on such a control
    is REFUSED (``refused=True``), so the boundary can never be crossed by a retarget.

    This never fills anything itself — it only decides WHICH selector (if any) is a
    safe, intended fill target. The caller does the deterministic fill by
    attribute-id (no free-form literal injection).
    """
    # 1. Is the original selector still present? (fast path — one lookup.)
    try:
        el = page.query_selector(selector)
    except Exception:
        el = None
    if el is not None:
        try:
            visible = el.is_visible()
        except Exception:
            visible = True
        if visible:
            # A re-rendered page could point the original selector at a submit
            # control; refuse rather than fill onto the boundary.
            if is_boundary_control(el):
                return HealResult(
                    selector=None,
                    refused=True,
                    reason="original selector resolves to a stop-boundary control",
                )
            return HealResult(selector=selector, healed=False, reason="selector intact")

    # 2. Original is broken/stale — recover.
    result = recover_broken_selector(
        page, selector, field_label, wait_config=wait_config
    )
    if not result.recovered:
        return HealResult(
            selector=None, healed=False, reason="no recovery candidate found"
        )
    alt = result.alternative_selector or selector
    # 3. Boundary guard on the recovered target — the safety-critical refusal.
    try:
        alt_el = page.query_selector(alt)
    except Exception:
        alt_el = None
    if is_boundary_control(alt_el):
        return HealResult(
            selector=None,
            refused=True,
            reason=f"healed selector {alt!r} resolves to a stop-boundary control",
        )
    strategy = result.attempts[-1].strategy if result.attempts else "recovered"
    healed = alt != selector
    return HealResult(
        selector=alt,
        healed=healed,
        reason=f"recovered via {strategy}" if healed else "selector loaded late",
    )


# ── Native calendar / date-picker widgets (gap #3) ─────────────────────────
#
# Workday / Greenhouse date fields (start date, DOB) that render a JS calendar grid
# rather than a typeable <input> cannot be filled by typing. These helpers detect
# such a widget and drive it by clicking month-nav + the target day cell — the fill
# stays by the intended field (never a submit control, guarded above).

#: Identity markers that (together with a calendar signal) mark a date field.
_DATE_FIELD_MARKERS: tuple[str, ...] = ("date", "calendar", "datepicker", "birth")

#: Explicit calendar-widget class/id/automation signals (any one is sufficient).
_CALENDAR_WIDGET_MARKERS: tuple[str, ...] = ("datepicker", "calendar", "date-picker")

_MONTHS: dict[str, int] = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
_MONTH_NAMES: tuple[str, ...] = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

#: Header text carrying the currently-displayed month/year of an open calendar.
_CALENDAR_HEADER_SELECTORS: tuple[str, ...] = (
    ".datepicker-switch",
    ".react-datepicker__current-month",
    "[data-automation-id='datePickerHeader']",
    "[class*='calendar'] [class*='title']",
    "[class*='datepicker'] [class*='header']",
    "[role='grid'] [aria-live='polite']",
)
_CALENDAR_NEXT_SELECTORS: tuple[str, ...] = (
    ".react-datepicker__navigation--next",
    "[data-automation-id='nextMonth']",
    "button[aria-label*='next' i]",
    ".next",
    "th.next",
)
_CALENDAR_PREV_SELECTORS: tuple[str, ...] = (
    ".react-datepicker__navigation--previous",
    "[data-automation-id='prevMonth']",
    "button[aria-label*='prev' i]",
    ".prev",
    "th.prev",
)
_CALENDAR_DAY_SELECTORS: tuple[str, ...] = (
    "[role='gridcell']",
    "td.day",
    ".react-datepicker__day",
    "[class*='calendar'] [class*='day']",
)
#: A day cell belonging to an adjacent (previous/next) month — must be skipped so a
#: "7" from the trailing month is not clicked instead of the target month's "7".
_OUTSIDE_MONTH_MARKERS: tuple[str, ...] = (
    "outside", "othermonth", "other-month", "adjacent", "muted", "old", "new",
)


def is_datepicker_element(element: Any) -> bool:
    """True if ``element`` is a JS calendar / date-picker trigger (no typeable input).

    Affirmative signal required so a normal typeable ``<input type=date>`` / text date
    input is NOT hijacked: either an ``aria-haspopup`` dialog/grid on a date field, an
    explicit ``datepicker``/``calendar`` class/automation id, or a READONLY date field
    (which only opens a calendar). Pure + defensive.
    """
    if element is None:
        return False

    def attr(name: str) -> str:
        try:
            return (element.get_attribute(name) or "")
        except Exception:
            return ""

    def has(name: str) -> bool:
        try:
            return element.get_attribute(name) is not None
        except Exception:
            return False

    identity = " ".join(
        attr(a)
        for a in ("id", "name", "class", "data-automation-id", "aria-label",
                  "placeholder", "type")
    ).lower()
    # Explicit calendar widget marker anywhere in the identity.
    if any(k in identity for k in _CALENDAR_WIDGET_MARKERS):
        return True
    has_date_marker = any(m in identity for m in _DATE_FIELD_MARKERS)
    if not has_date_marker:
        return False
    haspopup = attr("aria-haspopup").lower()
    if haspopup in ("dialog", "grid"):
        return True
    readonly = has("readonly") or attr("aria-readonly").lower() == "true"
    return readonly


def parse_target_date(value: str) -> tuple[int, int, int] | None:
    """Parse ``value`` into ``(year, month, day)``; ``None`` if unrecognised.

    Accepts ISO ``YYYY-MM-DD`` (the normalized stored form), ``MM/DD/YYYY``, and
    ``Month D, YYYY``. Kept tolerant but never guesses an ambiguous form.
    """
    import re as _re

    v = (value or "").strip()
    m = _re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", v)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (y, mo, d) if 1 <= mo <= 12 and 1 <= d <= 31 else None
    m = _re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", v)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (y, mo, d) if 1 <= mo <= 12 and 1 <= d <= 31 else None
    m = _re.match(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$", v)
    if m:
        mo = _MONTHS.get(m.group(1).lower())
        if mo:
            d, y = int(m.group(2)), int(m.group(3))
            return (y, mo, d) if 1 <= d <= 31 else None
    return None


def _parse_header_month(text: str) -> tuple[int, int] | None:
    """Parse an open calendar's header text into ``(year, month)``."""
    import re as _re

    t = (text or "").strip().lower()
    if not t:
        return None
    m = _re.search(r"(\d{4})[-/](\d{1,2})", t)  # 2026-07 / 2026/07
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return (y, mo)
    m = _re.search(r"([a-z]+)\.?\s+(\d{4})", t)  # July 2026 / Jul 2026
    if m:
        mo = _MONTHS.get(m.group(1))
        if mo:
            return (int(m.group(2)), mo)
    return None


def _first_present(page: Any, selectors: tuple[str, ...]) -> Any:
    """Return the first element found for any of ``selectors``, else ``None``."""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
        except Exception:
            el = None
        if el is not None:
            return el
    return None


def _calendar_current_month(page: Any) -> tuple[int, int] | None:
    """Read the month/year an open calendar is currently displaying."""
    el = _first_present(page, _CALENDAR_HEADER_SELECTORS)
    if el is None:
        return None
    text = ""
    for reader in ("inner_text", "text_content"):
        fn = getattr(el, reader, None)
        if callable(fn):
            try:
                text = fn() or ""
            except Exception:
                text = ""
            if text:
                break
    if not text:
        try:
            text = el.get_attribute("aria-label") or ""
        except Exception:
            text = ""
    return _parse_header_month(text)


def _cell_is_outside_month(cell: Any) -> bool:
    """True if a day cell belongs to an adjacent month (must be skipped)."""
    try:
        if (cell.get_attribute("aria-disabled") or "").lower() == "true":
            return True
    except Exception:
        pass
    try:
        cls = (cell.get_attribute("class") or "").lower()
    except Exception:
        cls = ""
    return any(m in cls for m in _OUTSIDE_MONTH_MARKERS)


def choose_date(
    page: Any,
    selector: str,
    value: str,
    *,
    boundary_guard: Any = is_boundary_control,
    max_nav: int = 480,
) -> bool:
    """Open the calendar at ``selector`` and click the day cell for ``value``.

    Navigates month-by-month to the target month/year, then clicks the matching day
    IN the displayed month (adjacent-month cells are skipped). ``boundary_guard`` is
    applied to the day cell so a control masquerading as a cell is never clicked —
    the stop-boundary holds even here. Returns True iff a day was clicked.
    """
    target = parse_target_date(value)
    if target is None:
        return False
    ty, tm, td = target
    trigger = None
    try:
        trigger = page.query_selector(selector)
    except Exception:
        trigger = None
    if trigger is None:
        return False
    try:
        trigger.click()  # open the calendar popup
    except Exception:
        return False

    # Navigate to the target month/year.
    for _ in range(max_nav):
        cur = _calendar_current_month(page)
        if cur is None:
            break  # header unreadable — try to click the day in what is shown
        if cur == (ty, tm):
            break
        direction = _CALENDAR_PREV_SELECTORS if (ty, tm) < cur else _CALENDAR_NEXT_SELECTORS
        nav = _first_present(page, direction)
        if nav is None:
            break
        try:
            nav.click()
        except Exception:
            break

    # Click the target day in the displayed month.
    want = str(td)
    for sel in _CALENDAR_DAY_SELECTORS:
        try:
            cells = page.query_selector_all(sel)
        except Exception:
            cells = []
        for cell in cells:
            try:
                if not cell.is_visible():
                    continue
            except Exception:
                pass
            if _cell_is_outside_month(cell):
                continue
            try:
                txt = (cell.inner_text() or "").strip()
            except Exception:
                continue
            if txt != want:
                continue
            # Safety: never click a submit/account-create control disguised as a cell.
            if boundary_guard is not None and boundary_guard(cell):
                continue
            try:
                cell.click()
                return True
            except Exception:
                continue
    return False
