# ADR-0007: License gate for third-party capability reuse (Skyvern AGPL → idea-only; CAPTCHA opt-in)

**Status:** Accepted. Records the licensing/strategy decisions made while acting on the domain
deep-research ([`docs/design/competitive-research.md`](../design/competitive-research.md)) and the
plan-as-data design ([`docs/design/plan-as-data.md`](../design/plan-as-data.md)). Tracked by epic
**#351** (Skyvern parity) and its legs **#305** (plan-as-data), **#306** (learning flywheel),
**#350** (CaptchaSolverPort).

> Not legal advice. The AGPL §13 scope and the "separate process = mere aggregation" boundary are
> somewhat untested; an actual relicensing or code-vendoring decision deserves real legal review.

## Context

The deep research surfaced many reusable projects. Two recurring questions need a durable, written
rule rather than a per-PR judgement call:

1. **What may we copy into the product vs only learn from?** Applicant is a self-hosted, white-label
   product (engine + front-door, both network-facing). The reuse candidates span permissive (MIT /
   Apache-2.0: browser-use, Stagehand, litellm, mem0, AgentLab) and strong-copyleft (AGPL-3.0:
   **Skyvern**) licenses.
2. **Skyvern is the sharp case.** It is the closest competitor to Applicant's pre-fill capability
   (vision+DOM form understanding, Workday/ATS focus) and the source of the recurring "can we just
   use their code / can we *finish CAPTCHA*?" question. It is **AGPL-3.0**, and its strongest
   anti-bot/CAPTCHA capability is reserved to their paid cloud (not in the open code).

## Decision

**1. License gate (the rule).**
- **MIT / Apache-2.0 ⇒ vendor-able** (`adopt-code`): may be copied/linked into the product, with the
  required notice recorded in repo-root `NOTICE` / `THIRD_PARTY_LICENSES.md`. (Apache-2.0 → MIT
  product is fine.)
- **AGPL-3.0 / GPL ⇒ idea-only** (`adopt-idea`): study the approach, re-implement clean from our own
  understanding; **do not copy, link, or close-paraphrase the code.** Copyleft would infect the
  combined work. Ideas/techniques are not copyrightable; the specific expression (code) is.
- Tag every reuse candidate `adopt-code` vs `adopt-idea` (the research report already does this).
- **License is verified before any code reuse**, including for permissive-looking projects whose
  license is unconfirmed (e.g. ApplyPilot — `verify` in the report).

**2. Do NOT relicense Applicant to AGPL to reuse Skyvern.** It is *technically* compatible (AGPL code
fits an AGPL product, and our MIT/Apache deps are one-way compatible into AGPL), but it is a one-way,
product-wide trade we decline:
- AGPL **§13 network clause** triggers immediately for both network-facing apps — every user who
  interacts over the network is owed the complete corresponding source of the running version.
- It **breaks the white-label/commercial posture**: every white-label deployer inherits the
  source-disclosure obligation, and competitors may self-host the exact product. AGPL is effectively
  irrevocable for released code.
- A GPL-2.0-only transitive dep would become *incompatible*, forcing an audit/removal.

**3. The isolated-AGPL-service boundary is considered and rejected for now.** Running Skyvern as a
separate AGPL service (own repo/container, own published source + our mods, talking to Applicant only
over an arm's-length network API) would contain the copyleft to that service. We decline it because,
for Applicant specifically, the *architectural* cost outlives the *legal* fix:
- **Two browser stacks that fight** — Applicant routes all automation through one anti-detect browser
  (camoufox) precisely for fingerprint coherence; a second, isolated stack cannot share that session
  and looks different from the rest of our traffic.
- **Autonomy-posture mismatch** — Skyvern is built to *complete* forms; Applicant is built to *stop*
  (review-before-submit, pre-fill stop-boundary, fabrication guard). Most of the integration effort
  would be constraining it back behind our gates.
- **AGPL friction is inherited by every white-label deployer** of that service.
- It remains *available* only as a deliberate, arm's-length, source-published service if a future
  need is strong enough — never as a thin in-process wrapper.

**4. Re-implement Skyvern's value clean.** The capability gaps close via license-clean work, tracked
under epic **#351**:
- Vision+DOM form understanding → **#305 plan-as-data** (DOM serializer ← browser-use MIT; act/extract/
  observe surface ← Stagehand MIT; planner/LLM ← litellm MIT).
- Broad ATS coverage that grows itself + self-healing → **#306** (AWM induction + ACE curation +
  Reflexion).
- CAPTCHA → **#350** (below). Skyvern is used as a *reference oracle* (observe its behaviour), never a
  dependency.

**5. CAPTCHA strategy (#350) — opt-in, safe-by-default.** A `CaptchaSolverPort` (driven) with three
adapters and a clear split:
- **Behavioral avoidance** (score-based systems: reCAPTCHA v3, Turnstile) — you do not "solve" these;
  you avoid the challenge by looking human (coherent fingerprint + human input cadence — *already
  shipped* via the stealth layer; this is the GREEN, low-risk, high-value half).
- **Solver-service** (challenge systems: reCAPTCHA v2, hCaptcha, FunCaptcha) — token injection via a
  third-party solver (CapSolver/2Captcha); requires residential egress for token acceptance.
- **Human hand-off** — the current stop-at-CAPTCHA behaviour; the **default and the backstop**.
- **Invariants:** solving never bypasses the final-submit stop-boundary; the solver API key is sealed
  in the credential vault and never logged; `CAPTCHA_STRATEGY` defaults to `human`.
- **ToS/legal caveat:** most job sites prohibit automated submission / CAPTCHA circumvention. For a
  user's *own* applications via a self-hosted tool this is a gray area (not fraud) but risks account/
  IP bans and theoretical ToS-circumvention exposure — hence opt-in and off by default. The
  solver-service leg lands separately, behind its flag, from the safe behavioral/hand-off legs.

## Consequences

- **Positive:** a written, repeatable rule for code reuse; the product keeps its MIT license and
  white-label/commercial flexibility; the Skyvern capability is bridged license-clean (#305/#306/#350)
  while honouring the stop-at-human-step safety posture.
- **Negative / cost:** re-implementing rather than vendoring Skyvern is more work than a copy would be
  (the price of staying license-clean and architecturally coherent). The CAPTCHA solver-service leg
  carries ongoing residential-egress cost and the ToS risk above.
- **License diligence:** keep `NOTICE` / `THIRD_PARTY_LICENSES.md` current for every vendored
  permissive dep; re-verify any `verify`-tagged project's license before reuse; the CI white-label
  denylist continues to gate shipped strings.
