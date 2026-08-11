# Spec — Diagnostic / Debug Admin dashboard (in-app, no terminal required)

Status: **proposed**. Author: Claude (spec pass). Scope owner: Applicant engine + a0 shell webui.

## 0. Goal

The operator currently has to `docker logs docker-api-1` (or shell into the container) to see
what the running instance is actually doing — scheduler ticks, discovery/scoring activity, LLM
routing decisions, errors. This spec adds an **in-app "Debug" panel** that surfaces:

1. A **live-tailing log stream** (level filter, search, pause, clear) over the engine's
   structured logs.
2. **Scheduler / agent-run status** (heartbeat, last/next tick, today's counts).
3. **Discovery/scoring counts** (discovered postings, pipelines started, LLM calls — this tick
   and today).
4. **LLM endpoint health** (which endpoints are configured, online/offline).

No terminal access required; everything is reachable from the sidebar.

## 1. What already exists (read before building — most of this is NOT new work)

This system already has most of the plumbing. Do not rebuild any of the following:

### 1.1 The log ring buffer (already redacted, already bounded)

`src/applicant/observability/logging.py` configures structlog with a processor chain
(`configure_logging`):

```
contextvars -> _add_correlation_id -> add_log_level -> TimeStamper
  -> _redact_secrets -> _capture_log -> renderer (JSON in prod)
```

- `_redact_secrets` / `_redact_value` / `_redact_text` already mask secret-named keys
  (`_SECRET_KEYS`) AND secret-*shaped* values embedded in free text (JWTs, `sk-...` keys,
  bearer tokens, `password=...`, URL userinfo, high-entropy tokens) — this runs **before**
  capture, so anything landing in the ring buffer (or stdout) is already redacted
  (NFR-PRIV-1). **No new redaction work is needed.**
- `_capture_log` appends every log event into `_LOG_RING`, a `collections.deque(maxlen=500)`
  module-global. `recent_logs(limit=100)` returns the newest `limit` entries.
- This is already wired end-to-end: `AdminQueryService.logs()` (in
  `src/applicant/application/services/admin_query_service.py:250`) calls `recent_logs`; the
  router `GET /api/admin/logs` (in `src/applicant/app/routers/admin.py`) calls
  `admin_query.logs(...)`; the whole `/api/admin/*` router is already gated behind
  `Depends(require_llm_configured)` (FR-UI-5) and is only reachable from inside the docker
  network (`api:8000` is never published).
- The a0-shell proxy `a0-applicant/api/ops.py` already forwards `action: "logs"` to
  `GET /api/admin/logs`, and `a0-applicant/webui/ops.html` already renders a (manual-refresh,
  no filter/search) log list under its "📄 Engine Logs" section.

**Implication:** the backend transport (ring buffer -> HTTP GET -> plugin proxy -> webui) is
proven and live today. What's missing is (a) a *live/incremental* read (cursor, not
"replace the whole list every refresh"), and (b) a **dedicated** panel with filter/search/
pause/clear plus the status/health widgets — Ops bundles unrelated tool-toggle/history/
detections concerns and is not the right home for a fast-polling live tail.

### 1.2 Scheduler + agent-run status (already returns everything needed)

`GET /api/agent-runs/{campaign_id}/status` (`src/applicant/app/routers/agent_runs.py`,
backed by `AgentRunService.status()` in
`src/applicant/application/services/agent_run_service.py:190` plus
`Scheduler.state()`/`Scheduler.campaign_health()` in
`src/applicant/application/services/scheduler.py:528`) already returns, in one call:

```jsonc
{
  "campaign_id": "...",
  "active": true, "paused": false,
  "run_mode": "continuous",
  "throughput_target": 10, "daily_budget": 10, "applied_today": 3,
  "latest_intent": "...",
  "latest_stats": {                 // written by AgentLoop._run_campaign_tick (agent_loop.py:2298)
    "discovered": 12,               // <- discovery count
    "digest_rows": 4,
    "pipelines_started": 3,
    "handoffs": 1,
    "completed": 2,
    "budget_remaining": 7,
    "tokens_in": 18234, "tokens_out": 2110,   // present only if a usage ledger is wired
    "cost_usd_estimate": 0.04, "llm_calls": 9  // <- scoring/LLM-call proxy count
  },
  "last_run_at": "2026-08-06T...",
  "scheduler": {                    // Scheduler.state()
    "running": false,
    "last_tick": "2026-08-06T...", "next_tick": "2026-08-06T...",
    "interval_seconds": 60,
    "now": "2026-08-06T...",
    "metrics": { ... tick totals / success-failure / stall-alert heartbeat ... },
    "campaign": { ... tick failures / overlap-skips for THIS campaign, only if any ... }
  }
}
```

