# Redesign: Form-first onboarding, then LLM-conversational gather/refine

Status: DRAFT SPEC (investigation-only; no code changed)
Scope: `src/applicant` (engine), `a0-applicant` (Applicant's plugin/product layer
deployed to `/a0/plugins/applicant` per `docker/Dockerfile.a0:25`)
Checkout: `agent-zero` container, `/a0/usr/projects/applicant`, branch
`claude/refactor-agent-zero-applicant-xn7xoc`

## 1. Goal

On the **first** campaign start, the 12-section intake wizard (forms) pops up
automatically for manual fill, as today's `main.html` wizard already does when
manually opened. **After that first pass** (whether the user finished all
sections, skipped some, or closed the modal early), the intake forms never
auto-pop again. Instead, the "Applicant" chat agent proactively — but not
naggingly — asks about whatever intake fields are still blank or were left
unanswered, accepts freeform answers, and writes them into the same intake
record the wizard writes to. Fields the user explicitly declines to answer are
remembered as *intentionally omitted* so the agent never re-asks about them.

This is additive: the wizard, the engine's `OnboardingService`, and the
`CriteriaService`/`AttributeCloudService` bridges are all reused as-is. Nothing
about the intake's field set or its Workday-readiness contract
(`docs/onboarding-intake.md`) changes.

## 2. Current architecture (as found)

### 2.1 Intake model + completeness tracking

- `IntakeSection` (`src/applicant/ports/driving/onboarding.py:22-36`) — 12
  resumable sections: `IDENTITY, WORK_AUTHORIZATION, LOCATION, TARGET_ROLES,
  COMPENSATION, WORK_HISTORY, EDUCATION, REFERENCES, CERTIFICATIONS,
  KEY_ATTRIBUTES, EEO, BASE_RESUME, CAMPAIGN_CRITERIA`.
- `REQUIRED_SECTIONS` (`onboarding.py:41-53`) — everything **except**
  `CERTIFICATIONS`. Notably **`REFERENCES` is required** here.
- `OnboardingState` (`onboarding.py:60-67`) — `campaign_id`, `complete`,
  `sections_complete: list[str]`, `missing_sections: list[str]`,
  `intake: dict[str, Any]`. No notion of "omitted" exists anywhere in this
  model today.
- `OnboardingPort` (`onboarding.py:105-129`) — `get_state`, `save_section`,
  `complete`, `ingest_base_resume`. No "next thing to ask" or "mark declined"
  method exists.
- `OnboardingService` (`src/applicant/application/services/onboarding_service.py`):
  - `_load`/`_store` (lines 117-128) persist a per-campaign dict
    (`{"intake": {...}, "sections_complete": [...], "complete": bool}`) keyed
    `onboarding.<campaign_id>` in the app-config store. Additional flags have
    been added to this dict additively before (`memory_seeded`, line 358) —
    that's the precedent for adding new flags safely.
  - `save_section` (144-176) **overwrites the entire section's dict**:
    `intake[section.value] = data` (line 153). The wizard's own `save()`
    (`main.html:253-260`) always posts **every field** in the section's form,
    so this is safe today — **but any new write path that posts only the one
    field the user just answered in chat would silently wipe every sibling
    field already saved in that section.** This is the single most important
    landmine for the design below (§3.2.3).
  - `_section_filled` (694-698) — a section counts as done if **any** field is
    non-empty. There is no per-field completeness and no "explicitly skipped"
    state; `main.html`'s `skip()` (261-266) posts `data: {}`, which
    `_section_filled({})` evaluates `False`, so **a skipped section is
    indistinguishable from a never-visited one** and stays in
    `missing_sections` forever. Combined with `REFERENCES` being in
    `REQUIRED_SECTIONS` while the wizard flags it `optional: true`
    (`main.html:201`) with a Skip button, **`complete()` can never return
    `true` today for a user who skips References** — a pre-existing bug this
    design's omission mechanism fixes as a side effect.
  - `_bridge_section_to_engine` / `_bridge_attributes` / `_bridge_profile_criteria`
    / `_bridge_criteria` (178-296) — every non-empty field saved via
    `save_section` is fanned out into `AttributeCloudService.upsert(...,
    confirm=True)` and/or `CriteriaService.edit_criteria(..., confirm=True)`.
    This only iterates real `data.items()` — an "omitted" marker that never
    enters `data` cannot leak into the attribute cloud or criteria. (This is
    why the design below keeps omission **out-of-band**, not as a sentinel
    string value written into `intake`.)
  - `complete()` (322-343) — `complete=True` only when
    `sections_complete ⊇ REQUIRED_SECTIONS`.
  - `apply_readiness()` (431-467) is a **separate, narrower** gate (titles,
    work modes, locations, salary floor, keywords/resume) that the
    apply-automation actually depends on — a campaign can be `apply_ready`
    while onboarding `complete` is still `False` forever (e.g. References
    skipped). Both gates matter for the design: the first-run form trigger
    should fire on "intake incomplete", not on "not apply-ready".

