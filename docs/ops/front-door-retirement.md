# Front-Door Retirement — Cutover Runbook (`front-door-retirement.md`)

**Issue:** #857 (AZ6-4)
**Owner:** Ops / Ship Gate
**Status:** Cutover is GATED on AZ6-1/AZ6-2 green + AZ6-6 (migration) done.

## Topology (Target State)

```
Public (Port 8000)  ──>  a0 (Agent Zero UI shell)
                           │
                           ▼ (internal http://api:8000)
Engine (api)          ◄────┼─ Internal, no host port
                           │
                           ▼ (internal http://companion:7000)
Companion             ◄────┘─ Headless, no host port
```

## Preconditions (must all be true before executing)

1. [ ] **AZ6-1 / AZ6-2** — Ship gate green (integration acceptance).
2. [ ] **AZ6-6** — Migration complete at the engine layer.

## Cutover Steps

1. **Verify current state**
   ```bash
   cd /opt/applicant
   docker compose ps
   ```
   Confirm the old `applicant` service (workspace UI) is NOT binding the host port 8000.

2. **Pull latest compose file**
   Ensure `docker/docker-compose.prod.yml` reflects the AZ-0 topology:
   - `a0` exposes host port `8000` → container `80`.
   - `companion` has **no** `ports:` block.
   - `api` has **no** `ports:` block.

3. **Stop the old front-door (if running separately)**
   ```bash
   docker compose -f workspace/docker-compose.yml down applicant
   ```

4. **Bring up the AZ-0 stack**
   ```bash
   docker compose -f docker/docker-compose.prod.yml up -d --remove-orphans
   ```

5. **Verify exposure**
   ```bash
   ss -tlnp | grep ':8000'
   ss -tlnp | grep ':7000'
   ```

## Post-Cutover Smoke Checklist

1. **Golden path — a0 reachable**: `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000` (Expected 200)
2. **Engine reachable from a0**: `docker compose exec a0 curl -s http://api:8000/healthz`
3. **Companion lanes functional**: `docker compose exec api curl -s http://companion:7000/api/health`
4. **Lane tests pass**: `.venv/bin/pytest tests/unit/test_lane_regression.py -v`
5. **Rollback is exercised**: Rollback procedure (`front-door-rollback.md`) exercised in staging before cutover.

## Verification Gate

The readiness gate `test_front_door_retirement_readiness.py` passes on the target deployment before any manual step.
