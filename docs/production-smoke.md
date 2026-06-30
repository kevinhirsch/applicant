# Production deploy smoke + readiness checklist

The layer most likely to bite on first deploy is the part that **only runs under
`docker compose up --build` on a real Docker host** — the apt/Chrome/camoufox/
patchright/TeX/LibreOffice image layers, the update/rollback script, the
credential-key volume, and the bridge over the container network. CI validates
`docker compose config` but **does not build images**, so these are first
exercised at `compose up --build`. This doc is the post-deploy verification pass.

Run it after `scripts/install.sh --apply` (or `scripts/proxmox-deploy.sh`) and
after every `scripts/update.sh --apply`.

## 0. One-shot health gate

```bash
# Both must be green. install.sh / update.sh already block on this via heartbeat().
curl -fsS http://localhost:${APP_PORT:-8000}/api/health            # front-door UI
docker compose -f docker/docker-compose.prod.yml exec -T api \
  python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"
```

The engine `/healthz` reports per-capability status. **A capability that silently
degrades to a stub still returns 200** — so do not stop at the status code; read
the capability map (step 1).

## 1. Capabilities are REAL, not stubbed (the silent-degrade trap)

The engine detects external binaries via `shutil.which()` / lazy import and
**silently degrades (no real output) when absent**. Confirm the built image
actually has each one — a missing binary produces a fake preview / simulated
pre-fill, not an error.

```bash
docker compose -f docker/docker-compose.prod.yml exec -T api sh -lc '
  for b in xelatex lualatex soffice google-chrome Xvfb; do
    command -v "$b" >/dev/null 2>&1 && echo "ok   $b" || echo "MISS $b"; done
  uv run python -c "import camoufox; print(\"ok   camoufox import\")" || echo "MISS camoufox"
  uv run python -c "from patchright.sync_api import sync_playwright; print(\"ok   patchright.sync_api\")" || echo "MISS patchright"
'
```

Expected: every line `ok`. Notes:
- **`patchright.sync_api`** is the one most likely to be MISS on an old build:
  the PyPI name `patchright` has a non-importable `0.0.1` name-squatter stub. The
  `browser` extra pins `patchright>=1.48` (`pyproject.toml`) so the lock resolves
  the genuine 1.x fork; without it the `chromium` engine + Proxmox CDP backend
  fall back to vanilla Playwright (loses anti-detect) or fail to launch.
- **`camoufox`** is the DEFAULT engine — `camoufox fetch` runs at build time. The
  browser binary lives under `/app/.local/share` (anchored by `XDG_DATA_HOME`).
- **`patchright install chromium`** runs at build time under
  `PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright` so the bundled chromium
  revision matches the installed driver.
- **`Xvfb`** is required for camoufox to render headful inside the display-less
  container.

Then confirm a true render end-to-end (not an approximate preview): trigger a
resume render from the UI and confirm a real PDF is produced for both the LaTeX
(accept) and docx (reject) onboarding paths.

## 2. The bridge (container DNS + shared token)

Both containers must resolve each other by **service DNS** (not localhost) and
share the SAME `APPLICANT_INTERNAL_TOKEN`.

```bash
# Same token on both sides (install.sh mints it once into .env; compose passes it through).
docker compose -f docker/docker-compose.prod.yml exec -T api          printenv APPLICANT_INTERNAL_TOKEN
docker compose -f docker/docker-compose.prod.yml exec -T applicant-ui printenv APPLICANT_INTERNAL_TOKEN   # must match
# Service-DNS wiring (NOT localhost).
docker compose -f docker/docker-compose.prod.yml exec -T applicant-ui printenv ENGINE_URL    # http://api:8000
docker compose -f docker/docker-compose.prod.yml exec -T api          printenv WORKSPACE_URL  # http://applicant-ui:7000
```

An empty token disables the reverse channel on both sides (calendar/research/
local-models callbacks + the `bridge` MIND_BACKEND degrade gracefully). The UI
`depends_on: api: service_healthy`, so the public front door never serves before
the engine reports a real (DB-reachable) `/healthz`.

