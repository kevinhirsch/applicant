"""Boot-time capability self-report (FR-OBS / NFR-OPS, issue #188).

The engine shells out to external binaries and **silently degrades** when they are
absent (``shutil.which()`` returns ``None`` → no real output). That silence is a
deploy hazard: a missing TeX/LibreOffice/Chrome in the shipped image looks healthy
until a résumé renders blank or pre-fill detects nothing. This module makes the
state explicit — a small report that names each external capability and whether it
is wired to a **real** binary or running as a **stub** (degraded).

Lift-and-shift: the underlying detection already lives in
``applicant.observability.capabilities`` (the same ``shutil.which`` checks the
adapters use and ``/healthz`` surfaces). This module does not re-detect; it folds
that status into the operator-facing ``{resume_renderer, browser, orchestrator}``
real-vs-stub shape the startup report and #188 acceptance criterion expect.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass

from applicant.observability.capabilities import capability_status

#: Status strings: ``real`` = the backing binary/dependency is present and the
#: capability runs for real; ``stub`` = it is absent and the engine degrades.
REAL = "real"
STUB = "stub"


@dataclass(frozen=True)
class Capability:
    """One external capability and whether it is backed by a real binary."""

    name: str
    status: str  # REAL | STUB
    detail: str  # which binary/dependency satisfied (or what is missing)

    @property
    def is_real(self) -> bool:
        return self.status == REAL


def _ok(status_text: str) -> bool:
    """The observability helpers report ``"ok (...)"`` when a capability is real."""
    return status_text.lower().startswith("ok")


def build_capability_report(
    *,
    browser_real: bool = True,
    postgres_engine: object | None = None,
) -> dict[str, Capability]:
    """Detect each external capability and report it as real-vs-stub (#188).

    Reuses ``capability_status`` for the actual probing, then maps it into the
    operator-facing capabilities the startup report (and the P1-3 health-panel
    endpoint, below) name:

    * ``postgres`` — real when a live SQLAlchemy engine is wired (persistence is
      durable); stub when the storage layer fell back to in-memory (data is
      NOT persisted across restarts).
    * ``resume_renderer`` — real when EITHER TeX (LaTeX path) OR LibreOffice (docx
      fallback) is present; both paths are reachable per the onboarding choice.
    * ``browser`` — real when the configured automation browser binary is present.
    * ``orchestrator`` — the in-process shim is always real; DBOS is real only when
      the optional ``dbos`` package is installed for the requested backend.

    Returns a mapping of capability name -> :class:`Capability`. Pure detection (no
    side effects), so it is safe at boot and deterministic per host.
    """
    status = capability_status(
        browser_real=browser_real, postgres_engine=postgres_engine
    )

    postgres = Capability("postgres", REAL if _ok(status["postgres"]) else STUB, status["postgres"])

    # Résumé rendering is real if either render backend is present.
    tex_ok = _ok(status["tex"])
    office_ok = _ok(status["libreoffice"])
    if tex_ok or office_ok:
        backers = [
            status[k].split("(", 1)[-1].rstrip(")")
            for k, present in (("tex", tex_ok), ("libreoffice", office_ok))
            if present
        ]
        resume = Capability(
            "resume_renderer", REAL, "backed by " + ", ".join(backers)
        )
    else:
        resume = Capability(
            "resume_renderer",
            STUB,
            "no TeX (lualatex/xelatex) or LibreOffice (soffice) on PATH — renders a stub",
        )

    # Browser: capability_status already encodes real vs degraded.
    browser = Capability(
        "browser",
        REAL if _ok(status["browser"]) else STUB,
        status["browser"],
    )

    report = {c.name: c for c in (postgres, resume, browser, _orchestrator())}
    return report


def _orchestrator() -> Capability:
    """Durable orchestration backend.

    The default in-process ``shim`` is always real (no extra dependency). Selecting
    DBOS (``ORCHESTRATOR_BACKEND=dbos``) requires the optional ``dbos`` package; when
    selected but missing, the engine runs on the shim — report it honestly as a stub.
    """
    backend = (os.getenv("ORCHESTRATOR_BACKEND") or "shim").strip().lower()
    if backend == "shim":
        return Capability("orchestrator", REAL, "in-process checkpoint shim")
    if importlib.util.find_spec("dbos") is not None:
        return Capability("orchestrator", REAL, "dbos (Postgres-backed workflows)")
    return Capability(
        "orchestrator",
        STUB,
        "ORCHESTRATOR_BACKEND=dbos requested but the dbos package is not installed",
    )


def report_as_dict(
    *, browser_real: bool = True, postgres_engine: object | None = None
) -> dict[str, dict[str, str]]:
    """The capability report flattened for logging / a health payload."""
    return {
        name: {"status": cap.status, "detail": cap.detail}
        for name, cap in build_capability_report(
            browser_real=browser_real, postgres_engine=postgres_engine
        ).items()
    }


# ═══════════════════════════════════════════════════════════════════════════
# P1-3 (issue #655) — the owner-facing "honest health panel" API shape.
#
# ``build_capability_report``/``report_as_dict`` above are the pre-existing
# (#188) boot-time self-report — real-vs-stub + a terse detail string, logged
# at startup only. Nothing exposed it over HTTP, so a self-hoster had no way to
# see WHY the assistant hadn't started (no browser? no Postgres?) short of
# reading container logs. ``api_capability_report`` wraps the SAME detection
# (no re-probing, no new state) with the two things a front-door render needs
# that the boot log never needed: a plain-language label + actionable fix copy
# per item, and a ``load_bearing`` flag so the UI can distinguish "the search
# cannot run at all" from "a nice-to-have is off". Never fabricates a status —
# every entry here traces 1:1 to a real ``Capability`` from
# ``build_capability_report``.
# ═══════════════════════════════════════════════════════════════════════════

#: Display order + plain-language label for each capability the panel shows.
_LABELS: dict[str, str] = {
    "postgres": "Database (Postgres)",
    "resume_renderer": "Résumé renderer",
    "browser": "Automation browser",
    "orchestrator": "Durable orchestrator",
}

#: Capabilities whose STUB status blocks the autonomous job-search loop from
#: doing real work — these drive the Today banner (P1-3 DoD: "a Today banner
#: when anything load-bearing is degraded"). ``orchestrator`` is deliberately
#: excluded: the default in-process shim is already a fully durable backend,
#: so a STUB there only means an explicitly-requested ``dbos`` upgrade didn't
#: install — the search still runs, just not on the requested backend.
LOAD_BEARING: frozenset[str] = frozenset({"postgres", "resume_renderer", "browser"})

#: Actionable fix copy per capability, shown only while that item is STUB —
#: names the concrete deploy-time fix (env var / package / binary), never a
#: vague "contact support".
_FIX_COPY: dict[str, str] = {
    "postgres": (
        "Set DATABASE_URL to a reachable Postgres instance in your deploy .env "
        "and restart the stack. Until then, application data will NOT persist "
        "across restarts."
    ),
    "resume_renderer": (
        "Install a TeX engine (lualatex or xelatex, e.g. TeX Live with the "
        "moderncv/fontspec/fontawesome5 packages) or LibreOffice headless "
        "(soffice) in the engine image, then restart. Until then, résumés "
        "render as a placeholder stub."
    ),
    "browser": (
        "Install the configured automation browser (camoufox, or Google "
        "Chrome for the chromium fallback via BROWSER_ENGINE=chromium) in the "
        "engine image and set BROWSER_REAL=true, then restart. Until then, "
        "pre-fill automation cannot run against real job sites."
    ),
    "orchestrator": (
        "Install the optional durable-orchestration extra "
        "(uv sync --extra durable-orchestration) or unset ORCHESTRATOR_BACKEND "
        "to run on the built-in in-process shim, which is already durable "
        "across restarts."
    ),
}

#: Display order for the panel — matches the DoR's own listing (postgres,
#: resume renderer, browser, orchestrator).
_ORDER: tuple[str, ...] = ("postgres", "resume_renderer", "browser", "orchestrator")


def api_capability_report(
    *, browser_real: bool = True, postgres_engine: object | None = None
) -> dict[str, object]:
    """The P1-3 health-panel payload: each capability + label + fix copy.

    Returns::

        {
          "capabilities": [
            {"name": "postgres", "label": "Database (Postgres)",
             "status": "real"|"stub", "detail": "...",
             "load_bearing": bool, "fix": "..." (non-empty only when stub)},
            ...
          ],
          "degraded": [names with status == stub],
          "load_bearing_degraded": [names with status == stub AND load_bearing],
          "all_real": not degraded,
        }

    Pure (no side effects, no timestamp) — the caller (the health router) adds
    ``generated_at`` since a wall-clock stamp doesn't belong in a detection
    function that must stay deterministic per host for testing.
    """
    report = build_capability_report(
        browser_real=browser_real, postgres_engine=postgres_engine
    )
    items: list[dict[str, object]] = []
    degraded: list[str] = []
    load_bearing_degraded: list[str] = []
    for name in _ORDER:
        cap = report.get(name)
        if cap is None:
            continue
        is_stub = cap.status == STUB
        load_bearing = name in LOAD_BEARING
        items.append(
            {
                "name": cap.name,
                "label": _LABELS.get(cap.name, cap.name),
                "status": cap.status,
                "detail": cap.detail,
                "load_bearing": load_bearing,
                "fix": _FIX_COPY.get(cap.name, "") if is_stub else "",
            }
        )
        if is_stub:
            degraded.append(cap.name)
            if load_bearing:
                load_bearing_degraded.append(cap.name)
    return {
        "capabilities": items,
        "degraded": degraded,
        "load_bearing_degraded": load_bearing_degraded,
        "all_real": not degraded,
    }