This already covers **both** "scheduler/agent-run status" and "discovery/scoring counts" — the
debug panel needs to call this endpoint and render fields that already exist. **No new backend
endpoint needed for this section.** The existing proxy `a0-applicant/api/agent_runs.py`
(`action: "status"`) already forwards it.

Relevant log events already emitted (visible once the log tail ships):
`scheduler_tick` (`scheduler.py:394`, fields: `campaigns`, `ladder_fired`, `tick_ok`,
`curation_reviewed`, `status_updates`, `inbox_scanned`, `inbox_matched`, ...),
`scheduler_tick_error` / `scheduler_tick_finally_failed` (failure paths),
`llm_router_selected` (`src/applicant/adapters/llm/smart_router.py:104`, fields: `task`,
`endpoint`, `score`), `discovery_source_failed` / `rate_limit_skip`
(`src/applicant/adapters/discovery/jobspy_searxng.py`), `discovery_declined_no_criteria`
(`agent_loop.py:746`).

### 1.3 LLM endpoint health (already exists)

`GET /api/model-endpoints` (action `list`) via the existing
`a0-applicant/api/model_endpoints.py` proxy already returns each configured endpoint with its
online/offline probe result and model type. **Reuse directly — no new backend work.**

### 1.4 The panel + polling pattern to model this on

- `a0-applicant/webui/today.html` — canonical panel shape: single `<style>` block scoped by a
  panel-specific class prefix (`.atoday …`), one root `<div class="atoday" x-data="todayPanel()">`,
  a `<script>` IIFE that imports `/js/api.js` and wraps `callJsonApi` to prefix
  `plugins/applicant/`, and `window.Alpine.data("todayPanel", () => ({ ... }))`.
- `a0-applicant/webui/update.html` — **the live-polling precedent to copy verbatim in shape**:
  ```js
  async init() {
    await this.fetchStatus();
    this.timerId = setInterval(() => { if (cond) this.fetchStatus(); }, 10000);
  },
  destroy() {
    if (this.timerId) { clearInterval(this.timerId); this.timerId = null; }
  },
  ```
  This is the only existing Applicant panel that already does interval polling + teardown;
  the debug panel's log-tail/status timers should follow this exact `init()`/`destroy()` shape.
- `a0-applicant/webui/ops.html` — shows the existing (non-live) log rendering to *not* duplicate
  wholesale; the debug panel supersedes its log section for live use (Ops's log section can stay
  as-is, or a later cleanup can point it at the debug panel — out of scope here).
- Proxy shape to copy: `a0-applicant/api/ops.py` / `agent_runs.py` / `model_endpoints.py` all
  share the identical `_engine()` / `_forward(method, path, body, timeout=10)` / `dispatch(input)`
  / `class X(ApiHandler): async def process(...)` skeleton. Copy this skeleton verbatim for the
  new proxy (section 2.3).

## 2. Backend changes (small, additive)

### 2.1 `src/applicant/observability/logging.py` — add a cursor (`seq`) to ring-buffer entries

Today `recent_logs(limit)` only supports "give me the last N", which forces a polling client to
either re-render everything each poll or diff by content. Add a monotonic sequence number so a
poller can ask for "everything since the last thing I saw":

- Add a module-level counter (plain `itertools.count()` is fine — the engine is a single
  Uvicorn process with no `--workers`, matching the existing single-process assumption the ring
  buffer already makes).
