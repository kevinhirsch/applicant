# Chat-Onboarding Closed Loop

## The "Minimal Wizard + Chat Probe" Model

The onboarding flow intentionally follows a **minimal wizard → chat probe** pattern:
the wizard (intake form) asks for almost nothing, and the chatbot proactively
gathers the remaining essentials needed before autonomous applying can begin.

This document explains the architecture: the `apply_readiness` gate, the nudge
service, the chat context loop, and how they close the onboarding circuit.

---

## Architecture Overview

```
                  ┌──────────────────────────────────┐
                  │         Minimal Wizard            │
                  │  (identity + résumé + EEO)        │
                  └──────────┬───────────────────────┘
                             │ (wizard complete)
                             ▼
                  ┌──────────────────────────────────┐
                  │   apply_readiness(campaign_id)    │
                  │   (the hard gate)                 │
                  │                                   │
                  │  Checks: titles, work_mode,       │
                  │  locations, salary_floor,         │
                  │  keywords, résumé                 │
                  └──────────┬───────────────────────┘
                             │ (missing essentials?)
                    ┌────────┴────────┐
                    ▼                 ▼
             ┌──────────┐    ┌──────────────────┐
             │ GATE     │    │  EssentialsNudge  │
             │ CLOSED   │◄───│  Service          │
             │          │    │  (daily push)     │
             │ Chat     │    └────────┬─────────┘
             │ probes   │             │ nudge →
             │ missing  │             │ user returns
             │ items    │             ▼
             └──────────┘    ┌──────────────────┐
                    │        │  Chat Service     │
                    │        │  _essentials_ctx  │
                    │        │  _do_criteria_    │
                    │        │  refocus()        │
                    │        └────────┬─────────┘
                    │                 │ captures
                    │                 ▼
                    │        ┌──────────────────┐
                    │        │  CriteriaService  │
                    │        │  edit_criteria()  │
                    │        └────────┬─────────┘
                    │                 │
                    └─────────────────┘
                             │ gate rechecked
                             ▼
                  ┌──────────────────────────────────┐
                  │         GATE OPEN!                │
                  │   "That's everything I need —     │
                  │    I can start applying now."     │
                  └──────────────────────────────────┘
```

### Why the Wizard Is Intentionally Minimal

The wizard asks for only what the user **must** provide upfront:

- **Identity** (name, email, phone) — core to every application.
- **Résumé upload** — seeds the attribute cloud (FR-ATTR-1).
- **EEO** — legally required self-identification.

Everything else — target roles, work mode, locations, salary floor, key skills —
is gathered **progressively** by the chatbot during natural conversation. This
keeps the initial friction near-zero while the agent still collects enough to
start applying. The approach mirrors progressive-profiling patterns used in
modern SaaS onboarding: ask for the minimum to deliver value, then collect
the rest conversationally.

---

## Components

### 1. The `apply_readiness` Gate

| File | Symbol |
|------|--------|
| `src/applicant/core/rules/apply_readiness.py` | `evaluate_apply_readiness()` |
| `src/applicant/application/services/onboarding_service.py` | `OnboardingService.apply_readiness()` |

A **pure function** (`evaluate_apply_readiness`) computes readiness from six boolean
flags derived from real campaign data — never fabricated:

| Essential | Flag | Source |
|-----------|------|--------|
| Target roles | `has_titles` | `criteria.titles` OR `criteria.human_readable` |
| Work mode | `has_work_modes` | `criteria.work_modes` |
| Locations | `has_locations` | `criteria.locations` |
| Salary floor | `has_salary_floor` | `criteria.salary_floor is not None` |
| Key skills | `has_keywords` | `criteria.keywords` OR `criteria.human_readable` |
| Résumé | `has_resume` | `onboarding.has_base_resume()` |

A free-text `human_readable` statement counts for **both** `has_titles` and
`has_keywords`, so a chat-only user who says "I'm looking for senior Python roles"
satisfies the gate without typed titles/keywords.

### 2. The Essentials Nudge Service

| File | Symbol |
|------|--------|
| `src/applicant/application/services/essentials_nudge.py` | `EssentialsNudgeService` |

The push sibling of the apply-readiness surface. Once per UTC day (when the
`essentials_nudge_schedule` is `"daily"`), for each active campaign whose automated
work is BLOCKED specifically because apply-essentials are absent, it pushes **one**
short, first-person notification through the existing notification system (in-app
inbox + opt-in fan-out).

Key properties:

- **Truthful** (FR-AGENT-5): the missing list is read from `apply_readiness().missing`
  — never fabricated.
- **Idempotent** (FR-NOTIF-3): deduped per `(campaign_id, UTC date)` so re-driving
  the same day emits nothing.
- **Graceful degradation**: no nudge emitted when the readiness reader or notifier
  is absent.
