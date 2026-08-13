"""Posting-liveness rule (E3): is a discovered posting still OPEN?

Pure, deterministic, no IO — given the HTTP result of loading a posting's URL
(status code + the final URL after redirects) it classifies the posting as
``live``, ``dead``, or ``unknown``. The fetch itself is IO (a driven adapter);
this rule is the testable decision, so a transient hiccup or an anti-bot block
never wrongly buries a real, live role — **only a CONFIRMED-dead posting is ever
demoted** (``unknown`` is left exactly as-is).

Motivation: freshness (dates) is NOT liveness — a fresh-looking posting can be
closed. Discovery must recheck that a surfaced role is still open, or a
great-fit role reads as a dead click (the exact failure the user hit: the
top-scored role was a dead link). Empirically (lever + greenhouse), a browser-UA
GET distinguishes LIVE (200 still at the posting URL) from DEAD (4xx/410, or a
200 that redirected to a board root / ``?error``) cleanly, with no 403.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

LivenessStatus = Literal["live", "dead", "unknown"]

#: Statuses that PROVE the posting is gone.
_DEAD_STATUSES = frozenset({400, 404, 410})
#: Statuses where we genuinely can't tell (transient error or anti-bot block).
#: NEVER demote on these — a live role behind Cloudflare must not be buried.
_UNKNOWN_STATUSES = frozenset({401, 403, 405, 408, 429, 500, 502, 503, 504, 0})


@dataclass(frozen=True)
class LivenessVerdict:
    status: LivenessStatus
    reason: str

    @property
    def is_dead(self) -> bool:
        return self.status == "dead"


def _job_token(url: str) -> str:
    """The stable job-identifying tail of an ATS posting URL (last non-empty path
    segment): greenhouse ``/jobs/<id>`` -> ``<id>``; lever ``/<slug>/<uuid>`` ->
    ``<uuid>``. Used to tell a still-on-the-posting 200 from a redirect-to-board."""
    path = urlparse(url or "").path.rstrip("/")
    return path.rsplit("/", 1)[-1].lower() if path else ""


def classify_liveness(status_code: int, final_url: str, posting_url: str) -> LivenessVerdict:
    """Classify one posting's liveness from its fetch result (pure).

    ``final_url`` is the URL after following redirects; ``posting_url`` is the
    original stored URL. Only 4xx-gone and a 200-that-redirected-off-the-posting
    are ``dead``; anti-bot/transient statuses are ``unknown`` (never demoted).
    """
    if status_code in _DEAD_STATUSES:
        return LivenessVerdict("dead", f"HTTP {status_code}")
    if status_code in _UNKNOWN_STATUSES:
        return LivenessVerdict("unknown", f"HTTP {status_code} (transient/blocked — not demoted)")
    if status_code == 200:
        final = (final_url or "").lower()
        if "error=" in final or "/404" in final or "not-found" in final or "job-not-found" in final:
            return LivenessVerdict("dead", "redirected to an error page")
        token = _job_token(posting_url)
        if token and token not in final:
            return LivenessVerdict("dead", "redirected away from the posting (board root)")
        return LivenessVerdict("live", "HTTP 200 at the posting URL")
    return LivenessVerdict("unknown", f"HTTP {status_code}")