- In `_capture_log`, stamp `entry["seq"] = next(_SEQ)` before appending to `_LOG_RING`.
- Change `recent_logs` to:
  ```python
  def recent_logs(limit: int = 100, since_seq: int | None = None) -> list[dict]:
      items = list(_LOG_RING)
      if since_seq is not None:
          items = [e for e in items if e.get("seq", -1) > since_seq]
      return items[-limit:] if limit else items
  ```
  (`since_seq` takes priority as the filter; `limit` still caps the page size either way so a
  huge gap — e.g. the panel was closed for an hour — can't return an unbounded burst.)

### 2.2 `AdminQueryService.logs` + `GET /api/admin/logs` — thread `since_seq` through

- `src/applicant/application/services/admin_query_service.py:250` —
  `def logs(self, limit: int = 100, since_seq: int | None = None) -> list[dict]: return recent_logs(limit, since_seq)`.
- `src/applicant/app/routers/admin.py` — extend the existing `logs()` handler:
  ```python
  @router.get("/logs")
  def logs(
      limit: int = 100, since_seq: int | None = None,
      admin_query=Depends(get_admin_query_service),
  ) -> dict:
      entries = admin_query.logs(max(0, min(limit, 1000)), since_seq)
      latest_seq = entries[-1]["seq"] if entries else since_seq
      return {"entries": entries, "latest_seq": latest_seq, "status": "live"}
  ```
  `latest_seq` is echoed back even when `entries` is empty (falls back to the caller's own
  `since_seq`) so a poller can always advance its cursor without special-casing "nothing new".
  This is backward compatible: `since_seq` is optional, existing callers (Ops) are unaffected.

### 2.3 New plugin proxy `a0-applicant/api/adminlogs.py`

A dedicated proxy, kept separate from `ops.py`, because the log tail polls on a much faster
cadence (~2s) than Ops's tool/history/detections calls — coupling them would mean every fast
log poll also implies re-fetching unrelated Ops state, or splitting `ops.py`'s single
`dispatch` in ways that blur its existing contract. Copy the exact skeleton from `ops.py` /
`agent_runs.py`:

```python
"""AdminLogs proxy — live/paginated engine log tail for the Debug panel.

The Debug panel polls this on a fast (~2s) cadence for a live-tailing log view, separate
from the Ops console's slower, aggregate admin calls (history/detections/tools). Forwards to
the engine's already-redacted, ring-buffered "/api/admin/logs" (FR-LOG-3 / FR-OBS-2). One
action dispatched by "action": "tail" (GET, params: limit, since_seq).

Self-contained (plugin sibling-imports are unreliable); the pure "dispatch"/"_forward" logic
is module-level so it is unit-testable without the framework.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from helpers.api import ApiHandler
from flask import Request


def _engine() -> str:
    return os.getenv("ENGINE_URL", "http://api:8000").rstrip("/")


def _forward(method: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(f"{_engine()}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "{}"
            return {"ok": True, "status": r.status, "data": json.loads(raw) if raw.strip() else {}}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": e.read().decode()[:300]}
    except Exception as e:
        return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}"}


def dispatch(input: dict) -> dict:
    action = str((input or {}).get("action") or "tail").strip().lower()

    if action == "tail":
        limit = int((input or {}).get("limit") or 200)
        since_seq = (input or {}).get("since_seq")
        qs = f"?limit={limit}"
        if since_seq is not None:
            qs += f"&since_seq={int(since_seq)}"
        return _forward("GET", f"/api/admin/logs{qs}")

    return {"ok": False, "status": 400, "error": f"unknown adminlogs action {action!r}"}


class AdminLogs(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
```

### 2.4 Why NOT SSE/websocket, and why NOT tailing container stdout

The task asks to evaluate both; the recommendation is **poll-over-the-existing-ring-buffer**
(2.1–2.3 above), for concrete reasons specific to this codebase, not just general preference:

- **SSE/websocket** would need a new transport path through the a0-shell, because every existing
  plugin proxy (`ops.py`, `agent_runs.py`, `model_endpoints.py`, and 30+ others) is a one-shot
  JSON `dispatch(input) -> {ok, status, data|error}` call — `_forward` does a single
  `urllib.request.urlopen` and reads the whole body; it does not stream. The engine *does* have a
  real streaming primitive already — `src/applicant/app/routers/realtime.py`, a multiplexed
  WebSocket with a `{chan, type, seq, data}` frame envelope and a server-side
  `authorize_upstream` safety seam — but that machinery exists specifically for **consequential,
  bidirectional** control channels (live browser takeover). Bolting a one-way log feed onto it
  means adding a new channel to the envelope/authorization seam for a read-only feature that
  doesn't need bidirectional control — disproportionate complexity for this ask. A 2s poll against
  a 500-entry, already-JSON, already-redacted in-memory buffer is indistinguishable from "live" to
  a human watching a dashboard, and needs zero new transport.
- **Tailing container stdout** (`docker logs -f docker-api-1` from inside `agent-zero`) would
  require mounting the Docker socket into a shell container — a real trust-boundary widening the
  codebase explicitly avoids elsewhere (the engine is deliberately "internal-only", per
  `admin.py`'s and `realtime.py`'s own docstrings). It would also mean re-parsing text/JSON lines
  outside the structlog pipeline, re-deriving what's already free from the ring buffer (bounded
  size, guaranteed-redacted, structured dicts), and would break if the container's log driver
  isn't `json-file` or if `stdout` ever carries a non-structlog line (e.g. a raw `print()` or a
  library warning) that never passed through `_redact_secrets`. The in-process ring buffer has
  neither of these gaps.

