# Skyvern Parity Gap Analysis

**Status:** Complete  
**Issue:** #351  
**Date:** 2025-06-29

## Methodology

Analyzed Skyvern's open-source capabilities (AGPL — reference only, no code reuse)
against Applicant's current adapter surface (`page_source.py`, `prefill_service.py`,
`ats.py`, `detection_monitor.py`). The goal is feature parity for autonomous form-filling.

## Gap Inventory

| # | Gap | Current state | Skyvern approach | Impact | Effort |
|---|---|---|---|---|---|
| 1 | **Multi-page flow as one plan** | Engine walks pages one at a time via advance() | Plans the whole flow; navigates multi-step wizards as one reasoning unit | High — cuts per-page LLM calls | Medium |
| 2 | **Iframe/Shadow DOM penetration** | Detects fields only in top-level DOM | Recursively enters iframes and shadow roots to find all fields | High — many ATS (Workday, Taleo) render fields in iframes | Medium |
| 3 | **Dynamic element waiting + auto-retry** | Static wait_for_load_state with 10s timeout | Adaptive waits + element staleness detection + auto-retry on navigation mismatch | High — SPA transitions often time out | Low |
| 4 | **Form structure inference** | Relies on AtsAdapter page model + DOM heuristics | Infers form structure from field labels, groupings, required markers | Medium — reduces adapter maintenance | Medium |
| 5 | **CAPTCHA/challenge classification** | Rule-based (URL/text markers) | Vision + DOM-based classification of challenge types (Turnstile, reCAPTCHA, hCaptcha, FunCaptcha) | Medium — reduces false negatives | High |
| 6 | **Error recovery on wrong-page navigation** | advance() returns None on failure | Re-plans from current URL when expected page doesn't match | Medium — prevents silent failures | Low |
| 7 | **PDF/OCR-extracted field mapping** | Not supported | Extracts and maps fields from embedded PDF forms | Low — rare in modern ATS | High |
| 8 | **Workday-specific portal registry** | Generic ATS adapter pattern | Pre-mapped field trees per Workday tenant | Low — worth a registry pattern | Low |
| 9 | **Credential auto-rotation** | Static ADR-0004 predefined credential | Skyvern detects credential expiry and rotates | Low — ADR-0004 covers account creation | Low |

## Top 3 Gaps for Implementation

### Gap 1: Iframe/Shadow DOM penetration (HIGH IMPACT)

**Problem:** Many ATS platforms (Workday, SAP SuccessFactors, Taleo) render form
fields inside nested iframes or shadow DOM roots. The current `PlaywrightPageSource`
detects fields via `page.locator('input, select, textarea, [role=combobox]')` which
only sees the top-level document.

**Solution:** Add recursive frame+shadow traversal to `detect_fields()` in
`PlaywrightPageSource`. The implementation uses Playwright's `frame_locator` and
`shadow` piercing utilities.

### Gap 2: Dynamic element waiting + auto-retry (MEDIUM IMPACT)

**Problem:** The current `advance()` method uses a fixed 10s
`wait_for_load_state("networkidle")` timeout, which fails on SPA-heavy ATS that
never reach networkidle. No retry/recovery on navigation mismatch.

**Solution:** Add adaptive waiting with progressive timeout, retry on stale
elements, and URL-change detection with replan fallback.

### Gap 3: Error recovery on wrong-page navigation (MEDIUM IMPACT)

**Problem:** When advance() navigates to an unexpected page (e.g., "we're reviewing your
application" interstitial, SSO redirect loop, error page), the engine currently has no
recovery path and records the mismatch silently.

**Solution:** Add URL verification after every navigation op with a recovery state
machine: detect wrong page → retry → re-plan → hand off.
