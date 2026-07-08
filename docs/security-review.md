# Security review (P2-3)

A launch-gate security pass over three surfaces: **secrets at rest**, the
**dependency audit**, and an **authenticated-endpoint sweep**. This page records
what was checked, what was found, how each finding was triaged, and where the
fix (or the deliberate deferral) lives. It is meant to be re-runnable — the
"How to re-run" commands reproduce the audit.

## Summary of findings

| # | Area | Severity | Finding | Disposition |
|---|------|----------|---------|-------------|
| 1 | Endpoint sweep | **High** (multi-account) | Results / Research / Gallery read proxies gated by `require_user`, not `require_engine_owner` — a second workspace account could read the owner's data on the single-tenant engine | **Fixed** — all three moved to `require_engine_owner`; regression test added |
| 2 | Deps (reachable) | **High** | `lxml` XXE / entity-expansion via a crafted `.docx` upload | **Fixed at the boundary** — résumé-ingest read path rejects any DTD-bearing part before python-docx parses it; the OOXML edit path already used a hardened no-entity parser. Robust on every lxml version |
| 3 | Deps (not wired) | High (upstream) | `langsmith` < 0.8.18 arbitrary file read via `TracingMiddleware` | **Not reachable** — `TracingMiddleware` is never instantiated; `langsmith` is an unused transitive dep of `langgraph`. Bump deferred to a coordinated lockfile refresh |
| 4 | Deps (low) | Low | `markdownify` < 0.14.1 memory-DoS on malformed `<h999…>` tags | **Deferred** — needs attacker-controlled job-board HTML; bump deferred to the same lockfile refresh (see note) |
| 5 | Secrets at rest | — | Audit | **Pass** — see below |

## 1. Authenticated-endpoint sweep

The engine is **single-tenant** (no owner concept in its data), so on the
white-labeled front door `require_user` (any authenticated account) is only IDOR
protection against foreign ids — it does **not** isolate one workspace account
from another's engine data. DISC-15/15b established `require_engine_owner`
(`workspace/src/auth_helpers.py`) — which passes the lone owner in single-user
mode and denies a second non-admin account — and applied it to the
pending/campaigns/tracker/activity proxies.

This sweep re-walked every `workspace/routes/applicant_*_routes.py` proxy and
found three engine-backed **read** surfaces still on `require_user` that surface
the owner's private data:

- **Results** (`applicant_results_routes.py`) — learning/outcomes funnel,
  per-source conversion, the learned role signature;
- **Research** (`applicant_research_routes.py`) — cached company-research reports
  + budget;
- **Gallery** (`applicant_gallery_routes.py`) — generated documents / collections.

All three now gate with `require_engine_owner`. Verified RED-on-revert:
reverting any one gate to `require_user` turns the corresponding
`*_second_account_denied` test red (200 + engine read reached) — see
`workspace/tests/test_applicant_crossuser_isolation_p2_3.py`.

Other proxies were confirmed correctly gated and left unchanged: `admin`
(`require_admin`), `memory` / `mind` (`require_privilege` + `require_user`),
`internal` (`APPLICANT_INTERNAL_TOKEN` loopback), and the remaining surfaces
that already carry `require_engine_owner`.

## 2–4. Dependency audit

`pip-audit` over the exported engine dependency set found four advisories in
three packages. The front-door `npm audit` was clean (0 vulnerabilities).

- **lxml (PYSEC-2026-87, XXE, High).** The one genuinely reachable path: a user
  uploads a résumé, and a poisoned `.docx` could carry a DTD that reads a local
  file or expands an entity bomb. **Fixed at the call sites, version-independently:**
  - *Read* (`adapters/resume_parser/resume_parser.py`): `_docx_has_dtd` scans
    every XML part's prolog and refuses any that declares `<!DOCTYPE`/`<!ENTITY`
    before python-docx (which uses an entity-resolving parser) ever opens it.
  - *Edit* (`adapters/resume_tailoring/docx_tailor.py`): already parses with
    `_SAFE_XML_PARSER` (`resolve_entities=False, no_network=True, huge_tree=False`).

  A version bump to lxml ≥ 6.1.0 remains desirable but is **not** what closes the
  hole here — the boundary guards hold regardless of the installed lxml.
- **langsmith (GHSA-f4xh-w4cj-qxq8, file read via `TracingMiddleware`, High
  upstream).** Not reachable: `TracingMiddleware` is never constructed, and
  `langsmith` is only present as a transitive dependency of `langgraph`
  (`uv tree --invert --package langsmith`). No engine code imports or mounts it.
- **markdownify (PYSEC-2026-1604, memory-DoS, Low).** Reachable only via
  `python-jobspy`'s HTML-to-markdown of job-board pages, and only with a crafted
  `<h9999999>` tag; CVSS 3.1.

**Why the two bumps are deferred, not applied here.** The lockfile was resolved
with the repo's pinned uv (CI `setup-uv` v5.4.2 / the Docker digest in
`docker/Dockerfile`). Re-locking with a *different* uv version re-resolves the
`webarena-verified` URL dependency (the `eval` extra) and churns ~760 lines,
dropping that subtree. A dependency refresh must therefore be done deliberately
with the pinned uv so the `eval` extra is preserved and the diff stays reviewable
— out of scope for this security fix, tracked for a lockfile-maintenance pass.
Neither deferred advisory is reachable-and-high in this deployment (langsmith
unwired; markdownify low).

## 5. Secrets at rest

- **Vault.** Operator secrets (LLM API keys, captcha keys, credentials) are
  routed through the encrypted credential store; tier configs persist a
  `*_ref` and resolve the plaintext only at use (`SetupService._resolve_secret`,
  `_store_secret`). App-door session/secret storage on the front door uses
  Fernet-encrypted columns (`workspace/core/database.py` `EncryptedText`).
- **Demo seed (ties to P1-0).** The `DEMO_MODE` seed writes **no** secret: its
  LLM fixture uses a local Ollama endpoint with an empty `api_key`
  (`dev_seed._DEMO_LLM`), so a demo can never leak a real key.
- **Model identity / tokens** never appear in seeded or generated artifacts.

## How to re-run

```bash
# Dependency audit (engine): export the locked deps, audit without network installs
uv export --format requirements-txt --no-hashes > /tmp/reqs.txt
uvx pip-audit -r /tmp/reqs.txt --no-deps
cd workspace && npm audit            # front-door JS deps

# Endpoint-isolation regression
uv run pytest -q workspace/tests/test_applicant_crossuser_isolation_p2_3.py

# The .docx XXE guard
DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
  uv run pytest -q tests/unit/test_resume_parser_xxe_guard.py
```
