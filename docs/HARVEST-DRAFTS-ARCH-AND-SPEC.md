# HARVEST-DRAFTS-ARCH-AND-SPEC.md — Ready-to-apply drafts (NOT yet applied)

> **Status:** Planning artifact. These are **proposed patches** for two gated mutations the survival plan
> defers — the NFR-ARCH-1 import-linter contract and the `master-spec.md`/`traceability.md` requirement
> folding. They are drafted and **validated read-only against the real import graph**, so accepting them is
> a trivial apply. **Nothing here is applied** to `pyproject.toml`, `.github/workflows/ci.yml`,
> `docs/spec/master-spec.md`, or `docs/traceability.md` — that mutation remains behind the authorization
> gate. Companion: `docs/HARVEST-WAVE-FEATURES.md` (the feature specs these implement).

---

## 1. Validated import-graph evidence (read-only, this audit)

Before drafting the contract I verified applicant's actual layering with read-only greps. The tree is
**already a near-perfect hexagon**:

| Edge checked | Result | Evidence |
|--------------|--------|----------|
| `core → application/adapters/app` | **clean** (0) | core imports nothing outward |
| `core → ports` | **clean** (0) | core is truly innermost/pure → the safety gates **cannot** be corrupted by IO deps |
| `ports → adapters/application/app` | **clean** (0) | — |
| `adapters → application.services/workflows` | **clean** (0) | adapters never drive use-cases (the critical invariant) |
| `application → app.routers/main/container/config` | **clean** (0) | — |
| `adapters → app` | **1 exception** | `adapters/storage/alembic/env.py:27` → `app.config.get_settings` (Alembic migration env; benign) |
| `application → adapters` (concrete) | **4 imports** (impurity) | `prefill_service.py:39`→`adapters.browser.ats`; `conversion_service.py:23-24`→`adapters.resume_parser`,`adapters.resume_tailoring`; `setup_service.py:21`→`adapters.storage.app_config_store` |

**Two findings that correct the original sub-auditor sketch (why read-only validation mattered):**

1. **The auditor's proposed "forbid any non-`container.py` module from importing the safety gates" rule is
   infeasible** — it would red-wall CI on commit one. The gates are *deliberately* called at the IO edge:
   `adapters/browser/patchright_browser.py:46` and `app/routers/remote.py:36` call
   `prefill_boundary.ensure_action_allowed`; `application/services/{material,submission}_service.py` call
   `review_gate.ensure_submittable`. That is correct enforcement, not a violation. **Import rules cannot
   express "you must CALL the gate" — only "who may import what."** Gate *purity* is already guaranteed by
   core being the innermost layer (verified clean); runtime *enforcement* stays the job of the existing
   tests + the new typed capability registry (`FR-HARVEST-CAPREG`).
2. **`application → adapters` is not independent today** (4 concrete imports). So a strict hexagonal
   `independence` contract between them would **fail now** without a small refactor. The draft handles this
   with a two-option design (green-now vs. target-state) below.

---

## 2. NFR-ARCH-1 — import-linter contract (draft `pyproject.toml` block)

### Option A — lands GREEN today (recommended for Wave 1)
A single total-order `layers` contract. In import-linter, higher layers may import lower; lower may **not**
import higher. Ordering `app > application > adapters > ports > core` **passes the current tree** with one
documented `ignore_imports` (the Alembic env). It guards the edges that matter: nothing imports `app`
except the composition root + the one migration exception; **adapters cannot drive `application.services`**
(the key inversion guard); `ports`/`core` stay pure. It tolerates the existing `application → adapters`
imports (they are "higher imports lower", allowed).

```toml
# [tool.importlinter] — DRAFT, validated read-only against the tree on this branch.
# dev dependency to add: import-linter
[tool.importlinter]
root_package = "applicant"

[[tool.importlinter.contracts]]
name = "Hexagonal layering (app > application > adapters > ports > core)"
type = "layers"
layers = [
    "applicant.app",
    "applicant.application",
    "applicant.adapters",
    "applicant.ports",
    "applicant.core",
]
# Benign, documented exception: the Alembic migration environment reads settings.
ignore_imports = [
    "applicant.adapters.storage.alembic.env -> applicant.app.config",
]

[[tool.importlinter.contracts]]
name = "Core domain is pure (rules import nothing outward)"
type = "forbidden"
source_modules = ["applicant.core"]
forbidden_modules = [
    "applicant.adapters",
    "applicant.application",
    "applicant.app",
]
# Verified: currently zero violations.
```

