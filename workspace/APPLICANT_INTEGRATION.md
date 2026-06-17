# Applicant Integration Contract (Stage 2 foundation)

This document is the **shared contract** for wiring the front-door workspace UI
to the Applicant **engine**. Stage 2 happens in **four parallel lanes** (A–D).
This file defines:

1. the engine HTTP client every lane uses (`src/applicant_engine.py`),
2. the feature-activation layer (`src/applicant_features.py` + `/api/applicant/features`),
3. the **endpoint mapping** each lane implements, and
4. the **file-ownership map** so the four agents work on **disjoint** files.

> Two FastAPI apps:
> - **front-door UI** = this workspace app (public, container port 7000). The owner's own app.
> - **engine** = the job-application engine (`src/applicant/`), internal at `http://api:8000`.

---

## 1. Engine client — `src/applicant_engine.py`

`httpx`-only (no new deps), matching the httpx style already in `src/`
(`integrations.py`, `embeddings.py`). Reads **`ENGINE_URL`** (default
`http://api:8000`, wired in `docker/docker-compose.prod.yml`). All failures —
timeouts, connection errors, HTTP 4xx/5xx — surface as the typed
**`EngineError`** so a wired UI surface degrades gracefully instead of 500ing.
The client **never** lets a raw httpx exception escape.

### Surface

Module-level:

| Symbol | Purpose |
|---|---|
| `DEFAULT_ENGINE_URL` | `"http://api:8000"` |
| `engine_base_url() -> str` | resolve `ENGINE_URL` (trailing slash stripped) |
| `class EngineError(Exception)` | `.message`, `.status` (int or None), `.detail`, `.is_timeout` |
| `class ApplicantEngineClient` | async client (below) |
| `engine_available_sync(base_url=None, transport=None) -> bool` | sync `/healthz` ping; never raises |
| `get_sync(path, base_url=None, params=None, transport=None) -> Any` | sync GET → JSON, or raises `EngineError` |

`ApplicantEngineClient` (async; use `async with`, or hold one and call `aclose()`):

| Method | Engine endpoint |
|---|---|
| `engine_available()` | `GET /healthz` → bool (never raises) |
| `healthz()` | `GET /healthz` |
| `setup_status()` | `GET /api/setup/status` |
| `dormant_surfaces()` | `GET /api/dormant-surfaces` |
| `list_campaigns()` / `create_campaign(name)` | `GET` / `POST /api/campaigns` |
| `list_documents()` | `GET /api/documents` |
| `documents_for_application(application_id)` | `GET /api/documents/applications/{id}` |
| `review_document(document_id)` | `POST /api/documents/{id}/review` |
| `turn_document(document_id, body)` | `POST /api/documents/{id}/turn` |
| `approve_document(document_id)` | `POST /api/documents/{id}/approve` |
| `decline_document(document_id)` | `POST /api/documents/{id}/decline` |
| `approve_variant(variant_id)` | `POST /api/documents/variants/{id}/approve` |
| `set_document_aggressiveness(value)` | `POST /api/documents/aggressiveness` |
| `onboarding_state(campaign_id)` | `GET /api/onboarding/{id}` |
| `onboarding_section(campaign_id, body)` | `POST /api/onboarding/{id}/section` |
| `onboarding_complete(campaign_id)` | `POST /api/onboarding/{id}/complete` |
| `list_attributes(campaign_id)` | `GET /api/attributes/{id}` |
| `add_attribute(body)` | `POST /api/attributes` |
| `ai_add_attribute(body)` | `POST /api/attributes/ai-add` |
| `bind_attribute(body)` | `POST /api/attributes/bindings` |
| `acquire_missing_attribute(body)` | `POST /api/attributes/acquire-missing` |
| `conversion_engine(campaign_id)` | `GET /api/conversion/{id}/engine` |
| `conversion_preview(campaign_id, source)` | `POST /api/conversion/{id}/preview` |
| `conversion_accept(campaign_id)` | `POST /api/conversion/{id}/accept` |
| `conversion_reject(campaign_id)` | `POST /api/conversion/{id}/reject` |
| `chat(body)` | `POST /api/chat` |
| `chat_confirm(body)` | `POST /api/chat/confirm` |
| `list_pending_actions(campaign_id)` | `GET /api/pending-actions/{id}` |
| `resolve_pending_action(action_id)` | `POST /api/pending-actions/{id}/resolve` |
| `digest(campaign_id)` | `GET /api/digest/{id}` |
| `digest_email(campaign_id)` | `GET /api/digest/{id}/email` |
| `deliver_digest(campaign_id)` | `POST /api/digest/{id}/deliver` |
| `approve_digest_application(application_id)` | `POST /api/digest/applications/{id}/approve` |
| `decline_digest_application(application_id, body=None)` | `POST /api/digest/applications/{id}/decline` |
| `feedback_freetext(body)` | `POST /api/feedback/freetext` |
| `feedback_survey(body)` | `POST /api/feedback/survey` |

