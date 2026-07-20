# H1-H5 Honesty Invariant Re-audit: A0 Shell Surfaces (a0-applicant Plugin)

**Audit date:** 2026-07-20
**Scope:** a0-applicant plugin API proxies (`a0-applicant/api/*.py`) against the engine at `src/applicant/app/routers/*.py`
**Coverage:** All plugin proxies that mediate between the A0 shell UI and the Applicant engine

---

## H1 — Receipts, Not Narration

**Verdict: HOLDS**

**Definition:** Every number/claim is a projection of recorded actions, never an LLM narrating what it thinks it did.

### Evidence

All plugin API proxies use a pure `dispatch()` / `_forward()` pattern that calls the engine via `urllib.request.urlopen()` and returns the engine's response verbatim in a normalized envelope `{ok, status, data|error}`. The proxies never:
- Build prompts
- Call an LLM
- Derive state from multiple engine calls
- Fabricate or summarize engine responses

### Exact code references

| Plugin proxy | Actions | Engine route called | Pattern |
|---|---|---|---|
| `a0-applicant/api/health.py` (lines 40-51) | `capabilities` | `GET /api/health/capabilities` | Pure `_forward()` |
| `a0-applicant/api/chat.py` (lines 48-75) | `send`, `confirm`, `confirm_criteria` | `POST /api/chat/...` | Pure `_forward()` |
| `a0-applicant/api/documents.py` (lines 42-84) | `list`, `provenance`, `approve`, `decline`, `redline`, `snapshot` | `GET/POST /api/documents/...`, `GET /api/outcomes/...` | Pure `_forward()` |
| `a0-applicant/api/agent_runs.py` (lines 48-72) | `status`, `intent`, `list`, `run`, `pause`, `resume` | `GET/POST /api/agent-runs/...` | Pure `_forward()` |
| `a0-applicant/api/digest.py` (lines 44-90) | `get`, `recap`, `approve`, `decline` | `GET/POST /api/digest/...` | Pure `_forward()` |
| `a0-applicant/api/onboarding.py` (lines 38-70) | `state`, `section`, `complete` | `GET/POST /api/onboarding/...` | Pure `_forward()` |
| `a0-applicant/api/pending.py` (lines 44-91) | `list`, `count`, `resolve`, `snooze`, `resolve_bulk` | `GET/POST /api/pending-actions/...` | Pure `_forward()` |
| `a0-applicant/api/notifications.py` (lines 43-75) | `list`, `seen`, `deliver_now` | `GET/POST /api/notifications/...` | Pure `_forward()` |
| `a0-applicant/api/takeover.py` (lines 43-101) | `sessions`, `view_url`, `takeover`, `resume_*`, `handoff`, `final_approval` | `GET/POST /api/remote/...` | Pure `_forward()` |
| `a0-applicant/api/campaigns.py` (lines 44-94) | `list`, `create`, `update`, `clone`, `guardrails` | `GET/POST/PATCH /api/campaigns/...` | Pure `_forward()` |
| `a0-applicant/api/update_panel.py` (lines 41-52) | `status`, `trigger` | `GET/POST /api/update/...` | Pure `_forward()` |
| `a0-applicant/api/vault.py` (lines 45-90) | `list`, `add`, `delete`, `account`, `bank_account`, `rotate_key` | `GET/POST/DELETE /api/credentials/...` | Pure `_forward()` |
| `a0-applicant/api/audit.py` (lines 42-64) | `log`, `application_log` | `GET /api/__/audit-log/...` | Pure `_forward()` |
| `a0-applicant/api/dormant.py` (lines 34-43) | `list` | `GET /api/dormant-surfaces` | Pure `_forward()` |

### Gaps flagged

- **`features.py`** (`a0-applicant/api/features.py`) is the **exception** — it performs a client-side computation (`compute_features()` at lines 107-126) that fetches setup status AND dormant-surface status from the engine, then derives section states (`active`/`locked`/`configured`/`disabled`) in the plugin layer. This is client-side state derivation, not pure forwarding. See H5 GAP below.
- **Missing proxies**: The task specification mentions `synthesize.py`, `tunnel_proxy.py`, and `plugins.py` — these files **do not exist** in the codebase. Either the surfaces were never implemented or are handled differently.

---

## H2 — No Silent Underdelivery

**Verdict: HOLDS**

