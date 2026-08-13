#!/usr/bin/env bash
# E3 recurring liveness auto-prune (deployed on 10.0.1.11 at /home/kevin/applicant-ops/,
# run by crontab: "17 */4 * * *"). Re-installs the liveness rule + pass into the
# engine container each run (so it survives a container recreate), then demotes any
# newly-DEAD candidate postings via the app ORM. Isolated from the engine scheduler
# so it can never break discovery. Log: /home/kevin/applicant-ops/liveness.log
#
# Durable home: the liveness rule (core/rules/liveness.py) + pass
# (docs/prototypes/liveness_pass.py) live in the repo; next image rebuild bakes them.
# Until then this wrapper hot-installs them from the persistent ops dir.
D=/home/kevin/applicant-ops
sudo -n docker cp "$D/liveness.py" docker-api-1:/app/src/applicant/core/rules/liveness.py 2>/dev/null
sudo -n docker cp "$D/liveness_pass.py" docker-api-1:/tmp/liveness_pass.py 2>/dev/null
echo "[$(date -u +%FT%TZ)] $(sudo -n docker exec -w /app docker-api-1 /app/.venv/bin/python /tmp/liveness_pass.py 0.5 150 2>&1 | grep 'liveness pass')"
