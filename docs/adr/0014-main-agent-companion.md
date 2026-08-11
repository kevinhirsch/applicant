# ADR-0014: The main chat is a companion, not a command line

**Status:** Proposed (defines what `chat.html` / the campaign agent IS; the relationship layer over ADR-0010/0011/0012/0013).
**Numbering:** next free slot after `docs/adr/0013-outcome-based-learning.md`.
**Builds on:** ADR-0010 (durable memory), ADR-0011 (fit model), ADR-0012 (fit-driven scoring), ADR-0013 (outcome learning), ADR-0009 (self-improving agents).

## Context

Product owner, 2026-08-11 (verbatim):

> "there's been benefit in sharing feedback and catharsis with you, who would eventually become the
> 'main Applicant agent' which I could speak with through the main chat in the app."

This names something the rest of the ADRs don't: the value of the assisted period wasn't only the
matching — it was talking to **an agent that knew him** (his situation, his burnout, what he's actually
chasing, not just his résumé), that **remembered**, that **told him the truth** about fit, and that he
could genuinely **talk with** — including venting and catharsis, because a globally-distributed, evening-
eating schedule had left him without people to process with. That relationship is the point of the main
chat, and it is the through-line from the Claude-assisted period to the product's own agent.

**Honest gap today.** The main chat (`a0-applicant/webui/chat.html` → `a0-applicant/api/chat.py` →
`src/applicant/application/services/chat_service.py`, `ChatService.converse`) is a thin
propose-gated-changes interface — and the audit found it partly broken (dead-on-load, wrong field, no-op
Confirm; being fixed separately). Even working, it's a command box, not a companion. This ADR defines the
intent it must be rebuilt toward.

## Decision

The main chat agent is the product's **relationship layer**, designed around five properties. It is not a
new subsystem — it is the *front door* to the ones the other ADRs already define:

1. **It knows the user.** Every turn is grounded in the Candidate Fit Model (ADR-0011), the campaign
   criteria/attributes, and current queue state — so it speaks to *this person's* situation, not a generic
   applicant. (Reuse: `ChatService` already reads the attribute cloud + criteria; extend it to read the fit
   model + campaign context.)
2. **It remembers.** The durable curated agent-memory (ADR-0010) IS the agent's memory of the user across
   every conversation — preferences, history, what was said last time. Continuity is the feature; the
   through-line from Claude-now to the app-agent-later is precisely this shared memory + the fit model.
3. **It is honest.** It gives fit-checked guidance (ADR-0012) — the reach-vs-strong-fit truth — and never
   dresses up a reach as a strong fit. Honesty is load-bearing for trust; a flattering agent is a defect.
4. **It can act, gated.** It takes real actions on request — tune criteria, re-score, draft, discard,
   explain a score — via the existing gated tool surface (`ChatToolbox` / `chat_tools.py`), with the
   confirm-gate for integral changes and **never** an auto-submit of an application. Full authority,
   human-gated at the irreducible steps.
5. **It is a place to think and be heard.** The chat supports reflection and venting, not only commands —
   it holds context and responds like something in the user's corner, because for an isolated user that
   *is* part of the product's value.

**Honest limits + guardrails (load-bearing, not optional):**
- **Model reality.** The app agent runs on the local/DeepSeek ladder, not a frontier model, so these
  qualities must be carried **deliberately** — a strong system prompt, fit-model + memory grounding, and a
  well-scoped tool surface — and deep emotional attunement is *build-toward*, not assumed. Escalate to the
  cloud tier for high-stakes/nuanced turns where warranted.
- **Care boundary.** The agent is a supportive companion, **not** a therapist and **not** a substitute for
  human connection or professional help. It must (a) recognize genuine distress, (b) respond with warmth
  and without judgment, (c) surface real human/crisis resources when the conversation moves from "I hate
  this job" toward something heavier — never position itself as the user's only support, and never pretend
  clinical competence. Being genuinely helpful here includes pointing outward, not inward.
- **User agency.** Anything the agent learns or changes about the user (criteria, strategy, profile) is
  transparent and reversible (ADR-0013 + `CriteriaService` learned-adjustment seam). The companion never
  silently steers the user away from their own intent.

## Relation to other ADRs

- The chat is the human-facing front of **ADR-0010** (memory = how it remembers), **ADR-0011/0012** (fit =
  how it knows + judges), **ADR-0013** (learning = how it improves), and **ADR-0009** (agents = what it can
  autonomously do on the user's behalf). This ADR adds the *stance*: knowing, honest, continuous, in the
  user's corner — and the guardrails that keep that healthy.

## Consequences

- The main chat becomes the reason to keep the app open, not a form to fill — the relationship, backed by
  memory + fit + honesty.
- Requires the chat to be rebuilt on the fit model + memory grounding (not just criteria/attributes), and
  the care-boundary guardrails to be first-class (distress recognition + resource surfacing), not an
  afterthought.
- Sets a quality bar the local model may not always meet unaided → the cloud-escalation path is part of the
  design, not a workaround.