CI step (draft, for `.github/workflows/ci.yml`, beside ruff/pytest):
```yaml
      - name: Architecture — import-linter layering contract
        run: uv run lint-imports
```
Acceptance proof (run on a throwaway branch, do not commit): introduce
`app/routers/x.py` importing `applicant.application.services.prefill_service` *into* an adapter, or add an
`adapters/* -> application.services` import, and confirm `lint-imports` fails with a named broken contract.

### Option B — target state (stricter; needs a small refactor first)
To also forbid `application → adapters` (full hexagonal purity), add an `independence` contract **after**
routing the 4 concrete imports behind ports:
- `prefill_service.py:39` `adapters.browser.ats.{SCREENING_ESSAY,SCREENING_FACTUAL}` → move those constants
  to a `core`/`ports` location (they are domain constants, not adapter logic).
- `conversion_service.py:23-24` `ResumeParser`, `ModerncvConverter` → inject via existing ports.
- `setup_service.py:21` `adapters.storage.app_config_store` → access through a storage port.
```toml
[[tool.importlinter.contracts]]
name = "Application and adapters are independent (target state)"
type = "independence"
modules = ["applicant.application", "applicant.adapters"]
# NOTE: FAILS today (4 imports above). Enable only after the refactor.
```
**Recommendation:** ship **Option A** in Wave 1 (zero refactor, guards the critical inversion). File the
Option-B refactor as a follow-up hardening item; it is genuinely-better hexagonal hygiene but not load-bearing.

---

## 3. master-spec.md — requirement insertion blocks (draft, house style)

Proposed new subsection under §3 (or an appendix), matching the `**ID (MUST — title):** text` style. IDs are
provisional pending owner confirmation.

```markdown
### 3.N Harvest hardening — `FR-HARVEST` / `NFR-ARCH`

- **NFR-ARCH-1 (MUST — structurally enforced layer boundary):** The hexagonal layering MUST be enforced at
  build time by an import-linter contract gated in CI: `app > application > adapters > ports > core`, plus a
  `forbidden` contract keeping `core` pure (no outward imports). The single sanctioned exception is the
  Alembic migration environment reading `app.config`. This converts the "engine cannot self-authorize a
  final submit" guarantee from convention into a CI-enforced invariant (gate *purity*; runtime enforcement
  remains via tests + `FR-HARVEST-CAPREG`). Harvested from the dependency-cruiser pattern in `orwell`
  (MIT © 2026 kevinhirsch; pattern-only, no code copied).
- **FR-HARVEST-CAPREG (MUST — typed capability allowlist):** Each engine operation exposed through the
  front door MUST be registered in a frozen, typed registry carrying explicit `mutates_application`,
  `needs_human_review`, and `exposes_sensitive` flags, with a drift test that fails when an entry violates
  the declared invariants. Declarative only — the existing runtime gates remain the enforcers.
- **FR-HARVEST-PROVIDER (SHOULD — declarative multi-provider profiles):** Provider-specific quirks (auth,
  endpoints, vision, temperature handling, kwarg splits, per-model max-tokens, live model fetch) SHOULD be
  expressible as a declarative profile behind the existing `LLMPort`, **without** removing the
  capability-ranked tier ladder (`FR-LLM-3/4`) or defensive structured-output parsing (`FR-LLM-4a`). Adding
  a provider MUST NOT require transport-branch edits. Harvested pattern from `hermes-agent`
  (MIT © 2025 Nous Research). Gated on the white-label denylist (`hermes`/`nous` scoped excludes) + legal
  denylist (`hermes`/`nous` scoped excludes) — license gate dissolved (MIT ⊕ MIT).
- **FR-HARVEST-TRUTHTIER (SHOULD — graded fabrication downgrade):** The fabrication guard
  (`NFR-TRUTH`/`truthfulness.py`) SHOULD support a graded outcome: a claim not derivable from the
  candidate's true attributes MAY be downgraded to a capped-confidence **review flag** (surfaced for human
  review) rather than only hard-failing, never silently promoted. The hard-raise path for clear
  fabrications remains. Pattern from `orwell` (MIT © 2026 kevinhirsch).
- **FR-HARVEST-CARET (MAY — streaming caret affordance):** During token streaming the chat renderer MAY
  render an `aria-hidden` caret hugging the last character of the last block, removed on completion, not
  included in copied text. Front-door only (`markdown.js`), vanilla JS, no framework. Idea from
  `hermes-agent` (MIT © 2025 Nous Research).
- **NFR-OPS-1 (SHOULD — integration lane proof):** At least once, in a CI or staging lane, the system
  SHOULD exercise the real browser + real TeX render + a live ATS dry-run end-to-end, stopping at the
  review/pre-fill boundary (never a real final submit), producing a rendered-PDF + state-trace artifact —
  converting the skip-on-absent-dep integration tests from "wired" to "demonstrated."
```

