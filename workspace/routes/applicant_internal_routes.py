# routes/applicant_internal_routes.py
"""Stage 2.5 ENGINE -> WORKSPACE callback channel.

Today the Applicant bridge is one-directional: the front-door **workspace UI**
calls *into* the **engine** (``src/applicant_engine.py``, ``ENGINE_URL``). Stage
2.5 needs the *reverse* direction — the engine (the internal ``api`` container)
must be able to call BACK into the workspace ``applicant-ui`` app to read things
that only the front-door app knows: auto-detected interview calendar events
(lane A), deep-research runs (lane B), and Cookbook-served local models (lane C).

This module is the **shared channel + contract** for that reverse direction.
Three later lanes fill in the typed endpoints; this file only provides the
namespaced router (mounted at ``/api/applicant/internal/*``) plus a working
``ping`` and documented placeholders so the contract is concrete.

## Trust model (READ BEFORE EXTENDING)

The boundary is a **shared secret**, not the network alone. Unlike the existing
in-process loopback internal-tool path (``core.middleware.INTERNAL_TOOL_*`` in
``app.py``'s ``AuthMiddleware``), the engine calls the workspace from a *sibling
container on the private docker network*, so it is NOT loopback. This prefix is
therefore honored ONLY when:

1. ``APPLICANT_INTERNAL_TOKEN`` is configured (a strong secret shared by both
   containers via ``docker-compose.prod.yml`` + ``scripts/install.sh``). If it
   is unset, the entire prefix is DISABLED (every call -> 403). No token, no
   channel — there is no "open by default" fallback.
2. The request carries ``X-Applicant-Internal-Token`` matching that secret,
   compared with :func:`secrets.compare_digest` (constant time — no early-exit
   timing leak on the secret).

The gate lives in ``app.py``'s ``AuthMiddleware`` (a small, clearly-commented
branch keyed on this prefix) so an un-tokened request never reaches a handler.
This module ALSO re-checks the token defensively (defense in depth, and so the
router is safe to mount on a bare app in tests / if auth is disabled).

Every honored request is **owner-scoped**: the engine sets ``X-Applicant-Owner``
to the user the work is for, mirroring the impersonation attribution the loopback
internal-tool path already uses. Lanes MUST scope their reads/writes to
:func:`internal_owner` so one user's engine run can never read another user's
calendar / research / models.

## Lane contract (each lane implements its own placeholder below)

| Lane | Endpoint                                   | Returns |
|------|--------------------------------------------|---------|
| A    | ``GET  /api/applicant/internal/calendar/interviews`` | auto-detected interview events for the owner |
| B    | ``POST /api/applicant/internal/research``  | deep-research run for the owner |
| C    | ``GET  /api/applicant/internal/local-models`` | Cookbook-served local models |

See ``workspace/APPLICANT_INTEGRATION.md`` ("Stage 2.5 callback channel") for the
full contract + file-ownership map so the three lanes do not collide.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

#: Header the engine sets to prove it holds the shared secret.
INTERNAL_TOKEN_HEADER = "X-Applicant-Internal-Token"
#: Header the engine sets to attribute the call to a specific workspace user.
INTERNAL_OWNER_HEADER = "X-Applicant-Owner"
#: Route prefix for the whole reverse channel. The AuthMiddleware branch in
#: app.py keys on this so an un-tokened request never reaches a handler.
INTERNAL_PREFIX = "/api/applicant/internal"


def internal_token() -> str:
    """The configured shared secret, or "" when the channel is DISABLED.

    Read live (not import-time) so tests can set/clear it via monkeypatch and so
    a deploy that injects the env after import still works.
    """
    return (os.environ.get("APPLICANT_INTERNAL_TOKEN") or "").strip()


def internal_channel_enabled() -> bool:
    """True only when a non-empty shared secret is configured."""
    return bool(internal_token())


def verify_internal_token(request: Request) -> None:
    """Defense-in-depth gate re-checked inside every handler.

    Raises 403 when the channel is disabled (no secret) or the presented
    ``X-Applicant-Internal-Token`` does not match (constant-time). The
    AuthMiddleware branch in app.py performs the same check earlier; this keeps
    handlers safe when mounted on a bare app (tests) or with auth disabled.
    """
    secret = internal_token()
    if not secret:
        # Channel disabled: never reveal whether a token would have matched.
        raise HTTPException(status_code=403, detail="Internal channel disabled")
    presented = request.headers.get(INTERNAL_TOKEN_HEADER) or ""
    if not secrets.compare_digest(presented, secret):
        raise HTTPException(status_code=403, detail="Invalid internal token")


def internal_owner(request: Request) -> str:
    """The owner the engine attributed this call to (``X-Applicant-Owner``).

    May be "" when the engine did not attribute the call (single-user / system
    work). Lanes MUST use this to scope their reads/writes — never trust an owner
    embedded in the body.
    """
    return (request.headers.get(INTERNAL_OWNER_HEADER) or "").strip()


# ======================================================================== #
# LANE A — calendar interview detection (self-contained; merge-trivial).    #
# Everything below this banner up to the matching banner is lane A's only.  #
# ======================================================================== #

#: How far ahead to scan the owner's calendar for interviews.
CALENDAR_INTERVIEW_HORIZON_DAYS = 30
#: Hard cap on returned interview events (bounded payload).
CALENDAR_INTERVIEW_MAX = 25

#: Phrases that strongly indicate a hiring-process event. Matched
#: case-insensitively on a whole-word boundary against title + notes so
#: "interview"/"phone screen"/"onsite" hit while incidental substrings
#: ("screenshot", "winterview") do not. Ordered loosely most→least specific
#: so the FIRST match becomes the surfaced ``detected_kind``.
_INTERVIEW_SIGNALS: tuple[str, ...] = (
    "phone screen",
    "hiring manager",
    "technical interview",
    "coding interview",
    "system design",
    "take-home",
    "take home",
    "panel interview",
    "final round",
    "onsite interview",
    "on-site interview",
    "recruiter screen",
    "recruiter call",
    "recruiter chat",
    "interview",
    "onsite",
    "on-site",
    "screening",
    "panel",
    "recruiter",
    "hiring",
)

#: Tokens that, on their own, are too generic to flag an event — they only
#: count toward detection when paired with a hiring word (handled in
#: :func:`_detect_interview`). Kept separate so a plain "Team screen share"
#: or "1:1" does not get mislabelled as an interview.
_WEAK_SIGNALS: tuple[str, ...] = ("screen", "round", "call")

#: "<Company> interview", "interview with <Company>", "interview @ <Company>",
#: "interview at <Company>" — best-effort company extraction from the title.
# Signal/connector words are case-insensitive; the company group stays
# case-SENSITIVE (scoped ``(?i:...)``) so it only captures a real capitalized
# proper noun ("Acme Corp") and not connective words ("with the team").
_COMPANY_WITH = re.compile(
    r"(?i:\b(?:interview|screen|call|onsite|chat)\b[^A-Za-z0-9]+(?:with|w/|@|at))\s+"
    r"([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,3})",
)
_COMPANY_LEADING = re.compile(
    r"^\s*([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,3})\s+"
    r"(?i:interview|phone\s+screen|screen|onsite|on-site|panel)\b",
)

#: A meeting link in the notes/location (zoom/meet/teams/webex/generic https).
_LINK_RE = re.compile(
    r"https?://[^\s<>\"')]+",
    re.IGNORECASE,
)


def _detect_interview(title: str, notes: str) -> str | None:
    """Return the matched interview ``kind`` for an event, or None.

    Heuristic: a strong signal phrase anywhere in title+notes flags the event.
    A weak signal ("screen"/"round"/"call") only flags when it co-occurs with a
    hiring word ("interview"/"recruiter"/"hiring"/"candidate"/"position"/"role")
    so generic meetings ("screen share", "standup call") are NOT flagged.
    """
    hay = f"{title or ''}\n{notes or ''}".lower()
    if not hay.strip():
        return None
    for phrase in _INTERVIEW_SIGNALS:
        if re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", hay):
            return phrase
    # Weak signals need corroboration from a hiring-context word.
    hiring_ctx = re.search(
        r"\b(recruit\w*|hiring|candidate|position|role|job application|"
        r"applicant tracking|greenhouse|lever|workday)\b",
        hay,
    )
    if hiring_ctx:
        for weak in _WEAK_SIGNALS:
            if re.search(rf"(?<![a-z]){re.escape(weak)}(?![a-z])", hay):
                return weak
    return None


def _detect_company(title: str, notes: str) -> str | None:
    """Best-effort company name from the event title (None when unclear)."""
    title = (title or "").strip()
    m = _COMPANY_WITH.search(title) or _COMPANY_WITH.search(notes or "")
    if m:
        cand = m.group(1).strip(" .-")
        if cand:
            return cand
    m = _COMPANY_LEADING.match(title)
    if m:
        cand = m.group(1).strip(" .-")
        # Avoid echoing the signal word itself as a "company".
        if cand and cand.lower() not in {"interview", "phone", "panel", "onsite"}:
            return cand
    return None


def _extract_link(*fields: str) -> str:
    """First http(s) link found across the given fields (location/notes)."""
    for f in fields:
        if not f:
            continue
        m = _LINK_RE.search(f)
        if m:
            return m.group(0).rstrip(".,);")
    return ""


def detect_interviews(events: list[dict]) -> list[dict]:
    """Filter+annotate raw event dicts down to auto-detected interviews.

    Each input event is a dict with at least ``title``/``summary``,
    ``start``/``dtstart``, optionally ``end``/``dtend``, ``location``,
    ``notes``/``description``. Output is the clean engine-facing shape:
    ``{title, start, end, location, link, detected_company, detected_kind,
    all_day, calendar}``. Pure (no IO) so it is unit-testable in isolation.
    """
    out: list[dict] = []
    for ev in events:
        title = ev.get("title") or ev.get("summary") or ""
        notes = ev.get("notes") or ev.get("description") or ""
        kind = _detect_interview(title, notes)
        if not kind:
            continue
        location = ev.get("location") or ""
        link = ev.get("link") or _extract_link(location, notes)
        out.append(
            {
                "title": title,
                "start": ev.get("start") or ev.get("dtstart") or "",
                "end": ev.get("end") or ev.get("dtend") or "",
                "all_day": bool(ev.get("all_day")),
                "location": location,
                "link": link,
                "detected_company": _detect_company(title, notes),
                "detected_kind": kind,
                "calendar": ev.get("calendar") or "",
            }
        )
        if len(out) >= CALENDAR_INTERVIEW_MAX:
            break
    return out


def _read_owner_calendar_events(owner: str) -> list[dict]:
    """Owner-scoped read of upcoming (next ~30d) events from the native calendar.

    Returns raw event dicts (title/notes/start/end/location/calendar). Isolated
    in this thin function so tests can monkeypatch it and exercise the route
    without a live DB. Owner "" means single-user/no-scope (mirrors the native
    calendar's FALLBACK_OWNER behaviour) — never trust an owner from the body.
    """
    from core.database import CalendarCal, CalendarEvent, SessionLocal

    now = datetime.utcnow()
    horizon = now + timedelta(days=CALENDAR_INTERVIEW_HORIZON_DAYS)
    db = SessionLocal()
    try:
        q = db.query(CalendarEvent).join(CalendarCal).filter(
            CalendarEvent.dtstart >= now,
            CalendarEvent.dtstart <= horizon,
            CalendarEvent.status != "cancelled",
        )
        if owner:
            q = q.filter(CalendarCal.owner == owner)
        rows = q.order_by(CalendarEvent.dtstart).limit(200).all()
        events: list[dict] = []
        for e in rows:
            suffix = "Z" if getattr(e, "is_utc", False) and not e.all_day else ""
            events.append(
                {
                    "title": e.summary or "",
                    "notes": e.description or "",
                    "location": e.location or "",
                    "start": (e.dtstart.isoformat() + suffix) if e.dtstart else "",
                    "end": (e.dtend.isoformat() + suffix) if e.dtend else "",
                    "all_day": bool(e.all_day),
                    "calendar": e.calendar.name if e.calendar else "",
                }
            )
        return events
    finally:
        db.close()


# ======================================================================== #
# END LANE A                                                                #
# ======================================================================== #


def setup_applicant_internal_routes() -> APIRouter:
    router = APIRouter(prefix=INTERNAL_PREFIX, tags=["applicant-internal"])

    @router.get("/ping")
    async def ping(request: Request) -> dict:
        """Liveness + auth probe for the engine's WorkspacePort.

        Working now: the engine calls this from ``HttpWorkspaceClient.ping()`` to
        learn the channel is reachable AND the shared secret matches. Returns the
        attributed owner so the engine can confirm impersonation wiring.
        """
        verify_internal_token(request)
        return {"ok": True, "owner": internal_owner(request) or None}

    # --- Lane placeholders (501 until the owning lane implements them) -------
    # Each lane REPLACES its own stub here (this file is the shared channel) OR,
    # preferably, mounts its own router under the same prefix and registers it in
    # app.py. Keep the path + auth contract identical to what is documented.

    @router.get("/calendar/interviews")
    async def calendar_interviews(request: Request):
        """LANE A — auto-detected interview calendar events for the owner.

        Owner-scoped (``internal_owner``): reads the requesting owner's native
        workspace calendar, filters upcoming events (next
        ``CALENDAR_INTERVIEW_HORIZON_DAYS`` days, capped at
        ``CALENDAR_INTERVIEW_MAX``) to those auto-detected as interview-like via
        :func:`detect_interviews`, and returns ``{"interviews": [...]}``. A DB
        hiccup degrades to an empty list rather than 500ing the engine.
        """
        verify_internal_token(request)
        owner = internal_owner(request)
        try:
            raw = _read_owner_calendar_events(owner)
        except Exception as exc:  # never 500 the engine's callback
            logger.warning("calendar_interviews read failed: %s", exc)
            return {"interviews": []}
        return {"interviews": detect_interviews(raw)}

    @router.post("/research")
    async def research(request: Request):
        """LANE B placeholder — run deep research for the owner.

        Contract: owner-scoped; body ``{"query": str, ...}`` -> a research run /
        report handle. 501 until lane B lands.
        """
        verify_internal_token(request)
        raise HTTPException(status_code=501, detail="research not implemented (lane B)")

    @router.get("/local-models")
    async def local_models(request: Request):
        """LANE C placeholder — list Cookbook-served local models.

        Contract: ``{"models": [...]}`` of locally-served models the Cookbook is
        currently exposing. 501 until lane C lands.
        """
        verify_internal_token(request)
        raise HTTPException(status_code=501, detail="local-models not implemented (lane C)")

    return router
