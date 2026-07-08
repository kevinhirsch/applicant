# P1-2 — Real-board pre-fill proof runs (dry-run only)

**Date:** 2026-07-08 · **Backlog:** P1-2 · **Owner decision:** issue #719

> **Scope set by the owner (issue #719): dry-run ONLY, no employer trial accounts.**
> Automation may run against real ATS boards but MUST stop at the review boundary —
> pre-fill, never submit. The engine's review-before-submit + pre-fill stop-boundary
> core rules enforce this; these proof runs respect and demonstrate it. **No final
> submit was ever attempted anywhere.**

This is the honest H-series ledger of what ran **live** in this environment versus
what is **procedure-only** (encoded for the Integration Lane / a deploy box). Read
the "What ran live" and "What is procedure-only" sections before citing anything.

---

## What ran live (in this environment)

### 1. Real browser stack detects real-board form fields (FR-PREFILL-2/3)

The engine's production driver (`PlaywrightPageSource`, patchright + Chromium,
headless) was launched and driven against the **genuine DOM of two live ATS
postings**. Because a launched browser cannot tunnel this sandbox's egress proxy
(see "Findings" #2), the real board markup was captured out-of-band with `curl`
(which the proxy does pass) and replayed into the **same real browser** via
`set_content` — the identical technique `tests/integration/test_real_browser.py`
uses to keep the SSRF guard intact. The detection engine, the field classifier, and
the stop-boundary predicates that ran are exactly the production ones.

| Target | Board | Live posting | Fields detected | Field types | Stop boundary |
|---|---|---|---|---|---|
| `greenhouse-figma` | Greenhouse | Figma — Account Executive (Berlin) | **15** | 7 text, 1 tel, 1 file (résumé), 1 textarea, 5 listbox | respected |
| `lever-gopuff` | Lever | Gopuff posting | **81** | 2 file, 9 text, 1 email, 2 select, 38 radio, 13 checkbox, 16 hidden | respected |

Both runs detected the real fields a human would fill — name, email, phone, résumé
attachment, LinkedIn/portfolio, custom free-text questions, EEO/demographic and
work-authorization questions — including Greenhouse's custom `aria-haspopup="listbox"`
dropdowns (the Workday-shaped widget the plain input/select query would miss) and
Lever's radio/checkbox EEO block.

**Stop boundary:** neither run reached a post-submission **confirmation** page
(`is_confirmation_page == False`), which is the only signal a submit actually fired.
Both pages **are** a "final-submit page" (`is_final_submit_page == True`) — see
Finding #1: on single-page boards that is the *pre-fill terminus*, the expected place
the engine stops and hands off to review, not a violation. No value was typed and no
button was clicked; the harness performs detection only.

**Artifacts (this directory):**
- `evidence.json` — full per-target record: every detected field's selector, label,
  and type; the boundary flags; the state trace; `typed_any_value:false`,
  `submitted:false`.
- `greenhouse-figma.png`, `lever-gopuff.png` — screenshots of the real board DOM
  rendered in the real browser (unstyled — cross-origin CSS/JS can't load offline;
  the substantive evidence is the field inventory in `evidence.json`).
- `dom/greenhouse-figma.html`, `dom/lever-gopuff.html` — the captured real-board DOM
  snapshots, **re-usable as form-fill regression fixtures** (the harness `dom` mode
  replays them; see "Reproduce").

**Reproduce:**
```bash
uv sync --extra browser && uv run patchright install chromium
DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
  uv run python scripts/proof/ats_dryrun_proof.py dom \
    --label greenhouse-figma \
    --dom docs/proof/p1-2/dom/greenhouse-figma.html \
    --source-url "https://job-boards.greenhouse.io/figma/jobs/5364702004" \
    --out docs/proof/p1-2
# (repeat with --label lever-gopuff --dom docs/proof/p1-2/dom/lever-gopuff.html ...)
```

### 2. The model-backed portion of the loop, against a real provider

The loop's non-deterministic steps (free-text answers, material tailoring,
parse-verify) call the model through the engine's production
`OpenAICompatibleLLM` tier ladder. Using the owner's live provider key (sourced into
the environment, never printed or committed), one loop-representative completion ran
end to end: a benign application free-text answer assembled from stored résumé facts.

