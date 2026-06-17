"""ResearchService — deep research as a CAPPED, cached engine agent tool (Lane B).

Stage 2.5 added the engine -> workspace callback channel
(``WorkspacePort.run_research``). This service is the engine-side consumer that
exposes the workspace's native deep-research to the autonomous agent as a tool it
can *escalate* to when it hits a genuine knowledge gap (understanding a
company/role to tailor materials, or answering a question), plus the same path
for an explicit user-initiated request.

Escalation is deliberately bounded so a runaway agent can't burn unbounded
research runs (each is a multi-source LLM job):

* **Budget cap** — at most :data:`DEFAULT_MAX_RESEARCH_CALLS` *fresh* runs per
  campaign per process. A cache hit does NOT consume budget.
* **Dedupe** — an identical (campaign, normalized-query) is collapsed: the first
  run's report is reused, never re-run.
* **Cache** — every successful report is memoized on the service keyed by
  (campaign, normalized-query) so re-use is free for the rest of the run.

The service degrades gracefully: when ``workspace.available()`` is False (no
shared secret), or the workspace raises :class:`WorkspaceError`, ``research``
returns ``None`` (auto-escalation path) and ``run_for_campaign`` returns a typed
"unavailable" result rather than raising — the agent loop never crashes on a
flaky / disabled workspace.

The cache + budget ledgers are in-memory (the established idiom for the agent
loop's own per-campaign ledgers), keyed by campaign id, and pruned on demand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from applicant.observability.logging import get_logger
from applicant.ports.driven.workspace import WorkspaceError

log = get_logger(__name__)

#: Per-campaign cap on FRESH research runs (cache hits don't count). Bounds the
#: agent's auto-escalation so it can't issue unbounded multi-source LLM jobs.
DEFAULT_MAX_RESEARCH_CALLS = 3


@dataclass
class ResearchReport:
    """Structured outcome of one research request (fresh run or cache hit)."""

    query: str
    summary: str = ""
    key_findings: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    #: True when served from cache (no fresh run, no budget consumed).
    cached: bool = False
    #: True only when the workspace channel was unavailable / the run failed.
    unavailable: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "summary": self.summary,
            "key_findings": self.key_findings,
            "sources": self.sources,
            "cached": self.cached,
            "unavailable": self.unavailable,
            "reason": self.reason,
        }


def _normalize_query(query: str) -> str:
    """Canonical dedupe/cache key: case-folded, whitespace-collapsed."""
    return " ".join((query or "").split()).strip().lower()


class ResearchService:
    """Capped, deduped, cached deep-research tool over the WorkspacePort."""

    def __init__(self, *, workspace: Any, max_calls: int = DEFAULT_MAX_RESEARCH_CALLS):
        self._workspace = workspace
        self._max_calls = max(0, int(max_calls))
        # (campaign_key, normalized_query) -> ResearchReport (successful runs only).
        self._cache: dict[tuple[str, str], ResearchReport] = {}
        # campaign_key -> count of FRESH runs charged against the budget.
        self._calls: dict[str, int] = {}

    # --- introspection ----------------------------------------------------
    def available(self) -> bool:
        """True only when the workspace callback channel is configured."""
        try:
            return bool(self._workspace) and bool(self._workspace.available())
        except Exception:  # pragma: no cover - defensive: gate failure -> off
            return False

    def calls_made(self, campaign_id: Any) -> int:
        return self._calls.get(str(campaign_id), 0)

    def budget_remaining(self, campaign_id: Any) -> int:
        return max(0, self._max_calls - self.calls_made(campaign_id))

    def cached_report(self, campaign_id: Any, query: str) -> ResearchReport | None:
        return self._cache.get((str(campaign_id), _normalize_query(query)))

    # --- the core run -----------------------------------------------------
    def research(
        self,
        campaign_id: Any,
        query: str,
        *,
        owner: str | None = None,
        company: str | None = None,
        role: str | None = None,
        context: str | None = None,
        max_time: int | None = None,
        force: bool = False,
    ) -> ResearchReport | None:
        """Run (or reuse) research for ``query`` scoped to ``campaign_id``.

        AUTO-ESCALATION entry point. Returns ``None`` (never raises) when the run
        cannot proceed — channel off, budget spent (no cache hit), empty query, or
        a workspace failure — so the agent loop simply proceeds without research.

        * Dedupe/cache: an identical (campaign, query) is served from cache for
          free (does NOT consume budget) unless ``force`` is set.
        * Budget: a FRESH run is charged against the per-campaign cap; when the cap
          is reached and there is no cache hit, returns ``None``.
        """
        norm = _normalize_query(query)
        if not norm:
            return None
        ckey = str(campaign_id)
        cache_key = (ckey, norm)

        # Cache / dedupe — free, no budget consumed.
        if not force:
            hit = self._cache.get(cache_key)
            if hit is not None:
                # Return a copy flagged cached so the caller can tell it was free.
                return ResearchReport(
                    query=hit.query,
                    summary=hit.summary,
                    key_findings=list(hit.key_findings),
                    sources=list(hit.sources),
                    cached=True,
                )

        if not self.available():
            log.info("research_skip_channel_off", campaign_id=ckey)
            return None

        # Budget cap on FRESH runs (cache misses).
        if self.calls_made(campaign_id) >= self._max_calls:
            log.info("research_skip_budget_exhausted", campaign_id=ckey)
            return None

        try:
            raw = self._workspace.run_research(
                query=query,
                owner=owner,
                company=company,
                role=role,
                context=context,
                max_time=max_time,
            )
        except WorkspaceError as exc:
            # Degrade gracefully: a flaky / down workspace never crashes the loop.
            log.warning("research_run_failed", campaign_id=ckey, error=str(exc))
            return None
        except Exception as exc:  # pragma: no cover - defensive: never escape
            log.warning("research_run_error", campaign_id=ckey, error=str(exc))
            return None

        # Charge the budget only after a successful fresh run.
        self._calls[ckey] = self.calls_made(campaign_id) + 1
        report = self._parse(query, raw)
        self._cache[cache_key] = report
        log.info(
            "research_run_complete",
            campaign_id=ckey,
            calls_made=self._calls[ckey],
            sources=len(report.sources),
        )
        # Return a fresh (cached=False) view.
        return ResearchReport(
            query=report.query,
            summary=report.summary,
            key_findings=list(report.key_findings),
            sources=list(report.sources),
            cached=False,
        )

    # --- manual trigger ---------------------------------------------------
    def run_for_campaign(
        self,
        campaign_id: Any,
        query: str,
        *,
        owner: str | None = None,
        company: str | None = None,
        role: str | None = None,
        context: str | None = None,
        max_time: int | None = None,
        force: bool = False,
    ) -> ResearchReport:
        """Explicit, user-initiated research request (manual trigger).

        Same capped/deduped/cached path as auto-escalation but ALWAYS returns a
        ``ResearchReport`` (never ``None``): an ``unavailable=True`` report carries
        the reason so the UI/assistant can surface it instead of a 500.
        """
        report = self.research(
            campaign_id,
            query,
            owner=owner,
            company=company,
            role=role,
            context=context,
            max_time=max_time,
            force=force,
        )
        if report is not None:
            return report
        # Disambiguate WHY there is no report so the caller can react.
        if not _normalize_query(query):
            return ResearchReport(query=query, unavailable=True, reason="empty_query")
        if not self.available():
            return ResearchReport(
                query=query, unavailable=True, reason="workspace_unavailable"
            )
        if self.budget_remaining(campaign_id) <= 0:
            return ResearchReport(
                query=query, unavailable=True, reason="budget_exhausted"
            )
        return ResearchReport(query=query, unavailable=True, reason="research_failed")

    # --- parsing ----------------------------------------------------------
    @staticmethod
    def _parse(query: str, raw: Any) -> ResearchReport:
        """Map the workspace's structured response into a ``ResearchReport``."""
        if not isinstance(raw, dict):
            return ResearchReport(query=query, summary=str(raw or ""))
        findings = raw.get("key_findings") or []
        if not isinstance(findings, list):
            findings = []
        sources = raw.get("sources") or []
        if not isinstance(sources, list):
            sources = []
        return ResearchReport(
            query=raw.get("query") or query,
            summary=str(raw.get("summary") or ""),
            key_findings=[str(f) for f in findings],
            sources=[s for s in sources if isinstance(s, dict)],
        )
