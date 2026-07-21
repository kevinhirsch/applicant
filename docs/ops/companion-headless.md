# Companion: Headless Internal Service

## Posture

The **companion** service (formerly the vendored workspace UI front door) is now a
**headless internal-only service** with **no public host port**.

- It is reachable in-network at `http://companion:7000`.
- The engine accesses it via the internal token-gated channel
  (`/api/applicant/internal/*`) authenticated with `APPLICANT_INTERNAL_TOKEN`.
- It provides lanes A–D (calendar, email inbox scan, deep research) exclusively
  to the engine.
- There is no public UI, web entry point, or published port.

## Single-operator posture

- The companion does not serve operator-facing UI.
- All operator interaction flows through the **a0** service (the public Agent
  Zero shell) which proxies to the engine at `http://api:8000`.
- The engine in turn calls the companion internally for lane-specific work.

## Security boundary

| Aspect              | Detail                                               |
|---------------------|------------------------------------------------------|
| Host ports          | None (no `ports:` mapping in docker-compose.prod.yml) |
| Network reachability | Internal Docker network only                          |
| Auth to engine      | `APPLICANT_INTERNAL_TOKEN` shared secret              |
| Engine wiring       | `WORKSPACE_URL=http://companion:7000`                |
| Mind backend        | `MIND_BACKEND=bridge`                                |

## Verification

Run the hermetic unit tests:

```shell
.venv/bin/pytest tests/unit/test_companion_headless_hardening.py -v
```

This validates:
- No host port is published for the companion service.
- The engine wiring (`MIND_BACKEND=bridge`, `WORKSPACE_URL=http://companion:7000`,
  `APPLICANT_INTERNAL_TOKEN`) is intact.
- The `a0` service remains the public entry point.
- The `api` (engine) is also internal-only.