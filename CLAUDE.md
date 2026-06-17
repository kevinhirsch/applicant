# CLAUDE.md — working mandate for Applicant (engine + front-door)

Applicant = the job-application **engine** (`src/applicant/`, hexagonal FastAPI, internal `api:8000`)
behind a white-labeled **front-door workspace UI** (`workspace/`, the public app on `${APP_PORT}`),
wired by the bridge (`workspace/src/applicant_engine.py` → engine; engine→workspace callback via
`workspace/routes/applicant_internal_routes.py`). The authority for behavior is
`docs/spec/master-spec.md` (FR-/NFR- requirements).

## Binding working principles (read before building anything)

1. **Lift and shift first — never rebuild what exists.** If logic or UI for something already
   exists anywhere in the tree, **copy that component into the new location first**, get it working
   there unchanged, and only **then adapt it by extension and removal** until it meets the spec for
   the new context. Do NOT write a fresh from-scratch implementation when a working one exists.
   (Example: the OOBE "Connect a model" step must reuse the existing Local/Remote endpoint manager
   — `workspace/static/js/admin.js` `initEndpointForm`/`loadEndpoints` over the workspace's own
   `/api/model-endpoints` in `workspace/routes/model_routes.py` — not a new form.)

2. **Reachability is the definition of done.** A requirement is not done because the engine
   implements it and tests pass — it is done when it is **reachable/operable in the white-labeled
   front-door**. Always verify the whole chain: spec → engine endpoint → workspace proxy
   (`workspace/routes/applicant_*`) → JS (`workspace/static/js/`) → nav/section
   (`workspace/src/applicant_features.py`). The traceability docs verify only the engine; do not
   trust them for reachability.

3. **White-label, always.** Zero references to any vendor/persona codename
   (`firehouse`/`orwell`/`odysseus`/`smokey`) and zero `FR-`/`NFR-` jargon in user-facing strings.
   The product is **Applicant**. Plain language + tooltips.

4. **Front-door proxies; the engine owns logic.** Workspace `/api/applicant/*` routes are thin
   auth-protected, owner-scoped proxies over the engine client; business logic lives in the engine.
   Reuse the engine's gates (e.g. `require_automated_work`) rather than re-implementing them.

5. **Green increments.** Before merge: `uv run pytest -q`, `uv run ruff check .`,
   `uv run python -c "from applicant.app.main import app"` boots, single Alembic head, and
   `docker compose -f docker/docker-compose.prod.yml config` validate. Keep PRs focused.

See `workspace/CLAUDE.md` for the vendored app's internals and `docs/spec/master-spec.md` for the
requirement set.
