# Redesign: Single Persistent Conversation (replace multi-"Chats" paradigm)

Status: DRAFT SPEC (investigation-only; no code changed)
Scope: `agent-zero/webui` (vendored Agent-Zero framework, actively customized in this
checkout) + `a0-applicant` (Applicant's plugin/product layer)
Checkout: `agent-zero` container, `/a0/usr/projects/applicant`, branch
`claude/refactor-agent-zero-applicant-xn7xoc`

## 1. Goal

Replace the current "Chats" sidebar (arbitrary, unlimited, user-managed list of
chat sessions, à la a coding-agent IDE) with **one fixed, always-on conversation**
per Applicant install/campaign. The user should never see a chat list or a "New
Chat" affordance that spawns a sibling conversation. There is one thread; it is
always there; it survives reloads; the same "Applicant" AI agent (with its
existing engine tools) answers questions about campaign state and acts on
freeform instructions in that one thread.

This is a UI/context-identity redesign, **not** an agent-capability change: the
"Applicant" agent already has engine tool access and already does freeform
Q&A + action today (see §2.6). Nothing about the LLM loop, tools, or the engine
needs to change for the steering behavior itself.

## 2. Current architecture (as found)

### 2.1 Context data model

`AgentContext` (`agent-zero/agent.py:42-160`) is the unit of a "chat". It's a
plain in-memory registry:

- `AgentContext._contexts: dict[str, AgentContext]` (`agent.py:44`) — process-wide
  dict keyed by a random 8-char id (`AgentContext.generate_id()`, `agent.py:131-139`).
- `AgentContext.__init__` (`agent.py:49-92`) is decorated `@extension.extensible`
  (`agent.py:49`), which means every construction call implicitly fires the
  extension points `_functions/agent/AgentContext/__init__/start` and `/end`
  (mechanism in `agent-zero/helpers/extension.py:51-160`; real precedent for this
  exact pattern already exists at
  `agent-zero/plugins/_model_config/extensions/python/_functions/agent/Agent/get_chat_model/start/_10_model_config.py`).
  A `start` extension receives `data["kwargs"]` (mutable, contains the ctor's
  `id=` kwarg when passed) and can rewrite it before the real constructor runs.
  **This is the clean hook point for enforcing a single canonical context id
  without touching vendored core files** — see §3.2.
- `AgentContext.get(id)` / `.use(id)` / `.first()` / `.all()` / `.remove(id)`
  (`agent.py:99-160`) — no parent/child or hierarchy concept exists on the
  model at all (no `parent_id` field anywhere).
- There is no built-in notion of "the campaign's context" — a context is just
  an id with a name, log, agent, and arbitrary `data`/`output_data` dicts.

### 2.2 Persistence

`agent-zero/helpers/persist_chat.py`:
- Each context is written to `usr/chats/<ctxid>/chat.json`
  (`get_chat_folder_path`/`_get_chat_file_path`, lines 17-27, 74-75) via
  `save_tmp_chat()` (lines 32-42), called after every reset
  (`api/chat_reset.py:18`) and elsewhere.
- On process boot, `load_tmp_chats()` (lines 54-71) walks `usr/chats/*` and
  deserializes every folder back into a live `AgentContext` — this is why
  contexts survive container restarts today, and it requires no change for a
  single fixed context (it'll just always find/restore the one folder).
- `load_json_chats()` (lines 87-96) explicitly **strips `id` and mints a new
  context** for every imported file — this is the "Load Chat" feature
  (`api/chat_load.py`), and it fragments the single-conversation model if left
  enabled (see §5).

### 2.3 Backend endpoints

- `POST /message_async` (`agent-zero/api/message_async.py` + shared logic in
  `agent-zero/api/message.py:22-70`) — the actual send-message call. Takes
  `context` (id, may be `""`), resolves it via `self.use_context(ctxid)`
  (`agent-zero/helpers/api.py:101-116`):
  ```
  if not ctxid:
      first = AgentContext.first()
      if first: return first
      return AgentContext(config=initialize_agent(), set_current=True)  # brand new random id
  got = AgentContext.use(ctxid)
  if got: return got
  if create_if_not_exists: return AgentContext(config=..., id=ctxid, set_current=True)
  ```
  i.e. empty ctxid today resolves to "whichever context happens to be first in
  an unordered dict" or a fresh random one — not deterministic, and exactly the
  kind of ambiguity a single-conversation model needs to remove.
- `POST /chat_create` (`agent-zero/api/chat_create.py:8-44`) — "New Chat".
  Creates a new `AgentContext` with a fresh guid (`guids.generate_id()`,
  line 11), optionally copying project/model-override data from the
  *current* context. Fires `mark_dirty_all()` (line 38) so all open tabs see
  the new context appear in their sidebar list.
- `POST /chat_reset` (`agent-zero/api/chat_reset.py:8-27`) — clears history of
  a given context **in place** (same id kept). This already is the "reset the
  one conversation" primitive we want to keep.
- `POST /chat_remove` (`agent-zero/api/chat_remove.py:7-34`) — deletes a
  context and its persisted files.
- `POST /chat_load` (`agent-zero/api/chat_load.py:6-17`) / `POST /chat_export`
  (`agent-zero/api/chat_export.py`) — JSON import/export; import always mints
  a new context (§2.2).
- `agent-zero/plugins/_chat_branching/api/branch_chat.py:78-147` — "Branch
  chat" — clones history up to a message into **another brand-new context**
  (not a parent/child link — no such field is persisted). Wired into the chat
  UI via `agent-zero/plugins/_chat_branching/extensions/webui/set_messages_after_loop/inject-branch-buttons.js`
  (a button under every past message). This is a 4th context-creation entry
  point that must be considered.
- `agent-zero/plugins/_chat_compaction/api/compact_chat.py:11-53` — manual,
  user-triggered summarization of one context's whole history into a single
  message (gated on a min-token threshold). Relevant infra for a long-lived
  single conversation (see §6.2); does not run automatically.

### 2.4 Frontend context id/session model

- `agent-zero/webui/components/sidebar/chats/chats-store.js` — Alpine store
  `chats`. State: `contexts: []` (all known contexts, populated from
  poll/push snapshots, sorted newest-first — `applyContexts()`, lines 54-69),
  `selected` (current ctxid).
  - `init()` (lines 32-51): on load, priority is (1) `?ctxid=` URL param
    ("open in new window" flow), else (2) `sessionStorage.getItem("lastSelectedChat")`.
    If neither is set, nothing is selected → welcome screen shows (§2.5).
  - `newChat()` (lines 162-178): `POST /chat_create` → `selectChat(new id)`.
  - `killChat()` (lines 96-122): `POST /chat_remove`.
  - `resetChat(ctxid=null)` (lines 145-159): `POST /chat_reset` — **already the
    exact "clear this conversation, keep identity" primitive** the redesign
    wants to keep exposed.
  - `setSelected()` (lines 289-299) persists the choice to
    `sessionStorage.lastSelectedChat` — the only "persist across reload"
    mechanism today, and it's per-browser-tab-storage, not a server-side
    default.
- `agent-zero/webui/index.js`:
  - `setContext(id)` (lines 526-563) — client-side context switch: resets
    log-tracking vars, clears `#chat-history` DOM, updates both
    `chatsStore`/`tasksStore` selection, and triggers a push-sync handshake
    (`syncStore.sendStateRequest`).
  - `deselectChat()` (lines 569-580) — `setContext(null)` + clears both
    `sessionStorage` keys → shows the welcome screen.
  - `sendMessage()` (lines 40-131) posts to `/message_async` with the
    in-memory `context` var (may be `""` on a truly fresh browser) and on
    success calls `setContext(jsonResponse.context)` to adopt whatever id the
    backend resolved/created.
  - `poll()` / snapshot application (~lines 370-410): if the previously
    selected context has vanished (deleted elsewhere), it falls back to
    `chatsStore.firstId()`, or calls `deselectChat()` if none remain at all —
    another source of nondeterminism the single-conversation model removes by
    construction (there's always exactly one, so this fallback branch becomes
    dead code).
- `agent-zero/helpers/state_snapshot.py:239-296` (server side of poll/push):
  builds the `contexts` list (→ sidebar "Chats") and `tasks` list (→ sidebar
  "Tasks") by walking `AgentContext.all()`, splitting on whether a
  `TaskScheduler` task is bound to that context id (lines 253-283). Scheduled
  Tasks are a **separate, unrelated concept** or Applicant campaign automation
  and are explicitly out of scope for this redesign — nothing here needs to
  change.

### 2.5 Sidebar UI

- `agent-zero/webui/components/sidebar/left-sidebar.html:21-29` composes the
  sidebar body: `<x-component path="sidebar/chats/chats-list.html">` inside
  `#chats-section`, then `<x-component path="sidebar/tasks/tasks-list.html">`
  inside `#tasks-section`. This is the file/line to touch to remove the Chats
  list from the shell.
- `agent-zero/webui/components/sidebar/chats/chats-list.html:14-73` — renders
  the "Chats" header, the "New Chat" icon button (line 17,
  `@click="$store.chats.newChat()"`), and a tree of
  `$store.chats.topLevelContexts()` with expand/collapse
  (`hasChildren`/`childContexts`/`isExpanded`/`toggleChildren`) and per-item
  `displayName()`.
  - **Pre-existing bug found during this investigation**: none of
    `topLevelContexts`, `hasChildren`, `childContexts`, `isExpanded`,
    `toggleChildren`, or `displayName` are defined anywhere in
    `chats-store.js` or any other `.js` file in the repo (verified with
    `grep -rn` across `agent-zero/` and `a0-applicant/` — zero hits besides
    the template call sites). `chats-store.js` itself is untouched since the
    vendor merge commit (`549408023`), while `chats-list.html` was rewritten
    by `e0de09f7f` ("unify left-sidebar visual style") to a tree-view markup
    that was apparently modeled on `tasks-list.html`'s parent/child pattern
    without porting the backing store methods. Net effect: **the Chats
    sidebar on this branch throws Alpine "is not a function" errors today** —
    moot once this file is replaced, but worth knowing it isn't a regression
    you'd be introducing.
- `agent-zero/webui/components/sidebar/top-section/header-icons.html` has
  three more entry points that create/select/clear chats:
  - Line ~40 and ~76: "Dashboard" button/menu item → `deselectChat()` (shows
    welcome screen).
  - Line ~128: "New Chat" dropdown item → `$store.chats.newChat()`.
  - Line ~136: "Load Chat" dropdown item → `$store.chats.loadChats()`.
  - Line ~139: "Save Chat" dropdown item → `$store.chats.saveChat()` (export;
    harmless to keep, exports current conversation as JSON).
  - Line ~143: **"Clear Chat" dropdown item already wired to
    `$store.chats.resetChat()`** behind a `$confirmClick` guard — this is the
    existing, already-shipped UI affordance for "reset the current
    conversation" and should be kept/relabeled rather than reinvented.
- `agent-zero/webui/components/welcome/welcome-store.js:17-19` — the welcome
  screen's visibility is purely `get isVisible() { return !chatsStore.selected; }`.
  `executeAction("new-chat")` (line 255-257) calls `chatsStore.newChat()`. In
  a world where a context is *always* selected, `isVisible` is permanently
  false and the welcome screen becomes dead code by construction — good, but
  its quick actions ("New Chat", "Scheduler", "Settings", "Plugins",
  "Projects", "Memory" — lines ~252-280) are also generically coding-agent
  flavored and not Applicant-relevant; worth a follow-up cleanup even though
  it'll no longer be reachable.

### 2.6 Where the freeform steering already lives

`a0-applicant/agents/applicant/prompts/agent.system.main.specifics.md` is the
system-prompt override for the "Applicant" agent persona used by these
contexts. It already states the agent (1) answers freeform questions, (2)
routes consequential job actions ("applying, submitting, saving a job")
through engine tool calls, never ad hoc, (3) routes "remember this" facts to
either the engine mind or A0 memory depending on content, and (4) must give
`apply_ready`/status answers only as projections of real engine data. **None
of this needs to change** — the single-conversation redesign is purely about
which `AgentContext` id the UI/backend always resolve to, not about the
agent's tool access or behavior.

### 2.7 Important adjacent finding: a second, separate "chat" surface already exists

`a0-applicant/webui/chat.html` (opened as a **modal**, via
`openModal('/plugins/applicant/webui/chat.html')` — confirmed by grepping every
`openModal(...)` call site; every `a0-applicant/webui/*.html` page, including
this one, is a modal layered on top of the vanilla Agent-Zero shell, not a
separate app/route) is a *different*, narrower chat implementation:

- Its Alpine component `chatPanel()` (`a0-applicant/webui/chat.html:78-95`)
  calls `plugins/applicant/chat` (`action: "history"` / `"send"`) and
  `plugins/applicant/campaigns` (`action: "list"`) — **not** `/message_async`
  and **not** `AgentContext` at all.
- The backend, `a0-applicant/api/chat.py`, is an explicit proxy: its own
  docstring (lines 1-14) says *"The Chat UI is served by the a0 shell, but the
  Applicant engine is internal-only ("api:8000"). This handler forwards the
  UI's calls to the engine's "/api/chat" API, keeping the engine the single
  source of truth for conversation state."* It also short-circuits "how do
  I…" messages into canned help content (`_detect_help_intent`,
  lines 32-67) before ever reaching the engine, and forwards
  attribute/criteria confirmation actions (`confirm`, `confirm_criteria`,
  lines 154-167) to dedicated engine endpoints.
- `_resolve_campaign_id()` (lines 89-109) **already assumes single-campaign**:
  a comment states *"Map missing/'__system__' campaign_id to the single active
  campaign (MVP is single-campaign)"* and resolves via `GET /api/campaigns`,
  picking the `active` one (or the first).

This means Applicant currently ships **two independent, non-interoperating
chat surfaces**: (a) the general-purpose AgentContext-backed "Applicant" AI
agent (main shell, sidebar, tool access — the one this spec's redesign
targets) and (b) a campaign-scoped, engine-proxied, narrower Q&A/confirmation
modal that bypasses the agent loop entirely. They have separate transcripts,
separate storage, and a user could plausibly hit either one and get a
different "memory" of what was discussed. This is a real product-level risk
independent of anything in this spec — see §5.1.

## 3. Proposed design

### 3.1 One canonical, deterministic context id

Replace "empty ctxid → arbitrary `AgentContext.first()` or brand-new random
id" with **one well-known id that both client and server always resolve to**,
so the same conversation reappears after any reload, on any tab, on any
device, forever (until the user explicitly resets it via the existing "Clear
Chat" action, §2.5).

Two reasonable choices, in order of recommendation:

1. **Derive the id from the engine's active campaign** (e.g.
   `f"campaign-{campaign_id}"`), reusing the exact
   resolve-and-cache pattern `a0-applicant/api/chat.py:89-109` already
   implements (`_resolve_campaign_id` + `GET /api/campaigns`, 30s TTL cache).
   This naturally unifies identity with the modal surface in §2.7 if that
   surface is ever retired/merged (§5.1), and pre-adapts for a future
   multi-campaign world (one persistent conversation *per campaign*, still
   "one conversation" from any given campaign's point of view) without
   another migration later.
2. **A hardcoded literal** (e.g. `"main"`), the minimal-diff MVP option if
   coupling the AI-agent context id to engine campaign state is undesired
   right now. Simpler, but will need revisiting the day Applicant supports
   more than one campaign per account.

Either way, the id must be computed identically on the frontend (for
`sessionStorage`/init) and the backend (for the `use_context` fallback and the
extension hook in §3.2) — factor it into one small shared helper, not two
copies that can drift.

### 3.2 Backend enforcement (no vendored-file edits required)

Two complementary layers, both in `a0-applicant` (keeps the diff inside the
product plugin rather than the upstream-tracked `agent-zero/` tree, matching
the existing separation convention):

- **Extension hook** at
  `a0-applicant/extensions/python/_functions/agent/AgentContext/__init__/start/_10_force_single_context.py`
  (new file) — an `Extension` subclass (same shape as
  `agent-zero/plugins/_model_config/extensions/python/_functions/agent/Agent/get_chat_model/start/_10_model_config.py`)
  that rewrites `data["kwargs"]["id"]` to the canonical id whenever a brand
  new `AgentContext` is about to be constructed. Because `AgentContext.get`/`use`
  is always tried first by every caller (`helpers/api.py:101-116`,
  `api/chat_create.py:14,17`, `api/chat_load.py`, `_chat_branching/api/branch_chat.py`),
  this hook only fires on genuine "doesn't exist yet" paths — it can't clobber
  a live context, it just guarantees that *if* something tries to mint a new
  one, it collapses onto the canonical id/context instead of a fresh random
  one. This is defense-in-depth against any entry point this spec's frontend
  changes miss (including future/third-party extensions).
- **`api/chat_create.py` guard**: with the hook in place, `CreateChat.process`
  (`agent-zero/api/chat_create.py:8-44`) becomes a no-op that just returns the
  canonical context's id instead of a new one — but since this file lives in
  vendored `agent-zero/`, prefer *not* editing it; the `__init__` hook alone
  is sufficient because `new_context = self.use_context(new_ctxid)` at line 17
  will resolve to the canonical context regardless of what `new_ctxid` the
  frontend sent, once "new_ctxid" is never actually a fresh unseen value (see
  §3.3 — the frontend stops calling `/chat_create` at all).

### 3.3 Frontend changes

All in `agent-zero/webui` (already the established pattern for UI
customization on this branch — `left-sidebar.html` and `chats-list.html` have
both been directly edited by product commits already, e.g. `e0de09f7f`,
`aa03fe903`):

1. **`chats-store.js`**
   - `init()` (lines 32-51): replace the `?ctxid=` / `sessionStorage`
     resolution with: always `selectChat(CANONICAL_CONTEXT_ID)` (constant or
     computed per §3.1). Drop the "nothing selected" branch entirely — there
     is never a "no context" state anymore.
   - `newChat()` (lines 162-178): delete, or repoint to just
     `selectChat(CANONICAL_CONTEXT_ID)` as a safe no-op for any stray caller
     during the transition.
   - `switchFromContext()` (lines 125-142) and the `firstId()`-fallback logic
     in `index.js` poll handling (~lines 393-403): dead code once there's
     only ever one context; safe to leave (harmless) or delete for clarity.
   - Keep `resetChat()`, `saveChat()`, `killChat()` as-is (killChat becomes
     unreachable from the UI but is harmless to leave for an admin/debug
     path).
2. **`chats-list.html`** — delete the list/tree markup and the "New Chat"
   button (lines 14-73) entirely. If a header row is still wanted for visual
   consistency with Tasks below it (or for the branding work already done in
   `e0de09f7f`), replace with a static, non-list header (e.g. "Campaign
   Conversation") plus, optionally, a single icon button wired to the
   existing `$store.chats.resetChat()` with its confirm dialog. Either way,
   this file's rewrite also incidentally fixes the pre-existing broken
   tree-view bug from §2.5.
3. **`left-sidebar.html:21-24`** — if `chats-list.html` is fully removed
   rather than replaced with a static header, drop the `#chats-section` block
   and its component include too.
4. **`header-icons.html`**:
   - "Dashboard" button/menu item (`deselectChat()`, lines ~40/~76) — decide
     product intent: either remove it (there's nothing to "deselect" to
     anymore) or repoint it to open Applicant's own dashboard modal
     (`a0-applicant/webui/main.html`/`today.html`) instead of clearing the
     chat context — flagged as an open question in §5.4, not a
     mechanical rename.
   - "New Chat" item (line ~128) — remove.
   - "Load Chat" item (line ~136) — remove (importing a JSON always mints a
     new context today, per §2.2/2.3 — fundamentally incompatible with "one
     conversation" unless it's changed to overwrite the canonical context's
     history in place, which is a bigger, riskier behavior change than this
     spec's scope).
   - "Save Chat" (export, line ~139) — keep; harmless, useful as a transcript
     backup.
   - "Clear Chat" (line ~143, already `resetChat()` + confirm) — keep as-is;
     this is the "reset the one conversation" affordance, already built.
5. **`welcome-store.js`** — `executeAction("new-chat")` (line 255-257): remove
   or repoint to `resetChat()`. Since `isVisible` (line 17-19) will now always
   be `false`, the whole welcome screen becomes unreachable; leaving the file
   otherwise alone is safe, but flag it for a later cleanup pass (dead code,
   not urgent).
6. **`_chat_branching`'s inject-branch-buttons.js`**
   (`agent-zero/plugins/_chat_branching/extensions/webui/set_messages_after_loop/inject-branch-buttons.js`)
   — this injects a "branch from here" button under every past message,
   whose whole purpose is to spin off a new, independent context. Disable
   this extension for the Applicant product surface (via the plugin's
   enable/disable mechanism used elsewhere, e.g. the `.toggle-N` marker files
   seen next to `_chat_compaction`/`_infection_check`, or by not registering
   the plugin at all for this product) — leaving it active directly
   contradicts "no way to spawn a sibling conversation."

### 3.4 Persistence across reloads

No new persistence mechanism is needed. `persist_chat.load_tmp_chats()`
(`agent-zero/helpers/persist_chat.py:54-71`) already restores every
`usr/chats/<ctxid>/chat.json` folder into a live `AgentContext` on boot; once
the canonical id is deterministic, this "just works" — reload, new tab, new
device, container restart, or day-2-vs-day-30 all land on the same
`usr/chats/<canonical-id>/chat.json`. The only genuinely new pieces are (a)
making the *id itself* deterministic (§3.1) and (b) making sure no code path
still mints a sibling (§3.2, §3.3).

## 4. Files to change (summary)

| File | Change |
|---|---|
| `agent-zero/webui/components/sidebar/chats/chats-store.js` | `init()` always selects canonical id; drop `newChat()`/fallback logic |
| `agent-zero/webui/components/sidebar/chats/chats-list.html` | Delete list/tree UI + New Chat button; optional static header + Reset action |
| `agent-zero/webui/components/sidebar/left-sidebar.html:21-24` | Drop `#chats-section` include if not replaced with a static header |
| `agent-zero/webui/components/sidebar/top-section/header-icons.html` | Remove "New Chat"/"Load Chat" items; decide fate of "Dashboard"; keep "Clear Chat"/"Save Chat" |
| `agent-zero/webui/components/welcome/welcome-store.js` | Repoint/remove `new-chat` quick action (becomes unreachable) |
| `agent-zero/plugins/_chat_branching/…` | Disable branch-button extension for Applicant surface |
| `a0-applicant/extensions/python/_functions/agent/AgentContext/__init__/start/_10_force_single_context.py` (new) | Force every newly-constructed context onto the canonical id |
| (new shared helper, frontend + backend) | Single source of truth for "what is the canonical context id" (literal or campaign-derived, §3.1) |

No changes needed to: the LLM/tool-calling loop, the "Applicant" agent system
prompt, the engine, `chat_reset`/`chat_export` endpoints, `state_snapshot.py`,
or the Tasks/scheduler sidebar section.

## 5. Risks / open questions

### 5.1 Two chat surfaces, one product

§2.7's `a0-applicant/webui/chat.html` modal is a second, independent
conversation with the engine that bypasses the AI agent/tool loop entirely
and already assumes single-campaign. Shipping "one always-on conversation" in
the main shell while this modal still exists as a *second* place to type
messages to "Applicant" is confusing at best (two different transcripts,
possibly two different answers to the same question) and contradicts the
stated goal at a product level. This spec does not redesign `chat.html` — it
should be decided explicitly whether to (a) retire it in favor of the single
conversation, (b) keep it as a deliberately distinct, narrower "quick
help/FAQ" surface with different, honest framing, or (c) merge it so it also
talks to the same canonical `AgentContext` (a bigger change than described
here, since it isn't wired for it at all). Flagging as a decision the product
owner needs to make, not an engineering detail.

### 5.2 Unbounded single-context growth

A context that is *never* replaced (only ever reset by explicit user action)
will accumulate history indefinitely over the life of a campaign — weeks or
months. Two mitigations already exist in the codebase and should be leaned
on rather than reinvented: Agent-Zero's built-in `History` auto-summarizes
older topics into "bulks" once a token budget is exceeded (referenced
elsewhere as already handling multi-week chats), and the
`_chat_compaction` plugin (`agent-zero/plugins/_chat_compaction/api/compact_chat.py`)
offers a manual, user-triggered full-history compaction with a minimum-token
gate. Worth deciding whether compaction should become *automatic* for the
single always-on conversation (since there's no longer a "start a fresh chat
when it gets unwieldy" escape hatch) rather than waiting on the user to
notice and trigger it manually.

### 5.3 Existing users may already have multiple real chats on disk

Any account that has already used the product will have several
`usr/chats/<ctxid>/` folders today. Switching to a canonical-id model doesn't
delete them, it just stops surfacing them in the UI (nothing lists arbitrary
contexts anymore) and stops the poll/push flow from ever selecting them.
Decide whether to (a) leave them orphaned on disk (harmless, just inert), (b)
write a one-time migration that picks the most-recently-active existing
context and renames/copies it to the canonical id so continuity is preserved
for current users, or (c) explicitly wipe them. (b) is the most user-friendly
but adds one-time migration code this spec doesn't design.

### 5.4 "Dashboard"/deselect semantics need a product decision

Today "Dashboard" (`deselectChat()`) means "show the welcome screen." In the
new model there's no meaningful "no chat" state to return to. Either repoint
this control to Applicant's own dashboard modal (`main.html`/`today.html`) or
remove it — a UX decision, not just a rename, since it changes what the user
lands on when they click "Dashboard" or the app's home icon.

### 5.5 Concurrency: one context, multiple tabs/devices

Nothing today prevents two open tabs (or a phone + a laptop) from both
targeting the canonical context simultaneously. This is a pre-existing
condition even today (per-tab, a user could already select the same context
twice), and `index.js:sendMessage()` already queues a second message via
`messageQueueStore` if the agent is `running` (`agent-zero/webui/index.js`
~lines 60-67) rather than racing — so the existing single-context-busy
handling should behave the same or better under this redesign, but it's
worth explicit verification once the canonical-id logic is live, since it's
no longer possible to "work around" a busy agent by opening a second chat
(that escape hatch is deliberately being removed).

### 5.6 Pre-existing bug incidentally fixed

`chats-list.html`'s tree-view (`topLevelContexts`/`hasChildren`/etc., see
§2.5) calls store methods that don't exist anywhere in the codebase today —
replacing this file per §3.3 removes the broken code path as a side effect,
but it's worth someone confirming this isn't presently throwing visible
console errors in production that anyone's been silently living with.

## 6. Non-goals (explicitly out of scope)

- The Tasks/Scheduler sidebar section and its underlying scheduled
  `AgentContext`s (`AgentContextType.TASK`) — unrelated automation runs, not
  touched by this redesign.
- Any change to the "Applicant" agent's system prompt, tools, or engine
  integration (§2.6) — already does freeform Q&A + action.
- Redesigning `a0-applicant/webui/chat.html` (§5.1) — flagged as a decision
  point, not designed here.
- Multi-campaign support — noted as a reason to prefer the campaign-derived
  canonical id (§3.1 option 1) over a hardcoded literal, but building actual
  multi-campaign UX is out of scope.