### 2.5 Security note

Single-user local instance, but keep the existing guarantees intact rather than adding new ones:

- Redaction is already applied before capture (1.1) — do not add a second redaction pass in the
  proxy or the webui; keep the engine the single point of truth for what's safe to display
  (avoids the two-copies-drift risk the codebase's own `redact_text` docstring calls out).
- `/api/admin/*` is already gated by `require_llm_configured` and only reachable from inside the
  docker network — no new auth is being added or is needed here; don't accidentally loosen this
  by, e.g., proxying `/api/admin/logs` through anything public.
- Do not persist log entries anywhere outside the existing bounded in-memory ring (no new file/
  DB sink) — keeps the "bounded, ephemeral, redacted" property that makes this safe by
  construction.

## 3. Frontend: `a0-applicant/webui/debug.html`

New panel, modeled structurally on `today.html` (style scoping, root `x-data`, `callJsonApi`
wrapper) and on `update.html` for the polling/`destroy()` lifecycle. Four sections in one panel.

### 3.1 Layout

```
🐞 Debug  [?]
sub: "Live engine diagnostics"

[Section: Live log tail]
  toolbar: [level: All/Debug/Info/Warning/Error ▾]  [search box]  [Pause/Resume]  [Clear]
  scrolling monospace log view (auto-scroll to bottom unless paused or user has scrolled up)
  each line: timestamp · [LEVEL] · event · key=value ... (compact, click to expand raw JSON)

[Section: Scheduler / agent-run status]
  campaign picker (same <select> pattern as ops.html; default to first campaign or "__system__")
  running: yes/no · last tick: … · next tick: … · interval: …s
  latest intent: "…"
  applied today: N / daily budget: N

[Section: Discovery / scoring counts]   (same status payload, different fields — no extra call)
  discovered: N  ·  pipelines started: N  ·  handoffs: N  ·  completed: N
  LLM calls: N  ·  tokens in/out: N/N  ·  est. cost: $N   (omit the last three if absent)

[Section: LLM endpoint health]
  table: name · base_url · model_type · ● online / ○ offline
  [Refresh]
```

### 3.2 Alpine component skeleton

```html
<link rel="stylesheet" href="/plugins/applicant/webui/applicant-theme.css">
<style>
  .adebug{max-width:820px;margin:0 auto;padding:8px 4px;color:var(--color-text);font-family:inherit}
  /* ... reuse the exact today.html/.aops token set (h1, .sub, .err, .btn, .btn.primary,
     .loading, .spinner, .section, table styles) with an .adebug prefix instead of
     .atoday/.aops, so the panel matches house style without inventing new tokens ... */
  .adebug .log-view{background:var(--color-panel,#f2f5f7);border:1px solid var(--color-border,#d8e0e6);
    border-radius:8px;padding:8px 10px;font-family:monospace;font-size:.76rem;
    max-height:420px;overflow-y:auto;white-space:pre-wrap;word-break:break-word}
  .adebug .log-line{padding:2px 0;border-bottom:1px solid var(--color-border,#d8e0e6)}
  .adebug .log-line.level-error{color:var(--color-danger-text,#9b1c1c)}
  .adebug .log-line.level-warning{color:var(--color-warning-text,#856404)}
</style>

<div class="adebug" x-data="debugPanel()">
  <h1>🐞 Debug <button class="help-btn" onclick="window.openModal('/plugins/applicant/webui/help.html?surface=debug')" title="Help for debug">?</button></h1>
  <div class="sub">Live engine diagnostics</div>

  <!-- Live log tail -->
  <div class="section">
    <h2>📜 Live log</h2>
    <div class="toolbar">
      <select x-model="levelFilter"><option value="">All levels</option>
        <option value="debug">Debug</option><option value="info">Info</option>
        <option value="warning">Warning</option><option value="error">Error</option></select>
      <input type="text" placeholder="Search…" x-model="search">
      <button class="btn" @click="paused = !paused" x-text="paused ? '▶ Resume' : '⏸ Pause'"></button>
      <button class="btn" @click="lines = []">🗑 Clear</button>
    </div>
    <div class="log-view" x-ref="logView">
      <template x-for="l in filteredLines" :key="l.seq">
        <div class="log-line" :class="'level-' + (l.level || 'info')" x-text="formatLine(l)"></div>
      </template>
    </div>
    <div class="err" x-show="logError" x-text="logError"></div>
  </div>

  <!-- Scheduler / agent-run status + discovery/scoring counts -->
  <div class="section">
    <h2>⏱️ Scheduler &amp; run status</h2>
    <select x-model="campaignId" @change="fetchStatus()"> ... same pattern as ops.html ... </select>
    <div class="info-box">
      <!-- running / last_tick / next_tick / interval / latest_intent / applied_today -->
      <!-- discovered / pipelines_started / handoffs / completed / llm_calls / cost -->
    </div>
    <div class="err" x-show="statusError" x-text="statusError"></div>
  </div>

  <!-- LLM endpoint health -->
  <div class="section">
    <h2>🔌 LLM endpoints</h2>
    <button class="btn" @click="fetchEndpoints()">↻ Refresh</button>
    <table> ... name / base_url / model_type / online badge ... </table>
    <div class="err" x-show="endpointsError" x-text="endpointsError"></div>
  </div>
</div>

<script>
  (() => {
  (() => {
  const _apiP = import("/js/api.js");
  const callJsonApi = async (ep, ...a) => (await _apiP).callJsonApi((ep && String(ep).startsWith("plugins/")) ? ep : ("plugins/applicant/" + ep), ...a);

  window.Alpine.data("debugPanel", () => ({
    // log tail state
    lines: [], sinceSeq: null, paused: false, levelFilter: "", search: "",
    logError: "", logTimerId: null,
    // status state
    campaigns: [], campaignId: "__system__", status: null, statusError: "", statusTimerId: null,
    // endpoint state
    endpoints: [], endpointsError: "",

    get filteredLines() {
      return this.lines.filter(l =>
        (!this.levelFilter || l.level === this.levelFilter) &&
        (!this.search || JSON.stringify(l).toLowerCase().includes(this.search.toLowerCase()))
      );
    },
    formatLine(l) {
      const kv = Object.entries(l).filter(([k]) => !["event","level","timestamp","seq"].includes(k))
        .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(" ");
      return `${l.timestamp || ""} [${(l.level || "info").toUpperCase()}] ${l.event || ""} ${kv}`;
    },

    async init() {
      await this.pollLogs();
      this.logTimerId = setInterval(() => { if (!this.paused) this.pollLogs(); }, 2000);

      const campR = await callJsonApi("campaigns", { action: "list" });
      this.campaigns = (campR && campR.ok && campR.data && campR.data.campaigns) || [];
      if (this.campaigns.length) this.campaignId = this.campaigns[0].id || this.campaigns[0].name;
      await this.fetchStatus();
      this.statusTimerId = setInterval(() => this.fetchStatus(), 5000);

      await this.fetchEndpoints();
    },

    destroy() {
      if (this.logTimerId) { clearInterval(this.logTimerId); this.logTimerId = null; }
      if (this.statusTimerId) { clearInterval(this.statusTimerId); this.statusTimerId = null; }
    },

    async pollLogs() {
      const r = await callJsonApi("adminlogs", { action: "tail", limit: 200, since_seq: this.sinceSeq });
      if (!r || !r.ok) { this.logError = (r && r.error) || "Couldn't reach the log engine."; return; }
      this.logError = "";
      const entries = (r.data && r.data.entries) || [];
      if (entries.length) {
        this.lines.push(...entries);
        if (this.lines.length > 1000) this.lines.splice(0, this.lines.length - 1000); // client-side cap
      }
      if (r.data && r.data.latest_seq != null) this.sinceSeq = r.data.latest_seq;
      // auto-scroll unless the user has scrolled up (check scrollTop vs scrollHeight before appending)
    },

    async fetchStatus() {
      const r = await callJsonApi("agent_runs", { action: "status", campaign_id: this.campaignId });
      if (!r || !r.ok) { this.statusError = (r && r.error) || "Couldn't reach the agent-run engine."; return; }
      this.statusError = "";
      this.status = r.data;
    },

    async fetchEndpoints() {
      const r = await callJsonApi("model_endpoints", { action: "list" });
      if (!r || !r.ok) { this.endpointsError = (r && r.error) || "Couldn't reach the model-endpoints engine."; return; }
      this.endpointsError = "";
      this.endpoints = (r.data && r.data.endpoints) || (r.data && r.data.items) || [];
    },
  }));
  })();
  })();
</script>
```

Notes for the implementer:
- Verify the exact response shape of `model_endpoints` `action: "list"` (`endpoints` vs `items`
  key) by reading `a0-applicant/webui/model_endpoints.html` before wiring section 4 — it already
  consumes this same call and shows the real field names.
- `pollLogs`'s `since_seq: null` on the very first call must be sent as *absent/null*, not `0`
  (0 would skip the seq-0 entry if the ring buffer numbering starts at 0) — the proxy in 2.3
  already handles `since_seq is None` by omitting the query param.
- Client-side `lines` cap (1000) is independent of the server's 500-entry ring — the client can
  reasonably keep more history across polls than the server buffer holds at any instant.

### 3.3 Sidebar entry

Add one button to `a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html`
(the file backing the `sidebar-quick-actions-main-start` breakpoint — currently 40 buttons in this
exact repeated shape), placed after the existing "Ops" button:

```html
<button class="sidebar-action" @click="window.openModal('/plugins/applicant/webui/debug.html')">
    <span class="material-symbols-outlined">bug_report</span>
    <span class="label">Debug</span>
</button>
```

## 4. Build checklist (smallest safe slices first)

Each slice should be independently shippable/testable; do not batch them.

1. **`logging.py`: add `seq` to ring-buffer entries.** Add the counter, stamp `seq` in
   `_capture_log`, extend `recent_logs(limit, since_seq=None)`. Unit-test:
   log N events, call `recent_logs(since_seq=k)`, assert only entries with `seq > k` come back,
   newest-last ordering preserved. No API/UI change yet — purely internal.
2. **`AdminQueryService.logs` + `GET /api/admin/logs`: thread `since_seq`, add `latest_seq`.**
   Keep `since_seq` optional so the existing `ops.py` (`action: "logs"`, no `since_seq`) is
   unaffected. Test: existing Ops log fetch still returns the same shape plus one new
   `latest_seq` key; a fetch with `since_seq` set returns only newer entries.
3. **New proxy `a0-applicant/api/adminlogs.py`.** Copy the `ops.py` skeleton, single `tail`
   action. Test the pure `dispatch()`/`_forward()` functions directly (per the module's own
   "self-contained, unit-testable without the framework" convention) with a fake urlopen.
4. **`debug.html` — log tail section only.** Root panel, log-view, level filter, search, pause,
   clear, 2s poll + `destroy()` cleanup, wired to `adminlogs`. Verify in a real browser
   (per this project's playtest-visual-verification standard) that: entries stream in without a
   full re-render/flicker, pause actually stops new lines from appearing, clear empties the view
   without duplicating on the next poll, and level filter + search compose correctly.
5. **`debug.html` — scheduler/status + discovery/scoring section.** Wire the existing
   `agent_runs` proxy `action: "status"` with the same campaign-picker pattern as `ops.html`;
   render `scheduler.*` and `latest_stats.*` fields verbatim (no new backend call). Verify against
   a campaign with at least one completed tick so `latest_stats` is non-empty.
6. **`debug.html` — LLM endpoint health section.** Wire the existing `model_endpoints` proxy
   `action: "list"`; confirm the real response key names against `model_endpoints.html` before
   assuming `endpoints`/`items`. Manual refresh button is sufficient (endpoints change rarely) —
   no timer needed.
7. **Sidebar entry.** Add the "Debug" button to
   `a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html`. Open the
   panel from the sidebar end-to-end once as the final integration check.
8. *(Optional polish, not required to ship)*: a `help.html?surface=debug` topic; a "raw JSON"
   expand/collapse per log line instead of the flattened `k=v` string; a toast/log-line highlight
   when a `scheduler_tick_error` or `discovery_source_failed` event arrives, since those are the
   two failure events an operator most wants to notice without reading every line.