> **Adding methods:** keep them small and 1:1 with an engine endpoint, returning
> decoded JSON (or `None` for the engine's `204` writes). Mock the transport in
> tests (`httpx.MockTransport`) — see `tests/test_applicant_engine.py`. **Lanes
> add only the methods their endpoints need; do not refactor existing ones.**

### Engine endpoint reference (full paths, by router)

Confirmed from `src/applicant/app/routers/*.py`. Top-level request-body field
names shown for `POST`/`PUT`.

**documents** (`/api/documents`): `GET /` · `GET /applications/{application_id}`
· `POST /redline` {variant_id, base_source, new_source, aggressiveness} ·
`POST /cover-letter` {campaign_id, application_id, true_source, jd_terms,
campaign_default, role_requires} · `POST /screening-answer` {campaign_id,
application_id, question, true_source, essay, explicit_answer} ·
`POST /deferred-essay` {campaign_id, application_id, true_source, label,
question, selector, url, explicit_answer} · `POST /aggressiveness`
{aggressiveness} · `POST /{document_id}/review` · `POST /{document_id}/turn`
{kind, instruction, true_source} · `POST /{document_id}/approve` ·
`POST /variants/{variant_id}/approve` · `POST /{document_id}/decline` ·
`POST /applications/{application_id}/ensure-submittable`

**onboarding** (`/api/onboarding`): `GET /{campaign_id}` ·
`POST /{campaign_id}/section` {section, data} · `POST /{campaign_id}/complete` ·
`POST /{campaign_id}/base-resume` (file upload) ·
`POST /{campaign_id}/confirm-conflict` {attribute, value}

**attributes** (`/api/attributes`): `GET /` · `GET /{campaign_id}` ·
`POST /` {campaign_id, name, value, aliases, is_integral, is_sensitive, confirm,
ai_suggested} · `POST /ai-add` {campaign_id, name, value, confirm} ·
`POST /bindings` {site_key, field_selector, attribute_id, campaign_id, shared,
metadata} · `POST /acquire-missing` {campaign_id, name, value, confirm}

**conversion** (`/api/conversion`): `GET /{campaign_id}/engine` ·
`POST /{campaign_id}/preview` {source} · `POST /{campaign_id}/accept` ·
`POST /{campaign_id}/reject`

**criteria** (`/api/criteria`): `GET /{campaign_id}` · `PUT /{campaign_id}`
{titles, locations, work_modes, keywords, salary_floor, human_readable, confirm,
clear_learned} · `POST /{campaign_id}/learned` {adjustment, rationale}

**chat** (`/api/chat`): `GET /` · `POST /` {campaign_id, message} ·
`POST /confirm` {campaign_id, name, value}

**pending_actions** (`/api/pending-actions`): `GET /` · `GET /{campaign_id}` ·
`POST /{action_id}/resolve`

**campaigns** (`/api/campaigns`): `GET /` · `POST /` {name}

**remote** (`/api/remote`): `GET /` · `POST /sessions` {application_id} ·
`GET /sessions/{session_id}/view-url` · `POST /sessions/{session_id}/takeover` ·
`POST /applications/{application_id}/request-final-approval` ·
`POST /applications/{application_id}/resume-account-step` ·
`POST /applications/{application_id}/resume-detection-step` ·
`POST /applications/{application_id}/submit-self` ·
`POST /applications/{application_id}/authorize-engine-finish`

**digest** (`/api/digest`): `GET /` · `GET /{campaign_id}` ·
`POST /{campaign_id}/deliver` · `GET /{campaign_id}/email` · `POST /presence`
{present} · `POST /applications/{application_id}/approve` ·
`POST /applications/{application_id}/decline` {feedback_text, criteria_delta}

**feedback** (`/api/feedback`): `GET /` · `POST /freetext` {campaign_id, text,
criteria_delta} · `POST /survey` {campaign_id, answers}

**setup** (`/api/setup`): `GET /status` · `POST /llm` · `POST /llm/from-endpoint`
· `GET`/`PUT /llm/tiers` · `GET`/`POST /channels` · `POST /channels/test` ·
`POST /advance/{step}`

**ui** (no prefix): `GET /api/dormant-surfaces`

---

## 2. Feature activation — `src/applicant_features.py` + `/api/applicant/features`

The workspace's own `/api/auth/features` (in `routes/auth_routes.py`,
`src/settings.py`, `data/features.json`) is a coarse admin on/off mechanism for
the owner's app features. It is **left untouched**.