- `CriteriaService.apply_learned_adjustment` (`criteria_service.py:66-91`) —
  this is the **LLM/learning** mutation path (FR-CRIT-3), distinct from
  `edit_criteria` (the direct user-edit path onboarding uses). It's for
  after-the-fact learned deltas (e.g. from conversion data), not for
  onboarding intake gathering — **not the right primitive for this feature**;
  onboarding's own `edit_criteria(..., confirm=True)` bridge (already used by
  `save_section`) is the correct one, because a chat answer is the user's own
  first-party statement, not a learned inference.
- `AttributeCloudService.upsert` (`attribute_cloud_service.py:74-118`) is what
  `_bridge_attributes` already calls; `resolve_missing`/`acquire_missing`/
  `resume_after_missing_attr` (177-277) are a **separate** mechanism — a
  mid-application "soft error" queue (surfaced via `a0-applicant/api/pending.py`,
  a "daily review panel") for a field discovered missing while an ATS form is
  being filled. That's a different trigger point (application-time, not
  onboarding-time) and this design does not change it, though the new chat
  tool below could later be reused to resolve those too.

### 2.2 Onboarding router (REST surface)

`src/applicant/app/routers/onboarding.py`:
- `GET /api/onboarding/{campaign_id}` (114-117) → `get_state`.
- `POST /api/onboarding/{campaign_id}/section` (120-129) → `save_section`
  (whole-section overwrite, see above).
- `POST /api/onboarding/{campaign_id}/complete` (132-144) → `complete`, 409
  with `missing_sections` if incomplete.
- `POST /api/onboarding/{campaign_id}/base-resume` (167-242) → file upload +
  parse + reconcile.
- `POST /api/onboarding/{campaign_id}/confirm-conflict` (245-251) → resolve an
  integral parsed-vs-typed conflict.

No endpoint today exposes "what's still missing" at field granularity, marks
something as intentionally skipped, or records that the OOBE wizard has been
shown once.

### 2.3 Webui panels

- **The real 12-section intake wizard**: `a0-applicant/webui/main.html`
  (Alpine.js component `applicantOnboarding`). Its `SECTIONS` array
  (`main.html:185-216`) is the **only** place the field catalog (labels, hints,
  types, which sections are `optional`) exists — it is hand-duplicated from
  `docs/onboarding-intake.md` and not shared with the engine. It calls the a0
  shell's onboarding proxy via `callJsonApi("onboarding", {action, ...})`
  (`main.html:181-182`, `228, 256, 264, 277, 299`), matching the `dispatch()`
  contract in `a0-applicant/api/onboarding.py:71-81` (`state` / `section` /
  `complete`; base-resume upload goes directly to `POST /api/a0-applicant/base_resume`).
  `main.html` is reachable via the sidebar's plugin nav button labeled
  **"Setup"** (`a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html:3-6`,
  `window.openModal('/plugins/applicant/webui/main.html')`) — opened as a
  **modal**, not auto-shown. There is also a **"Profile"** nav button pointing
  at `attributes.html` (same file, line ~34) — the attribute-cloud viewer,
  which is the closest thing to a standalone "profile" page; there is no
  separate profile-editing surface beyond re-opening `main.html` (its
  `goto(i)`/`resume()` let any section be revisited after completion).
- **`frontend/static/applicant/{setup.html,js/setup.js}`** is a *different*,
  simpler flow: LLM-endpoint connection + channels/fonts + one crude
  "intake ready" toggle (`initIntake`, `setup.js:372-385`) that just POSTs
  `/api/setup/advance/onboarding` — this is **not** the 12-section wizard and
  should not be confused with it; it appears to serve a different/legacy
  deployment surface and is out of scope for this design.
