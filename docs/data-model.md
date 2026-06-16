# Data Model

Source: master spec §8 (Postgres + JSONB; DBOS state co-resides). All tables are **campaign-scoped from day one** (FR-CRIT-4): MVP-1 runs one active campaign, but every row hangs off (or is reachable from) `campaigns` so multi-campaign — including cloning a campaign's setup — drops in without rework (multi-ready design, §2 "Campaign-scoped, multi-ready"). DBOS workflow/step state lives in the **same Postgres** (FR-DUR-3), so durable execution requires no extra datastore.

ORM/migrations: SQLAlchemy + Alembic (§5). Secrets are stored via a key-file-encrypted store, never in plaintext columns (FR-VAULT-3).

The §8 highlights enumerate **19 tables**. Each is listed below with its key columns and JSONB fields.

| # | Table | Key columns | JSONB fields | Scoping / notes |
|---|---|---|---|---|
| 1 | **campaigns** | id, run_mode, throughput_target, exploration_budget | criteria, schedule, learning_state | The scope root. One active in MVP-1; schema multi-ready. FR-CRIT-1/4, FR-LEARN, FR-AGENT-1/2. |
| 2 | **onboarding_profiles** | campaign_id, completion_flag (gate) | resumable wizard state, full Workday-ready intake | Per campaign; completion gates automated work. FR-ONBOARD-1/2. |
| 3 | **attributes** | id, campaign_id, name, value, is_integral, is_sensitive | aliases | Per-campaign attribute→value cloud; `is_sensitive` enforces EEO policy (FR-ATTR-6); `is_integral` drives confirmation gate (FR-FB-3). FR-ATTR-1/3/4. |
| 4 | **field_mappings** | id, campaign_id (nullable for global), attribute_id, site/tenant key, field selector | mapping metadata | Per-site field bindings; ATS field-mapping knowledge MAY be learned globally while values stay per-campaign. FR-ATTR-2, FR-PREFILL-3. |
| 5 | **fonts** | id, name, install_status, environment | font metadata | Uploaded font assets + install status, per environment. FR-FONT-1/2. |
| 6 | **discovery_sources** | id, campaign_id, source_key, enabled | yield_stats (decayed) | Source toggles + decayed yield stats for source-yield learning. FR-DISC-2/5, FR-LEARN-6. |
| 7 | **job_postings** | id, campaign_id, title, company, location, work_mode, salary, source_url, viability_score | normalized fields, rationale | Normalized postings + viability score & rationale. FR-DISC-3, FR-AGENT-3, FR-DIG-4. |
| 8 | **resume_variants** | id, campaign_id, storage_path (docx), parent_id (lineage), targeted_jd_signature, approved | fit_scores | Lineage tracked; approved = reusable parent; cluster/cap to prevent sprawl. FR-RESUME-6/7. |
| 9 | **generated_materials** | id, campaign_id, application_id, type (resume/cover_letter/screening_answer), content/storage_path, approved | redline state | Per-application generated artifacts with approval state. FR-RESUME-1/10, FR-ANSWER-1. |
| 10 | **revision_sessions** | id, material_id, status | redline state, turns (add/subtract/free-text + AI response) | Interactive revision loop history. FR-RESUME-8. |
| 11 | **applications** | id, campaign_id, posting_id, role_name, job_title, work_mode, root_url, resume_variant_id, status (§7), sandbox_session_url, timestamps | attributes_used | The durable application record; status is the §7 state machine. FR-LOG-1, FR-DUR-1, FR-SANDBOX. |
| 12 | **application_screenshots** | id, application_id, page ref, captured_at | — | Per-page screenshots of each pre-filled page. FR-LOG-2. |
| 13 | **decisions** | id, application_id, type (approve/decline), feedback_text | criteria_delta | Digest decisions + decline feedback + criteria delta. FR-DIG-3/5, FR-FB-1. |
| 14 | **outcome_events** | id, application_id, type, source (auto/manual) | — | Submission/conversion events; source distinguishes auto-detect vs mark-submitted. FR-LOG-4, FR-LEARN-2. |
| 15 | **agent_runs** | id, campaign_id, timestamp | intent_sentence | One-sentence "what I intend to do next" per run. FR-AGENT-7. |
| 16 | **detection_events** | id, application_id, signal type, timestamp | signal detail | Automation-detection signals driving cautious mode. FR-PREFILL-6, FR-STEALTH. |
| 17 | **tool_settings** | id, tool_key, enabled | — | Per-tool on/off registry. FR-UI-4. |
| 18 | **dormant_surface_backlog** | id, surface name, requirement IDs, status | wiring notes | One row per grayed-out surface stub. FR-UI-2. |
| 19 | **app_config** | id, key | provider/model/channels config; secrets via key-file-encrypted store | Global config (LLM provider/model, channels). Secrets encrypted, never logged. FR-LLM-2, FR-NOTIF-1, FR-VAULT-3. |

## Derived / materialized

- **pending_actions** (derived/materialized) — every item awaiting user input (digest approvals, document/cover-letter/screening-answer reviews, soft errors, agent questions, final-submit approvals), materialized for the pending-actions portal. FR-UI-3. *(Listed separately in §8 as derived; not one of the 19 base tables.)*

## Credential storage

Per-site/tenant credentials are sealed with libsodium in the encrypted-Postgres `CredentialStorePort` adapter (FR-VAULT-1), structured for many credential sets (Workday is per-tenant). The master key is a strict-permission key-file on disk (FR-VAULT-3). This adapter's physical schema is an adapter concern (Vaultwarden is a later alternative) and is not one of the §8 highlight tables.

## Campaign-scoping & multi-ready summary

Every domain table carries (directly or transitively) a `campaign_id`. The attribute cloud, base resume + variants, credentials, and learning state are all per-campaign (FR-CRIT-4). Cross-campaign sharing is allowed only where the spec permits it: **ATS field-mapping knowledge** (`field_mappings`) MAY be learned globally, but the underlying attribute *values* remain per-campaign. This shape makes adding a second campaign — or cloning an existing campaign's setup — a data operation, not a schema migration.
