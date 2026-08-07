# Work order: FE fixes — (A) show the active campaign, not empty __system__ + (B) rebrand to Applicant

**Branch:** `claude/refactor-agent-zero-applicant-xn7xoc`. Commit locally, **do NOT push**. These are PLUGIN/webui/proxy changes (no engine rebuild). Do FIX A first (it's the blocker: every panel currently shows an empty `__system__` workspace instead of the one active campaign `e827b520afcf4018ad48152b06e1ee84`, which holds 37 roles + 3 drafts).

## FIX A — proxy-side active-campaign resolution
Root cause: the `a0-applicant/api/*.py` proxies compute `cid = str(input.get("campaign_id") or "__system__")`, and FE panels omit campaign_id → they hit `/api/digest/__system__` → 0 rows. The engine has a real `active` flag (`GET /api/campaigns` returns each campaign's `active`). Fix is proxy-side only (smallest blast radius; engine untouched).

ARCHITECTURE CONSTRAINT: these proxy files are loaded individually via importlib (NOT as a package) — sibling imports are unreliable (that's why `_forward`/`_engine` are duplicated per file). So DUPLICATE the helper into each file (do NOT create a shared module). Add `import time` to each file's imports if missing.

Add this helper immediately AFTER the existing `_forward(...)` in each file listed below:
```python
_ACTIVE_CAMPAIGN_CACHE: dict = {"id": None, "ts": 0.0}
_ACTIVE_CAMPAIGN_TTL_S = 30


def _resolve_campaign_id(raw: str | None) -> str:
    """Map missing/'__system__' campaign_id to the single active campaign (MVP is
    single-campaign). Explicit non-system ids pass through. Fails CLOSED to the raw
    value on ANY problem (no campaign yet / engine down / pre-onboarding gate) so the
    pre-onboarding __system__ flow is unaffected."""
    cid = str(raw or "__system__").strip() or "__system__"
    if cid != "__system__":
        return cid
    now = time.time()
    if _ACTIVE_CAMPAIGN_CACHE["id"] and (now - _ACTIVE_CAMPAIGN_CACHE["ts"]) < _ACTIVE_CAMPAIGN_TTL_S:
        return _ACTIVE_CAMPAIGN_CACHE["id"]
    result = _forward("GET", "/api/campaigns")
    campaigns = result.get("data") if result.get("ok") else None
    if isinstance(campaigns, list) and campaigns:
        active = next((c for c in campaigns if isinstance(c, dict) and c.get("active")), campaigns[0])
        resolved = active.get("id") if isinstance(active, dict) else None
        if resolved:
            _ACTIVE_CAMPAIGN_CACHE["id"] = resolved
            _ACTIVE_CAMPAIGN_CACHE["ts"] = now
            return resolved
    return cid
```
Then replace the single `cid = ...` (or `campaign_id = ...`) default-assignment line with `cid = _resolve_campaign_id(<the raw input.get("campaign_id")>)` in EACH of these files (match each file's existing variable name + input accessor):
`digest.py, tracker.py, criteria.py, pending.py, ops.py, chat.py, agent_runs.py, discovery.py, research.py, onboarding.py, gallery.py, attributes.py, savejob.py`, and inside the relevant action branch for `easy_apply.py` (status), `screening.py` (library), `audit.py` (log).

- `base_resume.py`: it has no generic `_forward` (only a multipart `forward()`). Give it its own GET-only variant using its existing `urllib.request`/`json` imports (same fail-closed logic), then swap its `cid = ...` line.
- **DO NOT touch `vault.py`** — its `cid = cid or "__system__"` is genuinely instance-secret-scoped (SYSTEM_CAMPAIGN_ID = LLM keys/sandbox tokens). Resolving it would misfile credential lookups.
- **DO NOT touch `campaigns.py`** — it lists/creates campaigns, not scoped by one.

Tests: existing proxy unit tests (`test_az2_digest_proxy.py`, `test_az3_tracker_proxy.py`, `test_az2_attributes_proxy.py`, `test_az3_criteria_proxy.py`, `test_az2_chat_proxy.py`, `test_az2_pending_proxy.py`, `test_az3_research_proxy.py`, `test_az3_screening_proxy.py`, `test_az3_gallery_proxy.py`, `test_az3_discovery_proxy.py`, `test_easy_apply_proxy.py`, `test_audit_proxy.py`, `test_az12_onboarding_proxy.py`, `test_vault_proxy.py`) should ALL pass unchanged (their blanket `_forward` mock makes resolution fail-closed to __system__, so the final assertion is identical). Run them to confirm. ADD 1-2 new cases (e.g. in `test_az2_digest_proxy.py`) mocking `_forward` to return a realistic `/api/campaigns` list with an active campaign, asserting the digest call then forwards to that campaign's id.

## FIX B — rebrand "Agent Zero" -> "Applicant" (PLUGIN-OVERRIDE where possible; no A0-core prompt edits)
Prompt loader searches `plugins/<name>/prompts/` BEFORE `agent-zero/prompts/` and returns the first match — so override by creating same-named files under `a0-applicant/prompts/` (that dir already exists).

**B-1 (greeting) — create `a0-applicant/prompts/fw.initial_message.md`** (same JSON shape as the core one; change ONLY tool_args.text):
```json
{
    "thoughts": ["This is a new conversation, I should greet the user warmly and let them know I'm ready to help.", "I'll use the response tool with proper JSON formatting.", "A friendly emoji sets a welcoming tone."],
    "headline": "Greeting user and starting conversation",
    "tool_name": "response",
    "tool_args": {"text": "**Hello! 👋**, I'm **Applicant**, your AI job-search assistant. How can I help you today?"}
}
```

**B-2 (identity) — create `a0-applicant/prompts/agent.system.main.role.md`** overriding the core one; change the identity line (core says `"agent zero autonomous json ai agent"`) to `"applicant autonomous json ai job-search agent"`, leaving the rest of that role file's content identical to the core version (read the core file first and copy it, changing only the identity line).

**B-3 (titles/login/manifest) — edit A0-core webui (acceptable for this deployment):**
- `agent-zero/webui/index.html`: `<title>Agent Zero</title>` -> `<title>Applicant</title>`
- `agent-zero/webui/login.html`: `<title>Login - Agent Zero</title>` -> `Login - Applicant`; `alt="Agent Zero Logo"` -> `alt="Applicant Logo"`; `<h2>Agent Zero</h2>` -> `<h2>Applicant</h2>`
- `agent-zero/webui/js/manifest.json`: `"name"`/`"short_name"` "Agent Zero" -> "Applicant".

**B-5 (settings-page sweep) — OPTIONAL fast-follow, lower priority.** Replace visible prose "Agent Zero"/"Agent-Zero" -> "Applicant" across the settings component HTML/JS, BUT preserve: any URL (github.com/agent0ai, agent-zero.ai), localStorage/wire keys (`agent_zero_tunnel_url`, `agent_zero_version`), the `agent-zero-backup-` filename prefix, and MCP example config keys (`"agent-zero"`/`"agent-zero-http"` — verify before changing). Also `a0-applicant/webui/connections.html` "main Agent Zero menu" -> "main Applicant menu". Do B-1/B-2/B-3 first and commit; B-5 can be a second commit.

## Commit + verify
FIX A: `cd /a0/usr/projects/applicant && uv run python -m pytest tests/unit/test_az2_digest_proxy.py tests/unit/test_az3_tracker_proxy.py tests/unit/test_az2_attributes_proxy.py tests/unit/test_az3_criteria_proxy.py tests/unit/test_vault_proxy.py -q --tb=short` (all green; vault unaffected). Commit: `fix(ui): resolve active campaign for FE panels so digest/tracker/etc. show the real campaign, not empty __system__ [FR-UI]`.
FIX B: commit `feat(ui): rebrand shell to Applicant (greeting, identity, titles/login/manifest) [FR-UI]`.
Report exact files changed + test counts. (Plugin/webui/prompt files → I hot-patch docker-a0-1 + restart to deploy.)