- **`frontend/static/js/applicantOnboarding.js`** and its duplicate under
  `workspace/static/js/`) implement an entirely different, game-themed
  ("Big Brother" casting-interview) onboarding overlay keyed off
  `/api/applicant/state` (`started: false`). This is unrelated to the real
  Workday-intake product flow and is **not** touched by this design.
- **No code anywhere auto-opens `main.html` on first run today.** The plugin
  metadata's `has_main_screen` flag (`agent-zero/helpers/plugins.py:262`) only
  controls whether the plugin-list UI shows an "open" affordance
  (`agent-zero/webui/components/plugins/list/pluginListStore.js:77`) — nothing
  conditions it on onboarding state. **This is a real gap**, not a
  misunderstanding on the task's part — see §3.1.

### 2.4 The chat agent ("Applicant" persona) — prompts, and what tools exist

- Agent profile `a0-applicant/agents/applicant/` (deployed to
  `/a0/plugins/applicant/agents/applicant/`) overrides
  `prompts/agent.system.main.specifics.md` — voice/role, and states the
  engine's `apply_ready`/`apply_missing` gate must be respected
  (`agent.system.main.specifics.md:9`), plus a memory-routing rule (D19). No
  mention of onboarding-gathering.
- `a0-applicant/prompts/agent_guidance.md` — tells the agent to check
  `GET /api/setup/status` / the features handler for `apply_ready`/
  `apply_missing` before ever attempting to apply. Same pattern I reuse below.
- **No Applicant-specific `Tool` subclass exists anywhere in the checkout.**
  Confirmed by searching all `class ... Tool` definitions under `a0-applicant`
  and `agent-zero/plugins/*` — the only tools are framework-level
  (`_memory`, `_text_editor`, `_code_execution`, `_browser_agent`). The chat
  agent currently has **no direct way to read or write onboarding intake** —
  it would have to be told to shell out HTTP calls via `code_execution`, which
  is what `agent_guidance.md` literally describes for `apply_ready` today.
  This is the concrete gap the new tools in §3.2.5 close.
- Existing a0-applicant API proxies (`a0-applicant/api/*.py`) all follow one
  copy-pasted, self-contained pattern (`_engine()`, `_forward()`,
  `_resolve_campaign_id()`, `dispatch(input)`, then a thin `ApiHandler`
  subclass) — see `onboarding.py:1-87`, `criteria.py:1-92`, `pending.py:1-106`,
  `attributes.py`. `_resolve_campaign_id` (`onboarding.py:48-68`) maps a
  missing/`"__system__"` id to the single active campaign (MVP is
  single-campaign), failing closed to `"__system__"` on any problem — the
  engine's `OnboardingService._load` tolerates an arbitrary string id with no
  real `Campaign` row required, so onboarding can be filled before a
  first-class campaign exists.

### 2.5 Extension/hook infrastructure available (confirmed by reading core + precedent plugins)

Agent-zero (`agent-zero/extensions/python/*`) exposes, among others:
`monologue_start`, `system_prompt`, `banners`. Each is a small `Extension`
subclass dropped into a hook-named folder (in core, or in
`a0-applicant/extensions/python/<hook>/`), auto-discovered.

- **`system_prompt`** — fires when the agent's system prompt is (re)built;
  an extension mutates the `system_prompt: list[str]` argument in place and
  appends its own block. Precedent: `_14_project_prompt.py`
  (`agent-zero/extensions/python/system_prompt/_14_project_prompt.py:1-30`)
  builds a block from live per-context data (`projects.build_system_prompt_vars`)
  via `agent.read_prompt(...)`. **This is the mechanism to inject "here's what's
  still missing, consider asking" into the agent's context** — same shape as
  what I propose in §3.2.6.