**Definition:** Every degrade is loud per-action — never ship a quiet generic result that reads as success.

### Evidence

1. **Error forwarding**: Every proxy's `_forward()` function has a catch-all `except Exception as e` (e.g., `health.py` line 36-37) that returns `{ok: False, status: 0, error: "ExceptionType: message"}`. Engine HTTP errors are caught by the `HTTPError` handler (e.g., `health.py` lines 34-35) and returned as `{ok: False, status: <code>, error: <body>}`. **No proxy ever swallows an error** and returns a fabricated success.

2. **Input validation errors**: Proxies return 400 with a descriptive message for missing required parameters (e.g., `documents.py` line 47-48: `"application_id required"`), not a silent empty response.

3. **Engine error propagation**: Every valid action path goes through `_forward()` — there is no code path that catches an engine error and returns success. Tested for all 14 proxies with 500/502/503/404/403/429/401/409 errors — all forward the error envelope correctly.

4. **Underdelivery vocabulary**: The engine's core underdelivery rules (`src/applicant/core/rules/underdelivery.py`) produce structured plain-language shortfall records (`prefill_shortfall()`, `discovery_shortfalls()`, `source_shortfall_message()`). These pass through `pending.py`'s `_forward()` unchanged to the UI. The `shortfall.summary` for a 7-of-10-field prefill reads: *"I filled 7 of the 10 fields I found; 1 failed to fill (Phone); 1 question needs your answer (Why us?); 1 left blank — double-check the form."* — the proxy does not touch this string.

### Exact code references

- Error handling: present in all `_forward()` functions across all proxies
- Input validation: `chat.py:54-56`, `documents.py:46-48`, `documents.py:52-54`, etc.
- Engine underdelivery: `src/applicant/core/rules/underdelivery.py`
- Proxy passthrough: `a0-applicant/api/pending.py`

### Gaps flagged

None. All proxies pass engine errors through faithfully.

---

## H3 — Full-Fidelity Review

**Verdict: HOLDS**

**Definition:** Before every submit the user sees the literal payload — not a summary. Reviewed-is-sent (byte-identical promote).

### Evidence

The snapshot proxy in `a0-applicant/api/documents.py` (lines 78-82) forwards the engine's `/api/outcomes/applications/{application_id}/snapshot` response verbatim. The engine router at `src/applicant/app/routers/outcomes.py` (`get_snapshot()`, lines 82-109) returns the complete payload including:
- `answers`: The literal filled form values (keyed by selector or label)
- `material_versions`: Document-to-variant mapping
- `materials`: Uploaded file records with paths
- `posting_url`: The real job posting URL
- `timestamp`: When captured
- `stage`: `"reviewed"` (pre-submit) or `"submitted"` (post-submit)

The `stage` field is the honesty marker: `"reviewed"` means "this is exactly what will be sent", `"submitted"` means "this is exactly what was sent" — byte-identical promote per H3. The proxy never summarizes or modifies the payload.

When no snapshot exists, the engine returns a 404 with `"No submission snapshot recorded for this application."` — this is forwarded verbatim, never replaced with an empty inventory.

### Exact code references

- Plugin proxy: `a0-applicant/api/documents.py` lines 78-82 (`snapshot` action)
- Engine route: `src/applicant/app/routers/outcomes.py` lines 82-109 (`get_snapshot()`)
- Existing H3 test: `tests/unit/test_h3_full_fidelity_review.py`
- Engine snapshot entities: `src/applicant/core/entities/submission_snapshot.py` (STAGE_REVIEWED, STAGE_SUBMITTED)

### Gaps flagged

None. The proxy is a pure pass-through for both the snapshot payload and the 404 no-snapshot state.

---

## H4 — Visible Provenance

**Verdict: HOLDS**

**Definition:** Each generated line traced to ground-truth source; unsourced = flagged, not hidden.

### Evidence

The provenance proxy in `a0-applicant/api/documents.py` (lines 51-55) forwards `GET /api/documents/{document_id}/provenance` from the engine verbatim. The engine router at `src/applicant/app/routers/documents.py` (`line_provenance()`, lines 226-233) calls `material.line_provenance_for_document()` which returns a structured response with:
- `checked`: Boolean — `False` with a `reason` when the document has no reviewable text
- `lines`: Array of line-level traces, each with `facts` containing `token`, `sources`, and `unsourced` flag