This layer is **separate and derived**. `compute_features()` reads the engine's
`GET /api/setup/status` + `GET /api/dormant-surfaces` and computes a per-section
**state**:

| State | Meaning |
|---|---|
| `active` | engine reachable **and** the section's backing is configured/live |
| `configured` | backing configured but engine currently unreachable (transient) |
| `locked` | backing not yet configured (e.g. onboarding incomplete) — greyed |
| `disabled` | **present-but-disabled** by product decision (no Applicant backing) |

`GET /api/applicant/features` (added in `routes/applicant_routes.py`, mounted in
`app.py`, and **auth-exempt** like `/api/auth/features`) returns:

```json
{
  "engine_available": true,
  "engine_url": "http://api:8000",
  "sections": {
    "<key>": {
      "key": "...", "title": "...", "lane": "A|B|C|D|null",
      "state": "active|configured|locked|disabled",
      "nav_ids": ["rail-...", "tool-...-btn"],
      "requirement": "<setup-status predicate or null>",
      "present_but_disabled": false
    }
  }
}
```

The section map (`APPLICANT_SECTIONS`):

| key | lane | requires (setup-status field) | engine dormant keys | nav_ids |
|---|---|---|---|---|
| `documents` | A | `onboarding_complete` | `redline_surface` | `rail-documents`, `tool-library-btn`, `overflow-doc-btn` |
| `memory` | B | `onboarding_complete` | `attribute_editor`, `criteria_editor` | `rail-memory`, `tool-memory-btn` |
| `chat` | C | `llm_configured` | `chatbot` | `tool-assistant-btn`, `rail-assistant` |
| `email` | D | `channels_configured` | `digest_in_app` | `rail-email`, `tool-email-btn` |
| `compare` | — | — | — | `rail-compare`, `tool-compare-btn` |

**Compare ships present-but-DISABLED**: `present_but_disabled: true` → always
reported `disabled` (visible, greyed, never wired to the engine). Sections with
no Applicant backing stay locked until configured.

### Frontend wiring (already in place)

`static/app.js` fetches `/api/applicant/features` on boot (next to the existing
`/api/auth/features` block) and, for any section **not** `active`, adds the
`.applicant-locked` class (in `static/style.css`: dimmed +
`pointer-events:none`), sets `aria-disabled`, retitles the launcher with the
unlock reason, and installs a **capture-phase click guard** so an unwired
surface can't fire its handler. `active` sections are restored to normal. **User
management / auth is untouched.**