- **Tool discovery + prompting**: `_11_tools_prompt.py`
  (`agent-zero/extensions/python/system_prompt/_11_tools_prompt.py:26-42`)
  scans every `prompts/` dir returned by `subagents.get_paths(agent, "prompts")`
  (confirmed `include_plugins=True` by default,
  `agent-zero/helpers/subagents.py:339-350`) for `agent.system.tool.*.md`
  files and stitches them into the system prompt; each file is the tool's
  full usage doc (name, args, example JSON call) — see
  `agent-zero/plugins/_memory/prompts/agent.system.tool.memory.md` as the
  worked example for 4 sibling tools (`memory_load/save/delete/forget`) all
  documented in one file. Tool *implementations* live in a sibling `tools/`
  folder (`agent-zero/plugins/_memory/tools/memory_save.py`), each a
  `helpers.tool.Tool` subclass (`helpers/tool.py:16-27`: `execute(self,
  **kwargs) -> Response`, `Response(message, break_loop, additional=None)`).
  Since `a0-applicant` is deployed as the plugin `applicant`
  (`docker/Dockerfile.a0:25`), dropping `a0-applicant/tools/*.py` +
  `a0-applicant/prompts/agent.system.tool.*.md` makes new tools available to
  the "applicant" agent exactly like `_memory`'s tools are — **no other
  wiring needed.**
- **`monologue_start`** — fires once per user turn/loop; precedent
  `a0-applicant/extensions/python/monologue_start/_50_engine_llm_sync.py:69-113`
  already does a per-turn, cheap, best-effort HTTP round-trip to the engine
  from here (model-config sync) and caches a signature to avoid redundant
  work; `_55_local_only_gate.py` is a second, simpler example. This is the
  right place to **fetch** "what's the next thing to gather" once per turn
  (not on every `system_prompt` rebuild, which can happen more than once per
  turn inside a tool-call loop).
- **`banners` + the *already-built, currently-unused* auto-modal mechanism**:
  `agent-zero/api/banners.py:1-14` — `POST /banners` calls
  `call_extensions_async("banners", agent=None, banners=banners,
  frontend_context=frontend_context)`; extensions append dicts to `banners`
  in place. `frontend_context` carries whatever the caller sent
  (`is_welcome`, `is_onboarding`, `surface`, `ctxid` — see below). The
  **welcome-screen client already knows how to force-open a modal from a
  banner**: `agent-zero/plugins/_discovery/extensions/webui/initFw_end/auto-modal.js`
  (fires from the `initFw_end` webui hook, one of the few JS-lifecycle slots,
  confirmed by `agent-zero/extensions/webui/initFw_end/selfUpdateGlobal.js`
  as a second example) polls `POST /banners` with
  `context: {is_welcome, is_onboarding, surface, ctxid}`
  (`auto-modal.js:52-64`), and if any returned banner has an
  `auto_modal_path` (+ `auto_modal_priority`, `auto_modal_surfaces`), and it
  isn't session-suppressed (`isSuppressed`/`suppress`, keyed by banner id +
  reason + surface in `sessionStorage`) and not already open, it calls
  `window.openModal(banner.auto_modal_path)` (`auto-modal.js:88-96`). It also
  re-checks after a modal is closed (`modal-closed` event) and after a new
  chat is created (`chat-created` event). **Grepping the whole checkout for
  `auto_modal_path` finds zero producers** — the discovery plugin's own
  banner extension (`plugins/_discovery/extensions/python/banners/10_discovery_cards.py`)
  only emits card-style banners (`type: "hero"/"feature"`, no
  `auto_modal_path`). **This means the exact mechanism needed for "detect
  incomplete intake → force the wizard open" is already fully built and wired
  end-to-end in the framework, and nothing in the codebase uses it yet.**
  This is the cleanest possible seam for §3.1: a small Python banner
  extension, zero new frontend JS.

## 3. Proposed design

### 3.1 First-run form trigger (show the wizard automatically, exactly once)

**New persisted flag**, additive like `memory_seeded`:
- `OnboardingState` gains `oobe_shown: bool = False`
  (`src/applicant/ports/driving/onboarding.py`, alongside the other fields at
  line ~67).
- `OnboardingService._load` defaults `rec.setdefault("oobe_shown", False)`
  (mirrors lines 121-123); `_to_state` passes it through.
- New port method `mark_shown(campaign_id) -> OnboardingState`: sets
  `rec["oobe_shown"] = True` and stores — idempotent, no other side effects
  (does not touch `intake`/`sections_complete`/`complete`).
- New router endpoint `POST /api/onboarding/{campaign_id}/shown` →
  `svc.mark_shown(campaign_id)`.
- `a0-applicant/api/onboarding.py`: add a `shown` action to `dispatch()`
  (mirrors `complete`, `onboarding.py:79-80`):
  `if action == "shown": return _forward("POST", f"/api/onboarding/{cid}/shown", {})`.