(Note: `FR-HARVEST-FEPOLISH` and the denylist hardening are in-house/CI work, tracked in
`HARVEST-WAVE-FEATURES.md`; they need no new spec requirement — `FEPOLISH` serves existing `FR-UI`/`FR-OOBE`
and the denylist serves the existing white-label principle.)

---

## 4. traceability.md — matrix rows (draft)

Per the matrix's mandate (Requirement ID → WP → BDD Feature → adapter/contract test, plus front-door
reachability). Rows are **drafts**; tests/features cited are the ones the feature specs prescribe (to be
authored when the wave is implemented).

| Requirement | WP (wave) | BDD / Test anchor | Engine surface (target) | Front-door reachability |
|-------------|-----------|-------------------|--------------------------|--------------------------|
| NFR-ARCH-1 | Wave 1 | CI `lint-imports` step + `tests/architecture/test_layering` (marker) | `pyproject.toml` `[tool.importlinter]` | N/A (build-time guarantee protecting a reachable safety property) |
| FR-HARVEST-CAPREG | Wave 2 | `tests/.../test_capability_registry_drift` | engine op registry beside `require_automated_work` | the `/api/applicant/*` proxy boundary |
| FR-HARVEST-CARET | Wave 2 | front-door `test_applicant_*` chat smoke + playtest §6a visual | n/a (front-door) | chat surface (`applicantChat.js`) |
| FR-HARVEST-PROVIDER | Wave 3 | `LLMPort` contract tests + profile-table units | `adapters/llm/openai_compatible.py` behind `ports/driven/llm.py` | model-endpoint manager / `applicantModelLadder.js` |
| FR-HARVEST-TRUTHTIER | Wave 3 | extend `truthfulness` units (graded cases) | `core/rules/truthfulness.py` | review/redline (`documentLibrary.js`) |
| NFR-OPS-1 | Wave 4 | the `@pytest.mark.integration` suite run with deps present | `container.py` real wiring (browser/TeX) | front-door → engine → real-world chain (strongest reachability proof) |

---

## 5. What is still gated (not drafted as patches, deliberately)
- **Applying** any of §2/§3/§4 to the real files — needs authorization + (for §3) owner confirmation of the
  provisional IDs.
- **Attribution stub files** (`workspace/licenses/*-MIT-LICENSE.txt`, `ACKNOWLEDGMENTS.md` rows) — land in
  the same commit as the first real harvested code, not before (templates in `HARVEST-MAP.md` §C).
- **The Option-B refactor** (routing 4 application→adapters imports behind ports) — a follow-up, not Wave 1.
- **Attribution** for FR-HARVEST-PROVIDER/TRUTHTIER — add `workspace/licenses/` + `ACKNOWLEDGMENTS.md`
  row in the same commit as the first harvested code (MIT ⊕ MIT is clean; no legal gate remains).
