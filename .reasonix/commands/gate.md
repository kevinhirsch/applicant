---
description: Run the full green-increment gate set (never trust a subagent's green)
---
Run the full green-increment gate set — never trust a subagent's "green."

Run every command below from the repo root and report PASS/FAIL for each. No `-k` subsets,
no skipping. Do not declare green unless all pass.

```bash
export DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none'
uv run pytest -q -m "not integration"
uv run ruff check .
uv run lint-imports
uv run alembic heads
uv run python -c "from applicant.app.main import app"
uv run pytest -q workspace/tests/test_applicant_*.py
python -m compileall -q workspace/app.py workspace/routes workspace/src
uv run pytest -q tests/architecture/test_reachability_contract.py
```

Then run `node --check` on every changed `workspace/static/js/*.js` file.

Notes:
- The `DATABASE_URL` above forces the hermetic in-memory lane; without it the BDD harness hangs.
- Boot smoke (`from applicant.app.main import app`) times out on Windows — known pre-existing DB
  issue; the reachability-contract test confirms the import is fine in ~0.3s.