- `main.html`'s `init()` (`main.html:226`): after the first successful
  `refresh()`, fire-and-forget `callJsonApi("onboarding", {action: "shown"})`
  once. This records "the user has seen the wizard at least once", regardless
  of whether they finish it, skip sections, or close the modal immediately —
  matching "on first campaign start, forms pop up" as a one-time event, not a
  per-session nag.

**New banner extension** —
`a0-applicant/extensions/python/banners/_10_onboarding_first_run.py`
(mirrors `agent-zero/plugins/_discovery/extensions/python/banners/10_discovery_cards.py:1-11`
for shape; note `agent=None` in this hook per `agent-zero/api/banners.py:13`,
so it must be self-contained like the other `a0-applicant/api/*.py` proxies —
reuse `onboarding.dispatch({"action": "state"})` directly, no new HTTP
client needed):

```python
from helpers.extension import Extension
from api.onboarding import dispatch as onboarding_dispatch  # self-contained, agent-independent

class OnboardingFirstRun(Extension):
    async def execute(self, banners: list = [], frontend_context: dict = {}, **kwargs):
        if frontend_context.get("surface") != "welcome":
            return
        result = onboarding_dispatch({"action": "state"})
        if not result.get("ok"):
            return
        state = result.get("data") or {}
        if state.get("oobe_shown") or state.get("complete"):
            return
        banners.append({
            "id": "applicant-onboarding-first-run",
            "auto_modal_path": "plugins/applicant/webui/main.html",
            "auto_modal_priority": 100,
            "auto_modal_surfaces": ["welcome"],
            "auto_modal_reason": "onboarding-incomplete",
            "dismissible": True,
        })
```

This reuses `auto-modal.js` completely unmodified. Firing condition is
"never marked shown AND not complete" — a persistent (not session-scoped)
one-shot, so it survives across browser sessions/devices until the user has
actually seen the wizard once. `auto-modal.js`'s own session-scoped
suppression additionally prevents it from re-popping mid-session if the user
closes it and keeps chatting (`handleModalClosed`, `auto-modal.js:107-120`).

### 3.2 Post-first-run LLM-conversational gather/refine loop

#### 3.2.1 Data model: intentional omission (out-of-band, never bridged)

Add to the persisted record and `OnboardingState`:
- `omitted_sections: list[str]` — a whole section the user explicitly declined
  (e.g. "I'd rather not give references"). An omitted section satisfies the
  `REQUIRED_SECTIONS` gate the same way a filled one does, **without** writing
  anything into `intake[section]` — so it never reaches `_bridge_attributes`/
  `_bridge_profile_criteria`/`_bridge_criteria` (which only iterate real
  `data.items()`, `onboarding_service.py:236, 267, 236-246`). This directly
  fixes the pre-existing References skip/required inconsistency noted in
  §2.1.
- `omitted_fields: dict[str, list[str]]` (section value → field keys) —
  advisory-only, for a section that's partially filled but has specific
  blanks the user declined. Does not by itself flip section completeness;
  it only tells the gather logic (§3.2.4) to stop asking about that one
  field while still asking about other blanks in the same section.

Both default to `{}`/`[]` via `setdefault` in `_load`, exactly like
`sections_complete`/`intake` are today (`onboarding_service.py:120-123`).

`_to_state` (129-138) changes the `missing` computation to also exclude
`omitted_sections`:
```python
missing = [s.value for s in REQUIRED_SECTIONS
           if s.value not in done and s.value not in omitted]
```
`complete()` (322-343) uses the same `done | omitted_sections` union when
checking `missing`.

#### 3.2.2 Field catalog: single source of truth (closes a drift risk)

`main.html:185-216`'s `SECTIONS` array (id, title, hint, optional flag, and
each field's key/label/type/options) is currently the **only** place this
catalog exists, hand-duplicated from `docs/onboarding-intake.md`. Add a
server-side mirror,
`INTAKE_FIELD_CATALOG: dict[IntakeSection, tuple[FieldSpec, ...]]`
(`FieldSpec = @dataclass(frozen=True) label: str; hint: str = ""`) next to
`REQUIRED_SECTIONS` in `onboarding.py`, covering the same 12 sections/fields
as `main.html`. This is what `next_gather_target` (§3.2.3) reads to know
field *labels* to phrase questions with, and is a single source of truth the
wizard could later fetch too (stretch — not required for this feature; flagged
as a follow-up to prevent the two copies drifting apart over time).

