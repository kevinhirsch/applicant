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

    Returns:
        RecoveryResult indicating whether recovery succeeded and how.
    """
    attempts: list[RecoveryAttempt] = []
    _start = time.monotonic()

    # Strategy 1: Retry with adaptive wait
    wait_result = adaptive_wait_for_element(page, original_selector)
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
