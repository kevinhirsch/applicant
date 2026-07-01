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
    three operator-facing capabilities the startup report names:

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

    report = {c.name: c for c in (resume, browser, _orchestrator())}
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
