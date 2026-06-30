# Production deploy smoke check

The CI gate never builds or runs the container images — it validates `docker compose
config` but stops there (see `CLAUDE.md`). So the **engine image's baked-in binaries**
(TeX, LibreOffice, the anti-detect browser) and the **live multi-container bridge** are
first exercised only at `compose up --build`. Run this on the Docker host after a deploy
or image change. Anything that fails here is a real production gap; paste the failing
output back and it gets fixed.

> Host needs Docker + Docker Compose v2 (the only hard requirement). ~2 vCPU / 4 GB RAM
> to start. Everything after install is configured in-browser.

## 1. Validate compose + build the images

```bash
cd <repo>
docker compose -f docker/docker-compose.prod.yml config >/dev/null && echo "compose OK"
# Build + bring up the full prod stack (or: bash scripts/install.sh --apply, which also
# generates .env with the bridge token + runs migrations).
docker compose -f docker/docker-compose.prod.yml up --build -d
```

Watch the `api` image build for the layers CI never exercises: the apt install of
**LibreOffice** + **TeX** (`xelatex`/`lualatex` + moderncv/fontspec/fontawesome5) and the
**browser** extra (camoufox `fetch`, or patchright + a real Google Chrome). A failure in
those layers is the most likely deploy break.

## 2. All services healthy

```bash
docker compose -f docker/docker-compose.prod.yml ps
```

Expect `applicant-ui`, `api`, `postgres` (and `searxng`, `chromadb`, `ntfy`) **healthy**.
The public UI is on `${APP_PORT:-8000}` → container 7000; `api` is internal only.

```bash
curl -fsS "http://localhost:${APP_PORT:-8000}/api/health"      # front-door → {"status":"healthy"}
```

## 3. ★ Engine capabilities must all be REAL (the key check)

```bash
docker compose -f docker/docker-compose.prod.yml exec api \
  python -c "import urllib.request,json; print(json.dumps(json.load(urllib.request.urlopen('http://localhost:8000/healthz'))['checks'], indent=2))"
```

Every capability must be **ok / connected**, NOT degraded:

| check | required value | if wrong |
|---|---|---|
| `database` / `postgres` | `ok` / `connected` | DB env or `postgres` service |
| `libreoffice` | `ok (/usr/bin/soffice)` | docx résumé fallback is dead |
| `tex` | `ok` (NOT `NOT FOUND (using stub PDF)`) | LaTeX résumé render is a stub — résumés won't render |
| `browser` | `ok` / real (NOT `disabled … using in-memory fake`) | pre-fill is simulated — **nothing real submits** |

`tex: NOT FOUND` or `browser: disabled` means the Dockerfile didn't bake those binaries —
fix `docker/Dockerfile`, not the host.

## 4. Schema is migrated to a single head

```bash
docker compose -f docker/docker-compose.prod.yml exec api alembic heads    # exactly ONE head
docker compose -f docker/docker-compose.prod.yml exec api alembic current  # == the head
```

## 5. Bridge is wired both ways

```bash
grep -E 'APPLICANT_INTERNAL_TOKEN|ENGINE_URL|WORKSPACE_URL' .env   # token set (non-empty), URLs point at the services
docker compose -f docker/docker-compose.prod.yml logs api | grep -i "audit_log_started\|scheduler\|db_healthcheck"
```

`APPLICANT_INTERNAL_TOKEN` unset ⇒ the engine→workspace callback channel (calendar,
deep-research, local models) is disabled by design.

## 6. Operate the real flow once

1. Open `http://<host>:${APP_PORT:-8000}`, log in as the admin (`install.sh` prints the
   password; or `docker compose logs applicant-ui`).
2. OOBE: **Connect a model** (remote OpenAI-compatible key, e.g. OpenRouter, or a local
   Ollama) → confirm the Job Assistant returns a real model reply (not the canned
   fallback). **Your profile**: upload a résumé → confirm it parses + the LaTeX
   accept/reject gate renders (this exercises the TeX/LibreOffice path from §3).
3. Activity/Debug → **Download activity log** → confirm a non-empty JSON action trail.

## What "production-ready" then means

Green §1–§6 here + the CI gate (ruff, ~2,500 engine tests, front-door tests, single
Alembic head, `compose config`, node-check, white-label denylist) = the full stack is
verified end-to-end. The remaining live-only items (a real public-ATS pre-fill, the
takeover desktop) are exercised by operating an actual campaign.
