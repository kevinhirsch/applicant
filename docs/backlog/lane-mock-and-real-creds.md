# Lane Mock Backend & Real Credentials

## Overview

The workspace lane (email + calendar data channels) is backed by a
``WorkspacePort`` protocol. Two implementations exist:

1. **``HttpWorkspaceClient``** (default) — speaks HTTP to the companion workspace
   app over ``WORKSPACE_URL``, authenticated via ``APPLICANT_INTERNAL_TOKEN``.
2. **``MockWorkspaceClient``** — pure fixture data in memory; no network.

Toggle with ``WORKSPACE_BACKEND=mock`` at deploy/test time — see
`src/applicant/app/container.py` for the wiring.

## How the mock backend works

**Location:** `src/applicant/adapters/workspace/mock_workspace_client.py`

**What it serves:**
- **Emails** (`recent_emails`): Four deterministic fixture messages covering
  each outcome classifier:
  - `email-001-rejection`: Acme Corp — clear rejection ("regret to inform",
    "other candidates", "not been selected")
  - `email-002-interview`: Globex Inc — interview invite ("schedule an
    interview", "phone screen")
  - `email-003-offer`: Initech — job offer ("pleased to offer", "extend this
    offer", "welcome to the team")
  - `email-004-no-match`: Neutral newsletter — no outcome keywords
- **Calendar read** (`calendar_interviews`): One pre-seeded interview event
  ("Phone screen — Acme Corp")
- **Calendar write-back** (`create_calendar_event`): Stores events in memory
  with deduplication via ``dedupe_key`` — a second call with the same key
  updates the stored entry rather than appending.

**Transparency counters:**
- ``written_events`` — every event written via ``create_calendar_event``
- ``ping_count`` — how many ``ping()`` calls were made
- ``calendar_read_count`` — how many ``calendar_interviews()`` reads were made

## Swapping in real credentials

The same lane logic in `PostSubmissionService` works unchanged with either
backend. To swap to real credentials:

### 1. Set the config toggle

```env
# Use the real HTTP backend (the default — no action needed)
WORKSPACE_BACKEND=real
# or simply unset/omit it
```

### 2. Configure the workspace URL + auth token

```env
# Where the companion workspace app is reachable
WORKSPACE_URL=http://applicant-ui:7000
# Shared secret for the internal callback channel
APPLICANT_INTERNAL_TOKEN=<token>
```

### 3. The workspace app handles the real IMAP/CalDAV connections

The companion workspace (`applicant-ui`) owns the real credential storage and
mailbox/calendar connections. The engine never touches IMAP or CalDAV directly.
The workspace must be configured with:

| Service | Protocol | Settings |
|---------|----------|---------|
| Email (Gmail) | IMAP | ``imap.gmail.com:993`` with an **App Password** (not the regular Google password). Generate one at https://myaccount.google.com/apppasswords. Username is the full Gmail address. |
| Email (Gmail, sending) | SMTP | ``smtp.gmail.com:587`` (STARTTLS) with the same App Password. |
| Calendar (Google) | CalDAV or Google Calendar API (OAuth) | For CalDAV: ``https://apidata.googleusercontent.com/caldav/v2/`` — requires OAuth 2.0 credentials (client ID + secret) and a refresh token. For the simpler personal path: a Google Cloud project with the Calendar API enabled, OAuth consent configured, and a refresh token minted once. |
| Other IMAP providers | IMAP | Use the provider's IMAP/SMTP host:port. Most use port 993 (IMAPS) and port 587 (SMTP STARTTLS). |
| Other CalDAV providers | CalDAV | Use the provider's CalDAV endpoint URL. |

## Testing

With ``WORKSPACE_BACKEND=mock`` (or by injecting ``MockWorkspaceClient``
directly in unit tests):

```shell
# Unit tests that run the full lane logic against the mock backend
cd /a0/usr/projects/applicant
PYTHONPATH=src .venv/bin/pytest tests/unit/test_lane_mock_backend.py -v
```

These are fully hermetic — no network, no credentials, no skip guard.

**When real creds are configured**, the same ``PostSubmissionService`` methods
run against the real ``HttpWorkspaceClient`` and the companion workspace's live
mailbox/calendar. The integration test file `tests/integration/test_lane_regression.py`
covers that path (skipped when no companion is reachable).

## The seam

The swap is possible because both backends implement the same
``WorkspacePort`` protocol at `src/applicant/ports/driven/workspace.py`:

```python
@runtime_checkable
class WorkspacePort(Protocol):
    def available(self) -> bool: ...
    def ping(self, *, owner: str | None = None) -> dict: ...
    def calendar_interviews(self, *, owner: str | None = None) -> dict: ...
    def create_calendar_event(self, *, title, start, owner=None, end=None,
                               notes=None, location=None, all_day=False,
                               dedupe_key=None) -> dict: ...
    def recent_emails(self, *, owner: str | None = None, limit: int = 20) -> dict: ...
```

Any other implementation of this protocol (e.g. a real Gmail IMAP adapter or
Google Calendar API adapter) can be dropped in at the same seam with zero
changes to the lane logic.
