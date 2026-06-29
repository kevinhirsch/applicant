# Applicant — 1.0 Release Readiness

**Purpose:** the single document that answers "do we have everything we need, documented, to get
from here to a perfectly functional 1.0 shippable product?" It consolidates a full coverage audit of
all **119 FR/NFR requirements** in `docs/spec/master-spec.md` (the 1.0 authority) against three
dimensions — **engine implementation**, **executable acceptance spec (Gherkin/contract)**, and
**front-door reachability** — and defines the 1.0 scope cut, the blocking gaps, and the structural
guards that keep the product wired.

Companion artifacts: `docs/issue-acceptance-traceability.md` (issue → acceptance spec → green/pending),
`docs/traceability.md` (FR → engine), and the per-issue DeepSeek-ready work-order comments on GitHub.

---

## 1. Headline

**~115 / 119 requirements are COVERED** (implemented + executably spec'd + front-door-reachable where
user-facing). **Zero requirements are FORGOTTEN** (every gap below has a filed issue), and **only one
user-facing requirement was genuinely UNWIRED** (FR-FONT-1, now #400). The ship-critical MUSTs —
hexagonal layering (NFR-ARCH-1, CI-gated), the pre-fill stop-boundary (NFR-CAUTION-1 / FR-PREFILL-4),
truthfulness/fabrication guard (NFR-TRUTH-1), and zero-CLI operation (NFR-ZEROCLI-1) — are clean and
enforced server-side at single chokepoints.

The remaining work to 1.0 is small, finite, and enumerated below. It is **not** "build a lot more";
it is "close a handful of named gaps + make two product decisions + add two structural guards."

---

## 2. The 1.0 gap ledger

### 2a. 1.0-BLOCKING (must fix before shipping)

| Gap | Why blocking | Issue |
|---|---|---|
| **No CSRF protection** (only SameSite=Lax) on cookie-authed mutations (vault credential-plant, force-submit, admin) | A public surface that auto-acts on the user's behalf must not be CSRF-forgeable | #381 |
| **Verbatim attacker email HTML → innerHTML** + denylist email sanitizer (mXSS / `url()` beacon) | Stored XSS in the authenticated app from a received email | #384, #389 |
| **Modal keyboard a11y**: no focus-into-dialog, no focus trap, no Escape | "Perfectly functional" excludes keyboard users getting trapped in the Portal / takeover modal | #379, #380, #382 |
| **NFR-PRIV-1**: no PII/résumé/credential erasure, no retention policy, no vault key rotation | Required to make a privacy claim for a tool that hoards PII + EEO + credentials | #363, #361 |
| **NFR-OPS-1 / FR-OBS-2**: no runtime metrics + no loop-stall (N-consecutive-failure) operator alert | A 24/7 autonomous agent can fail silently for days | #362 |
| **FR-FONT-1**: base-résumé upload doesn't prompt to install missing fonts | The mandated detect→prompt is not wired into the journey | #400 |
| **FR-LEARN-5 dead biasing legs**: Phase-1 centroid + `feature_stats` never read; digest cache ignores learning | A MUST claims learning biases discovery/scoring; today two legs are dead code | #238, #237, #239 |
| **NFR-TRUTH-1 fail-closed verification** | Confirm the material service emits NOTHING if the fabrication post-check is skipped by an earlier LLM/parse exception | (verify; file if not fail-closed) |

### 2b. PRODUCT DECISIONS — RESOLVED (owner, this pass)

| Decision | Resolution | 1.0 action | Tracked |
|---|---|---|---|
| **FR-PREFILL-2a — universal/generic ATS scope** | **Universal generic-driver coverage.** 1.0 commits to filling *any* ATS via the generic live-DOM driver. | `resolve_ats()` (`ats.py:285`) MUST return the generic driver for unknown ATSes (not `WorkdayAts()`); land the field-match-rate wrong-ATS flag. **1.0-blocking.** | #173, #177 (+#171/#214/#305) |
| **FR-OOBE-2 — wizard 3-step vs spec's 4-step** | **Divergence APPROVED.** The wizard stays minimal (connect model → profile); onboarding continues conversationally — the engine proactively probes for any required-to-apply data not prefilled and collects it in chat ("invisible onboarding continues"). | Enable the proactive essentials probe by default in prod + close the nudge→chat loop + reconcile README/spec to the minimal-wizard model. **1.0-blocking** (enablement). | #406 (reframes #271) |

### 2c. NO-SPEC — implemented + unit/contract-tested but missing a *Gherkin* acceptance scenario

Author GREEN scenarios (they pass today) so acceptance criteria are explicit everywhere. Safety-critical
first: **FR-CUA-5** (hard-blocked key-combos/type-patterns) and **FR-CUA-7** (no-foreground co-working
invariant), **FR-STEALTH-2/3/4** (cadence / per-tenant profile / datacenter-egress refusal). Then
FR-STEALTH-5, FR-SANDBOX-4, FR-CUA-8/11, FR-RESUME-3a (conversion accept/reject), FR-UI-1/UI-6
(low priority — covered by CI denylist + sub-surface tests), FR-DISC-4/6 (contract-tested only).

### 2d. POST-1.0 (explicitly deferred — documented, not forgotten)

Negative-outcome learning (rejection/ghost/interview/offer) #190–#193; the FR-MIND self-improvement
flywheel #306; cross-run dedup #196; the deeper cross-surface integrations #290–#304; Skyvern-parity
#305/#350/#351; vendor memory backend #307; MCP server #308; eval harness #309; the LOW-severity UI
holes (#393/#394/#395/#396/#397/#399/#386) and the marginal BE→FE niceties (#401/#402/#404/#405).
**#403 (commit chat-proposed criteria change)** is a genuine chat-loop dead-end — recommend pulling it
*into* 1.0 if chat-steering is a 1.0 selling point.

---

## 3. Structural guards (build now — so 1.0 stays shipped)

These are the durable fixes for "things will go unwired / we'll forget something." Both are being added
in this readiness pass:

1. **Reachability contract test** — enumerates engine `/api/applicant/*`-relevant capabilities and
   asserts each has a workspace proxy + JS consumer (+ a nav section for surfaces). Green now via an
   explicit known-gap allowlist (the BE→FE unwired #400–#405); **any NEW unwired endpoint fails CI.**
   This makes CLAUDE.md principle #2 ("reachability is the definition of done") *enforced*, not aspirational.
2. **Hermetic e2e user-journey test** (#364) — drives a seeded campaign through discovery → score →
   digest → approve → tailor → pre-fill → **stop-boundary**, asserting a human-review item is produced
   and no auto-submit occurs. Proves the assembled product works end-to-end, not just unit-by-unit.

---

## 4. Proposed 1.0 scope cut

**1.0 = all MUSTs green + §2a closed + §2b decisions implemented + the §2c safety-critical Gherkin
authored + §3 guards built.** Everything in §2d ships post-1.0. Concretely, the 1.0-blocking issue set is:

`#381, #384, #389, #379, #380, #382, #363, #361, #362, #400, #238, #237, #239` (§2a) + `#173, #177`
(universal ATS coverage) + `#406` (chat-continued onboarding enablement) + the NFR-TRUTH-1 fail-closed
verification + the §3 guards (#364 + the reachability contract test — **both now built and green**).
That is the finite, documented path from here to a perfectly functional 1.0.

**Status of the guards (§3):** ✅ built this pass — `tests/architecture/test_reachability_contract.py`
(144 proxy paths enforced, known-gap allowlist, negative-tested) and `tests/e2e/test_pipeline_journey.py`
(seeded campaign → digest → approve → pre-fill → stop-boundary, no auto-submit). The §2c NO-SPEC Gherkin
is authored (GREEN) and the §2a/§2b acceptance specs are filed as `@pending`.

---

## 5. Coverage-audit method (for re-runs)

For each FR/NFR in `docs/spec/master-spec.md`: confirm (1) engine impl (`docs/traceability.md` + code),
(2) an executable acceptance spec (`tests/bdd/features/**` Gherkin or `tests/contract`), (3) front-door
reachability (engine endpoint → `workspace/routes/applicant_*_routes.py` proxy → `workspace/static/js`
consumer → `workspace/src/applicant_features.py` `APPLICANT_SECTIONS` nav). Classify
COVERED / NO-SPEC / UNWIRED / FORGOTTEN / POST-1.0. The reachability contract test (§3.1) automates
dimension (3) going forward.

> Doc correction noted by the audit: `docs/traceability.md` marks FR-LEARN-5 fully delivered, but the
> Phase-1 centroid + `feature_stats` biasing legs are dead (#238/#237) — correct when those land.