> **Lane note:** when your lane's engine wiring lands, the corresponding engine
> dormant surface(s) flip to `live` and the setup gate opens, so your section
> auto-activates with no frontend change. If you need a new section, add an entry
> to `APPLICANT_SECTIONS` (do not edit other lanes' entries).

---

## 3. Lane → endpoint mapping & file ownership

Each lane owns a **disjoint** set of files. Shared foundation files
(`src/applicant_engine.py`, `src/applicant_features.py`,
`routes/applicant_routes.py`, `app.py`, `static/app.js`) are **append-only** for
lanes: add your methods/sections/registrations; **do not rewrite** another lane's
additions. Prefer creating a **new** route file per lane and registering it in
`app.py` with a one-line `include_router(...)`.

### Lane A — Documents ↔ resume/cover-letter library

- **Engine:** `documents` (+ `onboarding` for intake/base-resume).
- **Engine client methods:** `list_documents`, `documents_for_application`,
  `review_document`, `turn_document`, `approve_document`, `decline_document`,
  `approve_variant`, `set_document_aggressiveness`, `onboarding_state`,
  `onboarding_section`, `onboarding_complete` (+ add `redline`, `cover-letter`,
  `screening-answer`, `deferred-essay`, `ensure-submittable`, `base-resume`,
  `confirm-conflict` as needed).
- **Owns (workspace files):**
  - `routes/applicant_documents_routes.py` *(new — engine-backed document/onboarding proxy)*
  - `static/js/documentLibrary.js`, `static/js/document.js`
  - `routes/document_routes.py`, `routes/document_helpers.py` *(only if extending; coordinate)*
- **Section:** `documents` (`redline_surface`; gate `onboarding_complete`).

### Lane B — Memory/Skills ↔ attributes + learning

- **Engine:** `attributes`, `conversion` (learning); `criteria` adjacent.
- **Engine client methods:** `list_attributes`, `add_attribute`,
  `ai_add_attribute`, `bind_attribute`, `acquire_missing_attribute`,
  `conversion_engine`, `conversion_preview`, `conversion_accept`,
  `conversion_reject` (+ `criteria` getters/setters as needed).
- **Owns (workspace files):**
  - `routes/applicant_memory_routes.py` *(new — engine attributes/learning proxy)*
  - `static/js/memory.js`, `static/js/skills.js`, `static/js/entities.js`
  - `routes/memory_routes.py`, `routes/skills_routes.py` *(only if extending; coordinate)*
- **Section:** `memory` (`attribute_editor`, `criteria_editor`; gate `onboarding_complete`).

### Lane C — Chat/Agent ↔ assistant + job-actions

- **Engine:** `chat`, `pending-actions`, `campaigns`, `remote`.
- **Engine client methods:** `chat`, `chat_confirm`, `list_pending_actions`,
  `resolve_pending_action`, `list_campaigns`, `create_campaign` (+ `remote`
  session/takeover/approval methods as needed).
- **Owns (workspace files):**
  - `routes/applicant_chat_routes.py` *(new — engine chat/pending-actions/campaigns/remote proxy)*
  - `static/js/assistant.js`, `static/js/chat.js` *(coordinate any shared chat
    renderer changes with the team — prefer additive)*
  - `routes/assistant_routes.py`, `routes/chat_routes.py` *(only if extending; coordinate)*
- **Section:** `chat` (`chatbot`; gate `llm_configured`).

### Lane D — Email ↔ notifications/digests

- **Engine:** `digest`, notifications, `feedback`.
- **Engine client methods:** `digest`, `digest_email`, `deliver_digest`,
  `approve_digest_application`, `decline_digest_application`,
  `feedback_freetext`, `feedback_survey`.
- **Owns (workspace files):**
  - `routes/applicant_email_routes.py` *(new — engine digest/feedback proxy)*
  - `static/js/emailInbox.js`, `static/js/emailLibrary.js`, `static/js/emailLibrary/*`
  - `routes/email_routes.py`, `routes/email_helpers.py`, `routes/email_pollers.py` *(only if extending; coordinate)*
- **Section:** `email` (`digest_in_app`; gate `channels_configured`).

### Disjointness summary

| Lane | New route file (owned) | Primary JS (owned) | Engine routers |
|---|---|---|---|
| A | `routes/applicant_documents_routes.py` | `documentLibrary.js`, `document.js` | documents, onboarding |
| B | `routes/applicant_memory_routes.py` | `memory.js`, `skills.js`, `entities.js` | attributes, conversion, criteria |
| C | `routes/applicant_chat_routes.py` | `assistant.js`, `chat.js` | chat, pending-actions, campaigns, remote |
| D | `routes/applicant_email_routes.py` | `emailInbox.js`, `emailLibrary.js` | digest, feedback |

**Shared, append-only (coordinate, never rewrite):**
`src/applicant_engine.py` · `src/applicant_features.py` ·
`routes/applicant_routes.py` · `app.py` (router registration block) ·
`static/app.js` (feature block) · `static/style.css` · this file.

---

## 4. Constraints carried into every lane

- Reuse what exists; don't rebuild. Don't break first-run login/setup or the
  native settings/model-config.
- httpx only on the engine path — **no new heavy deps**.
- Hermetic tests for anything new (mock the engine transport).
- **Keep user management fully intact.**
- **Zero** references to prior internal codenames in anything added.
