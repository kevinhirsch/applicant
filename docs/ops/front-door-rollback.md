# Front-Door Retirement — Rollback Procedure

**Use when:** The `front-door-retirement` cutover (#857) causes a regression in the applicant pipeline that cannot be resolved by a hotfix.

## Preconditions for rollback

1. The rollback path has been exercised at least once **before** the cutover.
2. The previous workspace compose file (`workspace/docker-compose.yml` or the old base `docker/docker-compose.yml` with `api` on port 8000) is still intact.

## Rollback Steps

1. **Isolate the cutover**
   ```bash
   docker compose -f docker/docker-compose.prod.yml down a0 companion
   ```

2. **Re-expose the old front-door / engine**
   Restore the old topology. If the old setup used the base `docker-compose.yml` (api on port 8000):
   ```bash
   docker compose -f docker/docker-compose.yml up -d api postgres searxng
   ```
   If the old setup used a separate workspace compose:
   ```bash
   docker compose -f workspace/docker-compose.yml up -d applicant
   ```

3. **Verify re-exposure**
   ```bash
   ss -tlnp | grep ':8000'
   # Should show the old front-door or engine directly on 8000
   ```

4. **Run the standard deploy suite**
   ```bash
   cd /opt/applicant && .venv/bin/pytest tests/unit/ -v -k "not long_running"
   ```

5. **Update the deploy state**
   Pin the deploy script to the old compose file so `update.sh` does not roll forward again.

## Important Notes

- Rollback means the a0 service is no longer the public entry point.
- The companion service remains headless and internal; it was never public.
- Do not leave the rollback in place longer than necessary — a forward fix for the regression should be hotfixed and the cutover reattempted at the next ship-gate window.