- Provider reached, tier 1 used, provider-reported usage returned
  (`tokens_in`/`tokens_out`), ~1.8 s round trip, coherent truthful reply that used
  only the supplied facts.
- Harness: `scripts/proof/live_model_probe.py` (reads `OPENROUTER_API_KEY` and
  `OPENROUTER_MODEL` from env only — no credential or model id is committed).

### 3. The post-approval half of the loop, hermetically (what live can't cover)

The parts the owner decision puts out of live reach — human approve → final submit →
confirmation detected → tracker updates — are pinned by the hermetic loop suite over
`FakePageSource` (which models a full ATS page sequence including the confirmation
page and tracker write). This proves the engine reaches `AWAITING_FINAL_APPROVAL`
and **cannot self-authorize the final submit**.

```bash
DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
  uv run pytest -q -m "not integration" \
    tests/unit/test_prefill_service.py \
    tests/unit/test_final_say_invariant.py \
    tests/unit/test_loop_end_to_end.py
# 62 passed
```

---

## What is procedure-only (needs a deploy box / the Integration Lane)

These could not run **live** in this sandbox and are encoded for the Integration Lane
(`.github/workflows/ci-integration.yml`, `workflow_dispatch` with `ats_dry_run_url`,
+ weekly) and a real deploy box:

1. **Live browser *navigation* to a real board.** A launched Chromium cannot complete
   TLS through this sandbox's egress proxy — every external host (including
   `example.com`) returns `net::ERR_CONNECTION_RESET`, while `curl` through the same
   proxy succeeds. So live navigation is replaced here by the curl-capture + real-browser
   replay above. On a deploy box with direct egress, run the same detection live:
   ```bash
   APPLICANT_ATS_DRY_RUN_URL="https://job-boards.greenhouse.io/figma/jobs/5364702004" \
     xvfb-run -a uv run pytest -m integration tests/integration/test_ats_prefill_dryrun.py -v
   # or: uv run python scripts/proof/ats_dryrun_proof.py live --label <name> --url <posting>
   ```
2. **Workday.** `www.myworkdayjobs.com` is denied by this session's egress policy
   (gateway 502 to CONNECT) even for `curl`, so no Workday snapshot was captured. Per
   P4-DEC-2, Workday pre-fill is proven via the takeover/CDP path on a deploy box.
3. **Stealth stack under real network (FR-STEALTH).** Camoufox headful-on-Xvfb was
   **not** exercised (binary not fetched; no live browser egress). The Chromium path
   launched and rendered here; the coherent-fingerprint live check is
   `tests/integration/test_real_browser.py::test_real_browser_identity_is_coherent_real_linux_chrome`,
   run in the Integration Lane under Xvfb.
4. **The submit → confirmation → tracker leg, live.** Out of scope by owner decision
   #719 (no employer trial accounts, no submit). Covered hermetically (section 3);
   would need self-owned test postings to demonstrate live.

---

## Findings

1. **`is_final_submit_page()` is a page classifier, not a boundary violation.**
   On single-page boards (Greenhouse, Lever) the fields and the "Submit application"
   button share one page, so `is_final_submit_page()` is legitimately `True` on the
   pre-fill terminus — the page where the engine stops for review. The real crossing
   signal is `is_confirmation_page()`. **Fixed:** `tests/integration/test_ats_prefill_dryrun.py`
   asserted `not is_final_submit_page()`, which would false-alarm on every Greenhouse/
   Lever run; it now asserts `not is_confirmation_page()` and logs the terminus signal
   informationally. Severity: medium (would have failed the live lane on the two most
   common boards). The proof harness uses the corrected semantics.
2. **Launched-browser egress is blocked by the sandbox proxy** (env limitation, not a
   product defect). `curl` tunnels the proxy; Chromium's TLS through it resets. Logged
   so the deploy-box/Integration-Lane live navigation is a known follow-up, not a
   silent gap.

---

## Honesty statement (H-series)

Live in this environment: the real browser stack detecting real-board fields on two
targets, the stop boundary (no confirmation reached, nothing typed/submitted), and one
real model call through the engine adapter. Hermetic (not live): the post-approval
submit→confirmation→tracker leg. Not run here (procedure-only, above): live browser
navigation, Workday, and the Camoufox stealth stack under real network. This split is
why P1-2 is marked **PARTIAL**, not DONE.