The engine returns `checked: false` with an explicit reason when provenance cannot be computed — the proxy never turns `checked: false` into a clean check. Unsourced facts arrive at the UI as `unsourced: True` — the proxy does not strip them.

Owner-gating is enforced by the engine's document service (not the plugin proxy), which scopes provenance lookups to the owner's campaign.

### Exact code references

- Plugin proxy: `a0-applicant/api/documents.py` lines 51-55 (`provenance` action)
- Engine route: `src/applicant/app/routers/documents.py` lines 226-233 (`line_provenance()`)
- Engine rule: `src/applicant/core/rules/truthfulness.py` (`trace_line_provenance()`)
- Existing H4 test: `tests/unit/test_line_provenance_h4.py`

### Gaps flagged

None. The proxy is a pure pass-through. The engine handles `checked: false` with reason, unsourced flagging, and owner-gating.

---

## H5 — Calibrated Copy

**Verdict: HOLDS with ONE GAP**

**Definition:** Every promise in the UI is audited against actual capability state.

### Evidence

The health proxy (`a0-applicant/api/health.py`) forwards the engine's capability report verbatim. The engine's `capabilities()` route at `src/applicant/app/routers/health.py` returns each capability with:
- `real`: Boolean — whether the component is genuinely available
- `label`: Plain-language name
- `fix`: Actionable fix copy when degraded (not a bare red dot)
- `load_bearing`: Whether the component is critical for automated work

Degraded capabilities (e.g., `browser.real: False`) are forwarded as-is — the proxy never upgrades them to "available." Version and `generated_at` are the engine's own stamp.

The engine-side H5 sweep (`tests/unit/test_h5_calibrated_copy.py`) checks overclaim patterns in engine shell files and string literals. This audit covers the plugin layer only.

### GAP flagged: `features.py` client-side derivation

**`a0-applicant/api/features.py`** performs client-side computation of section states. Its `compute_features()` function:
1. Fetches `GET /api/setup/status` from the engine
2. Fetches `GET /api/dormant-surfaces` from the engine
3. Derives per-section `state` (`active`/`locked`/`configured`/`disabled`) in the plugin layer using `_section_state()` (lines 74-89)

This derivation is transparent (it only uses engine data as inputs) and correctly reflects gating requirements, but it **breaks the pure-forwarding pattern** that every other proxy follows. The section states are client-computed, not engine-forwarded.

**Mitigating factors:**
- The derivation uses live engine data as its sole inputs (never hardcoded defaults)
- The computation informs UI presentational state (which nav buttons to show), not application correctness
- The engine is the single source of truth for the underlying data

**Recommendation:** Either (a) add an engine endpoint that returns the fully computed feature states, making the plugin a pure forwarder, or (b) move the feature-gating computation to an engine route and let the plugin call it as a single `_forward()`.

### Other findings

- **Missing proxies**: `synthesize.py`, `tunnel_proxy.py`, and `plugins.py` are mentioned in the task spec but do not exist in the codebase. If these surfaces are planned, the overclaim check should be applied to their UI strings before implementation.
- **Overclaim denylist**: The plugin's own UI strings (in `a0-applicant/webui/` and `a0-applicant/prompts/`) should be audited against the same denylist used in the engine-side H5 test. This current audit reviews the API proxies, not the static UI strings — a separate pass is needed for full coverage.

---

## Summary

| Invariant | Verdict | Key gap |
|---|---|---|
| H1 — Receipts, not narration | **HOLDS** | `features.py` does client-side derivation; missing proxy files |
| H2 — No silent underdelivery | **HOLDS** | None |
| H3 — Full-fidelity review | **HOLDS** | None |
| H4 — Visible provenance | **HOLDS** | None |
| H5 — Calibrated copy | **HOLDS WITH GAP** | `features.py` client-side state computation; plugin UI strings not audited |

### Remediation items

1. **P1** — Add engine endpoint `/api/features/sections` to compute section states, making `features.py` a pure `_forward()` proxy
2. **P2** — Audit static plugin UI copy (`a0-applicant/webui/`, `a0-applicant/prompts/`) against the H5 overclaim denylist
3. **P3** — Verify whether `synthesize.py`, `tunnel_proxy.py`, `plugins.py` surfaces are needed; if so, implement with H1-H5 compliance from day one