#### 3.2.3 Service methods (`OnboardingService`)

- `mark_field_omitted(campaign_id, section, field, note="") -> OnboardingState`
  — appends `field` to `omitted_fields[section.value]` (dedup), stores.
- `mark_section_omitted(campaign_id, section, note="") -> OnboardingState`
  — appends `section.value` to `omitted_sections`, stores. Recomputes
  `sections_complete`/`missing_sections` via the updated `_to_state` (§3.2.1).
- `save_field(campaign_id, section, field, value, *, confirm=True) ->
  OnboardingState` — **read-merge-write**, to avoid the whole-section
  clobber landmine in §2.1:
  ```python
  def save_field(self, campaign_id, section, field, value, *, confirm=True):
      rec = self._load(campaign_id)
      data = dict(rec.get("intake", {}).get(section.value, {}))
      data[field] = value
      state = self.save_section(campaign_id, section, data)  # existing method, unchanged
      # answering a field un-defers it if it was previously marked omitted
      rec = self._load(campaign_id)
      omitted = dict(rec.get("omitted_fields", {}))
      if field in omitted.get(section.value, []):
          omitted[section.value] = [f for f in omitted[section.value] if f != field]
          rec["omitted_fields"] = omitted
          self._store(campaign_id, rec)
      return self._to_state(campaign_id, rec)
  ```
  Delegating to the existing `save_section` means the EEO-normalize step, the
  `_bridge_section_to_engine` fan-out to `AttributeCloudService`/
  `CriteriaService` (both called with `confirm=True`, matching the existing
  posture that onboarding answers are the user's own explicit first-party
  data — `onboarding_service.py:222-226, 239-245, 292-296`), and logging all
  keep working unmodified. **This is the one new piece of write logic; everything
  downstream of it is reused as-is.**
- `next_gather_target(campaign_id) -> GatherTarget | None` — `GatherTarget =
  @dataclass(frozen=True): section: str; title: str; hint: str;
  missing_fields: list[dict]` (each `{key, label, hint}` from
  `INTAKE_FIELD_CATALOG`). Walks `REQUIRED_SECTIONS` in its fixed order
  (Identity → … → Campaign criteria), **skipping `BASE_RESUME`** (upload-only,
  not something a chat answer can satisfy — the agent can only remind the
  user to upload it, handled as a special-cased reminder, not a gather
  target), and returns the first section that is neither in
  `sections_complete` nor `omitted_sections`, together with whichever of its
  catalog fields are absent/empty in `intake[section]` **and** not already in
  `omitted_fields[section]`. Returns `None` once every required section is
  done-or-omitted (i.e. onboarding is functionally resolved even if some
  fields were declined).

#### 3.2.4 Router + proxy plumbing

New engine endpoints (`src/applicant/app/routers/onboarding.py`):
- `GET /api/onboarding/{campaign_id}/next` → `next_gather_target`, `null`
  when none.
- `POST /api/onboarding/{campaign_id}/field` — body `{section, field,
  value}` → `save_field`.
- `POST /api/onboarding/{campaign_id}/omit` — body `{section, field?: str
  | null, note?: str}` → `mark_field_omitted` when `field` present, else
  `mark_section_omitted`.
- `POST /api/onboarding/{campaign_id}/shown` (§3.1).

`a0-applicant/api/onboarding.py`: extend `dispatch()` with `next`,
`save_field`, `omit`, `shown` actions, each a one-line `_forward(...)` call —
same shape as the existing `state`/`section`/`complete` actions
(`onboarding.py:74-81`).

#### 3.2.5 New agent tools

Two new `Tool` subclasses in `a0-applicant/tools/` (new folder; deployed to
`/a0/plugins/applicant/tools/` per `docker/Dockerfile.a0:25`), following the
`helpers.tool.Tool` contract (`agent-zero/helpers/tool.py:16-27`) and the
`_memory` plugin's file-per-tool convention:

- **`onboarding_next.py`** (`OnboardingNext`) — no args. Calls
  `dispatch({"action": "next"})` (import from `api.onboarding`, same
  self-contained pattern). Returns a `Response` whose message is a compact,
  human-readable summary: section title + up to 3 missing field labels/hints
  (or "nothing outstanding" when `None`). This is a **read-only lookup** the
  agent calls when it wants to check what's still open — e.g. at the start of
  a session, or when the user asks "what do you still need from me?".
