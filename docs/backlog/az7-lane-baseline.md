# AZ-7 Lane Parity Baseline

**Issue**: #850 (AZ4-2 lane regression) → #860-863 (AZ-7 MCP cutovers)  
**Integration verification**: #145  
**Status**: Buildable (skip-guarded tests + baseline doc; live-run gated on companion)

---

## Companion Internal-Token Channel

- Base URL: `WORKSPACE_URL` (default `http://applicant-ui:7000`)  
- Path prefix: `/api/applicant/internal`  
- Auth: `X-Applicant-Internal-Token` header (value from `APPLICANT_INTERNAL_TOKEN`)  
- Owner scope: `X-Applicant-Owner` header (optional, for multi-user attribution)  
- Channel disabled (available()=False) when token is unset

---

## Lane A — Calendar (Read + Write-back)

**Read endpoint**: `GET /calendar/interviews`

Request headers: X-Applicant-Internal-Token, X-Applicant-Owner (optional)

Response contract: 200 JSON dict with:
  - `events`: list of interview objects, each with at least id, title, start, end (or similar calendar event fields)
  - OR the workspace may return events wrapped in a container key

**Write endpoint**: `POST /calendar/events`

Request body:
  - `title` (str, required): event title
  - `start` (str, required): ISO 8601 timestamp
  - `all_day` (bool, default false)
  - `end` (str, optional): ISO 8601 timestamp
  - `notes` (str, optional): description/notes
  - `location` (str, optional): event location or URL
  - `dedupe_key` (str, optional): stable identifier for idempotent updates

Response contract (201):
  - `ok`: true
  - `uid`: string event identifier
  - `created`: boolean

**Parity definition**: The AZ-7 MCP calendar tools (issues #860-863) must match these same request/response shapes when calling through the MCP protocol instead of the internal HTTP channel. `dedupe_key` behavior must be identical (same key → update, not duplicate).

---

## Lane B — Research

**Endpoint**: `POST /research`

Request headers: X-Applicant-Internal-Token, X-Applicant-Owner (optional)

Request body:
  - `query` (str, required): research question
  - `company` (str, optional): company context
  - `role` (str, optional): role context
  - `context` (str, optional): additional context
  - `max_time` (int, optional): max research time in seconds

Response contract (200):
  - `query`: the input query (echoed)
  - `summary`: string report summary
  - `key_findings`: list of string findings
  - `sources`: list of `{"url": str, "title": str}` objects
  - `cached`: boolean (true if a cached result was returned)
  - `budget_remaining`: int (remaining research budget for this campaign)

**Parity definition**: AZ-7 MCP research tools must accept the same body fields and return the same response shape. Budget tracking (per-campaign cap) must be preserved.

---

## Lane C — Email / Inbox Scan

**Endpoint**: `GET /emails/recent?limit=N`

Request headers: X-Applicant-Internal-Token, X-Applicant-Owner (optional)

Query parameters:
  - `limit` (int, default 20): max messages to return

Response contract (200):
  - `emails`: list of email objects, newest first, each with:
    - `uid`: string unique identifier
    - `subject`: string subject line
    - `from`: string sender
    - `body`: string plain-text body
    - `date`: ISO 8601 timestamp

**Parity definition**: AZ-7 MCP inbox tools must expose the same fields and ordering. The scan_inbox_for_outcomes flow in PostSubmissionService depends on this exact shape for rejection/interview/offer detection.

---

## Running

```bash
# All lane regression tests (skip cleanly without companion)
.venv/bin/pytest tests/integration/test_lane_regression.py -v

# With companion running (set APPLICANT_INTERNAL_TOKEN + WORKSPACE_URL):
export APPLICANT_INTERNAL_TOKEN=...
.venv/bin/pytest tests/integration/test_lane_regression.py -v
```

Each test is `@pytest.mark.integration` and skips with `pytest.mark.skipif` when the companion is not reachable.
