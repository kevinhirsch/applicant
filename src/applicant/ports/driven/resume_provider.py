"""ResumeProvider port (FR-RESUME-4).

Resolves the on-disk résumé file to attach to an ATS ``<input type=file>`` during
pre-fill. The DEFAULT implementation returns the user's uploaded base résumé
(Phase 2: "upload the base résumé as-is to prove the end-to-end Workday flow"); a
later phase can swap in a provider that returns the rendered, tailored variant
without touching the pre-fill upload site (NFR-EXT-1).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.application import Application


@runtime_checkable
class ResumeProvider(Protocol):
    """Outbound port resolving an uploadable résumé file for an application."""

    def resume_file_for(self, application: Application) -> str | None:
        """Return an existing on-disk résumé path for ``application``, or ``None``.

        ``None`` means "no uploadable file available" — the caller then skips the
        file input rather than blocking (a missing résumé is never a hard error).
        """
        ...