- **`onboarding_answer.py`** (`OnboardingAnswer`) — args: `section` (required,
  one of the `IntakeSection` values), `field` (optional — omit only when
  skipping the *whole* section), `value` (the user's own freeform answer;
  required unless `omit=true`), `omit` (bool, default `false`). Dispatches to
  `save_field` or `omit` accordingly. Returns a short confirmation message
  (new `fw.onboarding_field_saved.md`, mirroring `fw.memory_saved.md`).

Prompt docs (`a0-applicant/prompts/agent.system.tool.onboarding_next.md`,
`agent.system.tool.onboarding_answer.md`), following
`agent.system.tool.memory.md`'s worked format exactly (one usage block per
tool with example JSON `tool_args`). Key instructions to bake into
`onboarding_answer`'s doc, all directly motivated by rules already enforced
elsewhere in the engine so the agent doesn't fight the confirmation/sensitive
gates:
- **Only write a value the user just typed themselves**, in direct response
  to a question about that exact field — never infer, paraphrase into a
  different meaning, or guess a value the user didn't state. This mirrors the
  EEO section's existing rule (`onboarding_service.py:700-706`,
  `sensitive_fields.py`) that sensitive fields are never AI-guessed; the same
  discipline should hold for every field so onboarding answers stay
  first-party (matching the `confirm=True` trust posture already baked into
  the bridge calls, §3.2.3).
  answer isn't given yet).
- **Call `omit=true` the moment the user declines or deflects** a question
  about a field/section (e.g. "I'd rather not say", "skip that") — do not ask
  about the same field again in a later turn. This is what makes the "doesn't
  nag forever" requirement structural rather than a hope: `next_gather_target`
  mechanically excludes omitted fields/sections (§3.2.3), so once
  `onboarding_answer(omit=true)` is called, that field/section can never
  surface again from the tool itself.
