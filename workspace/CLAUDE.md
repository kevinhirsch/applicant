# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Firehouse is a self-hosted, multi-user AI workspace: a FastAPI (Python 3.11+) backend, a vanilla-JS front-end (no framework, ES6 modules served statically), SQLite/SQLAlchemy persistence, and a provider-agnostic LLM layer with an agentic tool loop. It bundles chat, an agent, deep research, model comparison, a document editor, persistent memory/skills, email, calendar, notes/tasks, image generation/editing, and "Cookbook" (hardware-aware local model serving).

## Commands

```bash
# Run the app (manual dev; bind 127.0.0.1 unless you intend LAN access)
python -m uvicorn app:app --host 127.0.0.1 --port 7000
python setup.py                      # first-run: creates data/ dirs, DB, admin user (safe to re-run)

# Docker (recommended for full-stack testing — bundles chromadb, searxng, ntfy)
docker compose up -d --build
docker compose logs --tail=120 firehouse
docker compose config                # validate compose changes

# Tests (pytest, asyncio_mode=auto, testpaths=tests)
python -m pytest                     # full suite
python -m pytest tests/test_agent_loop.py            # single file
python -m pytest tests/test_agent_loop.py::test_name # single test
python -m pytest -k "owner_scope"    # by keyword

# Lint / syntax checks (no formatter is enforced; these are the CI-equivalent checks)
python -m py_compile app.py routes/*.py src/*.py
node --check static/js/<file-you-changed>.js   # front-end has no build step
```

Note: some `tests/test_*_js.py` files shell out to `node --check` to validate front-end modules, so Node must be available for the full suite. The first-run admin password is printed to the terminal (or `docker compose logs firehouse`).

## Layered architecture (the big picture)

Requests flow top-down through clearly separated layers. Understanding the boundaries matters more than any single file:

```
static/ (browser SPA)  →  app.py (FastAPI + middleware/auth gate)  →  routes/ (thin HTTP)
   →  src/ (business logic / AI engine)  →  services/ + mcp_servers/  →  core/ (foundation)
   →  SQLite (app.db) · ChromaDB (vectors) · JSON state files · external services
```

- **`core/`** — foundation. `auth.py` (`AuthManager`: bcrypt, TOTP 2FA, session tokens, per-user privileges), `database.py` (SQLAlchemy 2.x models, `EncryptedText` Fernet columns), `session_manager.py` (sessions with **lazy message hydration** — metadata loads at boot, messages on first read), `middleware.py` (CSP-nonce security headers, `require_admin`), `atomic_io.py` (crash-safe JSON writes used for all `data/*.json` state).
- **`routes/`** (~47 modules) — thin HTTP layer, one `APIRouter` per feature, registered in `app.py`. Logic lives in `src/`; route files lean on shared `*_helpers.py` and dependency-injected auth/privilege gates.
- **`src/`** (~80 modules) — the AI engine and business logic. This is where real work happens.
- **`services/`** — self-contained subsystems (`search/`, `memory/`, `research/`, `shell/`, `docs/`, `hwfit/` Cookbook, `stt/`, `tts/`, `youtube/`, `faces/`).
- **`mcp_servers/`** — built-in MCP servers exposing internal capabilities to the agent (`email`, `memory`, `rag`, `image_gen`).
- **`static/`** — vanilla-JS PWA. `app.js` orchestrates ~132 ES6 modules; URL-routed views; large self-contained `editor/` image editor (~45 files) and `compare/` module. No bundler — modules load natively, so edits need no build, only `node --check`.

## Key cross-cutting concepts

**Auth has three request pathways** (all handled in `app.py`'s auth gate):
1. Cookie session (`firehouse_session`), validated via `AuthManager`.
2. `Bearer ody_*` API tokens — prefix-indexed in-memory cache, bcrypt-verified per request, scoped.
3. `X-Firehouse-Internal-Token` loopback — lets the agent's tool layer call admin-gated `/api/*` routes in-process (and impersonate an owner via `X-Firehouse-Owner`).

**Ownership/multi-user model.** Most data is owner-scoped via the `owner` column. The standard filter is `owner == user OR owner IS NULL` (see `src/auth_helpers.py` `owner_filter`). Admins bypass privilege checks; an hourly startup sweep reassigns null-owner rows to the primary admin. When adding any user-data route, scope queries with the existing owner helpers — there are many `*_owner_scope` / `*_isolation` regression tests guarding this.

**LLM layer is provider-agnostic** (`src/llm_core.py`). It auto-detects and normalizes payloads + streaming for Anthropic (`/v1/messages`, `tool_use`), OpenAI-compatible (vLLM/llama.cpp/SGLang), Ollama, OpenRouter, Groq, and others. Has fallback chains with dead-host cooldown and cross-chunk tool-call accumulation. `endpoint_resolver.py` + `model_discovery.py` turn settings keys into concrete (URL, model, headers) and scan hosts/ports for available models.

**The agent loop** (`src/agent_loop.py`, `agent_tools.py`, `agent_runs.py`) builds a system prompt (tools + active document + skills index + time), streams the model, parses tool blocks (fenced code blocks *or* native function-calls), executes, and loops up to ~20 rounds. There are ~60 tools (bash, python, web, files, email, calendar, memory, skills, `app_api` generic loopback, `ui_control` to drive the front-end). `agent_runs.py` makes runs **durable**: a background task drains the stream into a replay buffer so SSE clients can disconnect/reconnect without killing the run.

**Chat pipeline** (`src/chat_processor.py`, `chat_handler.py`): preprocess (URL/YouTube/image vision) → build context preface (hybrid BM25+vector memory, RAG docs, web search, skills index) → mode detection (`action_intents.py` can promote plain chat to agent mode) → trim/compact context (`context_compactor.py`, summarizes older turns at ~85% context) → stream with fallback → agent loop → persist.

**Memory & RAG** use ChromaDB for vectors (`src/memory_vector.py`, `src/chroma_client.py`, `src/embeddings.py`) plus JSON for the canonical store; retrieval is hybrid keyword+vector. The `services/memory/` layer adds LLM auto-extraction and periodic audit/consolidation (with a >50%-deletion safety net). Skills are disk-backed `SKILL.md` files (YAML frontmatter + markdown).

**Startup sequence** (`app.py` lifespan, via `src/app_initializer.py`): creates `data/` dirs, instantiates managers, then asynchronously warms the RAG index, pings/keepalives LLM endpoints, connects MCP servers, starts the in-process task scheduler, and runs null-owner + skill-ownership sweeps. MCP and warm-up are non-blocking so the server accepts requests quickly.

## Data & state

All runtime data lives in `data/` (gitignored): `app.db` (SQLite — sessions, messages, documents, email accounts, tokens, tasks, webhooks, crew), `chroma/` + `memory_vectors/` (vectors), and atomic JSON files (`auth.json`, `sessions.json`, `settings.json`, `memory.json`). Secrets in the DB (email passwords, signatures) are Fernet-encrypted via `EncryptedText` with the key at `data/.app_key`. Never read/modify these in tests against a real workspace.

## Conventions (from CONTRIBUTING.md)

- Keep PRs small and focused — one bug or feature each. Avoid broad rewrites, formatting-only churn, or mass file moves unless that *is* the task.
- Run the smallest relevant checks (`pytest`, `py_compile`, `node --check`) and state what you ran.
- Match surrounding style; the front-end deliberately has no framework or build step — keep new front-end code as plain ES6 modules.
- Bind manual dev runs to `127.0.0.1`; `0.0.0.0` only for intentional LAN/reverse-proxy use. Treat this as an admin console — auth, privileges, and owner-scoping are load-bearing.