- **Gate-aware**: emits only when the automated-work gate is closed AND the reason
  is missing essentials — never when blocked on e.g. a paused campaign.

The nudge body reads like a friendly first-person message:
```
"I'm ready to start applying, but I still need target roles and a salary floor.
Add them and I'll begin."
```

### 3. The Chat `_essentials_context`

| File | Symbol |
|------|--------|
| `src/applicant/application/services/chat_service.py` | `ChatService._essentials_context()` |

A bounded prompt block injected fresh per conversational turn. When the
apply-readiness gate is closed, it instructs the LLM to **ask** for the next one
or two missing essentials — a focused question, not a wall of fields. When the
gate is open, it tells the LLM it may announce readiness.

```
Apply-readiness: I can't start applying yet. The essentials still missing are:
target roles, locations, key skills. Proactively and warmly ask the user for
the next one or two (target roles, locations) in your reply...
```

The companion `_essentials_followup()` method recomputes readiness **after** a criteria
change is applied, so the agent truthfully confirms what was captured and what
remains.

### 4. Structured Chat Capture

The `_do_criteria_refocus()` method in chat_service.py routes user statements to
the criteria service through regex-based intent matching. Each facet follows one
of two patterns:

| Facet | Integral? | Applied | Pattern |
|-------|-----------|---------|---------|
| Work mode | No | Auto | Regex → `edit_criteria(work_modes=...)` |
| Human-readable statement | No | Auto | Regex → `edit_criteria(human_readable=...)` |
| Key skills / keywords | No | Auto | `_KEYWORDS` → tokenize → `edit_criteria(keywords=...)` |
| Salary floor | **Yes** | Proposal | `_SALARY` → `ControlAction(requires_confirmation=True)` |
| Locations | **Yes** | Proposal | `_LOCATIONS` → `ControlAction(requires_confirmation=True)` |

Non-integral facets (work mode, keywords, human_readable) apply directly —
the user is stating intent with no campaign-scope impact. Integral facets
(salary floor, locations) are surfaced as confirmation-gated proposals: the
user must explicitly confirm via `confirm_criteria_refocus()` (FR-FB-3).

---

## The Closed Loop

```
┌──────────────────────────────────────────────────────────────────┐
│  CLOSED LOOP: Wizard → Gate → Nudge → Chat → Capture → Gate     │
└──────────────────────────────────────────────────────────────────┘

1. User completes the minimal wizard (identity + résumé + EEO).
2. apply_readiness() reports: gate CLOSED — titles, locations,
   salary_floor, keywords, work_mode still missing.
3. EssentialsNudgeService emits a daily push notification naming
   exactly what's still missing.
4. User returns, opens chat, says "I'm looking for remote Python
   roles in Austin with a floor of $120k".
5. ChatService._do_criteria_refocus() matches:
   - _REMOTE → work_modes=["remote"] (auto-applied)
   - _ROLE_STATEMENT → human_readable (auto-applied)
   - _LOCATIONS → locations=["Austin"] (proposal, pending confirm)
   - _SALARY → salary_floor=120000 (proposal, pending confirm)
6. User confirms proposals.
7. apply_readiness() rechecked: gate OPEN.
8. _essentials_followup() tells user:
   "That's everything I need — I can start applying now."
9. EssentialsNudgeService stops (gate is open, nothing missing).
```

### Key Design Decisions

**Why the nudge exists.** The wizard is intentionally minimal; users who wander
off after completing it are blocked indefinitely. The nudge is the friendly
reminder that brings them back to unblock themselves.

**Why the nudge stops.** Once `apply_readiness().ready` is `True`, the nudge
service gets `missing=()` and emits nothing — self-correcting without an
explicit "turned off" flag.

**Why locations are confirmation-gated.** Changing search locations shifts the
campaign's geographic scope — an integral change (FR-FB-3). The chat presents
it as a proposal rather than silently updating criteria.

**Why keywords are auto-applied.** Key skills / keywords refine discovery but
don't change campaign scope. The user stating "skills in Python, Django" is
applying their own intent, not mutating a core constraint.

---

## File Reference

| Path | Role |
|------|------|
| `src/applicant/core/rules/apply_readiness.py` | Pure readiness gate — no I/O, no fabrication |
| `src/applicant/application/services/onboarding_service.py` | Readiness computation from real campaign state |
| `src/applicant/application/services/essentials_nudge.py` | Push nudge when gate is closed |
| `src/applicant/application/services/chat_service.py` | Chat context + structured criteria capture |
| `src/applicant/application/services/criteria_service.py` | Criteria persistence + integral gate |
| `src/applicant/core/entities/search_criteria.py` | `SearchCriteria` entity definition |
| `src/applicant/app/config.py` | `essentials_nudge_schedule` setting |
| `src/applicant/application/services/scheduler.py` | Daily nudge tick in the live loop |