- Never ask about more than one section's worth of fields in a single message
  (matches the wizard's own one-section-at-a-time pacing).

#### 3.2.6 Proactive surfacing (system prompt wiring)

Two small extensions, split per existing convention (fetch at
`monologue_start`, render at `system_prompt`, avoiding a redundant engine
round-trip if the system prompt rebuilds more than once inside one turn —
same reasoning as the existing `TOOL_KWARGS_KEY` cache pattern,
`agent-zero/extensions/python/system_prompt/_11_tools_prompt.py:30`):

- `a0-applicant/extensions/python/monologue_start/_60_onboarding_gather_fetch.py`
  — mirrors `_50_engine_llm_sync.py`'s shape (best-effort, threaded, never
  raises). Calls `dispatch({"action": "state"})`; if `oobe_shown` is falsy,
  does nothing (the first-run modal is still the active surface — avoid
  double-prompting while §3.1's banner may still be about to fire). Otherwise
  calls `dispatch({"action": "next"})` and stashes the result via
  `self.agent.set_data("_onboarding_gather_target", result)`.
- `a0-applicant/extensions/python/system_prompt/_20_onboarding_gather_prompt.py`
  — mirrors `_14_project_prompt.py`'s shape exactly: reads
  `agent.get_data("_onboarding_gather_target")`; if a target is cached,
  appends a short block via a new `agent.system.onboarding_gather.md` prompt
  (rendered with the section title + field labels/hints), instructing the
  agent: "If it fits naturally in this reply, ask about ONE of these; if the
  user answers, call `onboarding_answer`; if they decline, call it with
  `omit=true`. Otherwise say nothing about it this turn." If no target is
  cached (nothing outstanding, or still pre-first-run), appends nothing.

`agent.system.main.specifics.md` (the "applicant" profile's specifics file,
`a0-applicant/agents/applicant/prompts/agent.system.main.specifics.md`) gets
one short new paragraph cross-referencing this behavior, next to the existing
`apply_ready`/memory-routing rules, so the "don't nag" and "first-party
answers only" rules are visible in the same place a reviewer would already
look.

## 4. Files to change (summary)

Engine (`src/applicant/`):
- `ports/driving/onboarding.py` — `OnboardingState.oobe_shown`,
  `omitted_sections`, `omitted_fields`; `INTAKE_FIELD_CATALOG`; `GatherTarget`
  dataclass; new `OnboardingPort` methods (`mark_shown`, `mark_field_omitted`,
  `mark_section_omitted`, `save_field`, `next_gather_target`).
- `application/services/onboarding_service.py` — implement the above;
  `_load`/`_to_state`/`complete()` updated for the two new persisted lists.
- `app/routers/onboarding.py` — 4 new endpoints (`/shown`, `/next`, `/field`,
  `/omit`).

Applicant plugin (`a0-applicant/`, deployed to `/a0/plugins/applicant/`):
- `api/onboarding.py` — 4 new `dispatch()` actions.
- `webui/main.html` — one fire-and-forget `shown` call in `init()`.
- `extensions/python/banners/_10_onboarding_first_run.py` — **new file**.
- `extensions/python/monologue_start/_60_onboarding_gather_fetch.py` —
  **new file**.
- `extensions/python/system_prompt/_20_onboarding_gather_prompt.py` — **new
  file**.
- `tools/onboarding_next.py`, `tools/onboarding_answer.py` — **new folder +
  files**.
- `prompts/agent.system.tool.onboarding_next.md`,
  `prompts/agent.system.tool.onboarding_answer.md`,
  `prompts/agent.system.onboarding_gather.md`,
  `prompts/fw.onboarding_field_saved.md` — **new files**.
- `agents/applicant/prompts/agent.system.main.specifics.md` — one added
  paragraph.

No changes needed to `CriteriaService`, `AttributeCloudService`, the pending-
actions/soft-error flow, or `main.html`'s existing section rendering/skip
logic (beyond the one `shown` call) — all reused exactly as they behave today.

## 5. Risks / open questions

- **Field catalog duplication** (`main.html` vs. the new
  `INTAKE_FIELD_CATALOG`): both must list the same 12 sections/fields. Low
  risk short-term (the schema is stable/spec-driven), but flagged as a
  follow-up to unify — e.g. a `GET /api/onboarding/schema` the wizard fetches
  instead of hard-coding `SECTIONS`. Not required for this feature.
- **Multi-campaign future**: `_resolve_campaign_id`'s `"__system__"` →
  single-active-campaign resolution is an MVP assumption baked into every
  proxy (`onboarding.py`, `criteria.py`, `pending.py`). The new endpoints
  inherit this unchanged; if/when multi-campaign ships, all of these proxies
  need the same fix together, not just onboarding's.
- **`REFERENCES` required-but-optional**: this design's `omitted_sections`
  mechanism makes References skippable *correctly* for the first time. Worth
  a product call on whether References should simply move out of
  `REQUIRED_SECTIONS` instead (matching its wizard-side `optional: true`)
  rather than relying on the agent or a future wizard change to call
  `mark_section_omitted` — either resolves the bug; the omission mechanism is
  useful regardless since other sections (e.g. Certifications, or any field a
  user has a real reason to decline) benefit from the same "explicitly
  declined, stop asking" state.
- **EEO fields**: `next_gather_target` will surface `eeo` like any other
  section since the wizard's own defaulting (`_normalize_eeo`) only fires on
  `save_section`, not proactively. Recommend the gather prompt for `eeo`
  specifically frame it as "would you like to answer the voluntary EEO
  questions, or decline?" (never a bare "what's your race/gender/veteran/
  disability status") — worth encoding as a special case in
  `agent.system.onboarding_gather.md` rather than generic phrasing, to keep
  FR-ATTR-6's spirit (never AI-guessed, always the user's own explicit
  answer) visibly intact in the prompt text itself, not just in the backend
  gate.
- **Suggested-attributes (#273) overlap**: `SetupService.suggested_attributes`
  (`setup_service.py:400-429`) is a separate, engine-learning-driven
  "proposed attribute awaiting approval" surface, unrelated to onboarding
  intake gaps. Do not conflate the two in the agent's prompt — they are
  different data sources with different approval semantics.

## 6. Non-goals (explicitly out of scope)

- Changing `docs/onboarding-intake.md`'s schema or the wizard's own UI/CSS.
- Touching the `frontend/static/applicant/setup.js` LLM-connection flow, or
  the game-themed `applicantOnboarding.js` overlay (§2.3) — both are separate
  surfaces from the real intake wizard.
- Reworking the mid-application "missing attribute" soft-error/pending-action
  queue (`AttributeCloudService.resolve_missing`, `a0-applicant/api/pending.py`).
- Multi-campaign-aware campaign resolution (see Risks).