## 3. Credential master key survives a rebuild (data-loss landmine)

`CREDENTIAL_KEYFILE` defaults to `/data/secrets/master.key` on the **`secrets`
named volume**. If it ever lands on the ephemeral container layer, a
`up --build` regenerates it and **every sealed vault credential becomes
permanently undecryptable**.

```bash
# The key file lives on the named volume; capture its identity before an update…
docker compose -f docker/docker-compose.prod.yml exec -T api sh -lc \
  'ls -l /data/secrets/master.key && sha256sum /data/secrets/master.key'
# …rebuild, then confirm it is BYTE-IDENTICAL afterwards (NOT regenerated).
docker compose -f docker/docker-compose.prod.yml up -d --build api
docker compose -f docker/docker-compose.prod.yml exec -T api sh -lc 'sha256sum /data/secrets/master.key'
```

The two `sha256sum` values MUST match. The same persistence rule covers
`CHECKPOINT_DIR` (`checkpoints`), `FONTS_DIR` (`fonts`), and
`BROWSER_PROFILES_DIR` (`browser-profiles`) — all on named volumes.

## 4. Update / rollback (can a failed update brick the instance?)

`scripts/update.sh --apply` order: git-sync → snapshot (git rev + image IDs to
`:previous`) → **backup DB BEFORE migrate** → build changed images → migrate as a
blocking one-off (`run --rm`, does not serve) → restart → heartbeat. Safety
properties to verify on a staging instance:

- **Backup precedes migrate.** A failed/empty `pg_dump` aborts before migrate
  (`update.sh`). A migration failure **auto-restores** the dump just taken and
  refuses to bring up the new stack.
- **Rollback reverts code + images + DB together.** `--rollback --apply` resets
  the checkout to the snapshot commit, re-tags `applicant/{api,ui}:previous` →
  `:latest`, restores the newest dump, and redeploys. It **refuses a partial
  DB-only rollback** if the pre-update snapshot is missing.
- **Dry-run first.** `scripts/update.sh` (no `--apply`) prints every step.

```bash
scripts/update.sh                      # dry-run: read the plan
scripts/update.sh --apply              # perform; blocks on heartbeat, points at --rollback on failure
scripts/update.sh --rollback --apply   # revert code+images+DB to the pre-update snapshot
```

Backups rotate to the newest `BACKUP_KEEP_COUNT` (default 7) in
`${APPLICANT_BACKUP_DIR:-<repo>/.backups}` (git-ignored with a `*` drop-file).

## 5. Migrations (single head, forward integrity, downgrade story)

```bash
uv run alembic heads          # MUST print exactly one head
uv run alembic upgrade head   # idempotent; run by install.sh before the api serves
```

- Every revision (`0001`…current) ships a real `downgrade()`; the chain is
  linear (single head). There is no automated multi-step downgrade in deploy —
  rollback is DB-restore-from-dump (step 4), not `alembic downgrade`.
- The forward data-integrity guarantee (seeded rows survive `upgrade head`, and
  the upgraded schema matches the ORM with no drift) is covered hermetically by
  `tests/unit/test_migration_data_integrity_hermetic.py`. The Postgres variant
  `tests/unit/test_migration_data_integrity.py` is `@pytest.mark.integration`
  and **skips unless a real Postgres is reachable** — run it against the deployed
  DB to exercise the Postgres path:
  ```bash
  DATABASE_URL=postgresql+psycopg://applicant:...@localhost:5432/applicant \
    uv run pytest -q tests/unit/test_migration_data_integrity.py
  ```

## 6. Checks runnable WITHOUT a Docker daemon (pre-flight)

```bash
bash -n scripts/*.sh                                          # syntax
docker compose -f docker/docker-compose.prod.yml config       # compose validity (needs POSTGRES_PASSWORD set)
uv run alembic heads                                          # single head
uv run python -c "from applicant.app.main import app"         # boot smoke
uv run ruff check .
scripts/install.sh                                            # DRY-RUN by default — prints the plan
```
