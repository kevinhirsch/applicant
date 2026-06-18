"""BaseResumeProvider — the default :class:`ResumeProvider` (FR-RESUME-4).

Returns the user's uploaded base résumé file, recorded by the onboarding upload
route at ``intake["base_resume"]["document_path"]`` on the campaign's onboarding
profile (Phase 2: upload the base résumé as-is). Best-effort: any miss (no
profile, no path, file gone) yields ``None`` so the pre-fill loop simply skips the
file input rather than blocking.

This mirrors the existing read-back patterns in ``MaterialService._base_resume_text``
and ``app/routers/conversion.py`` — the base résumé is the only real file on disk
today; the tailored variant's ``storage_path`` is a placeholder that is never
rendered in the live loop, so it is not uploadable yet.
"""

from __future__ import annotations

from pathlib import Path

from applicant.core.entities.application import Application


class BaseResumeProvider:
    """Resolve the uploaded base résumé path for an application's campaign."""

    def __init__(self, storage) -> None:
        self._storage = storage

    def resume_file_for(self, application: Application) -> str | None:
        repo = getattr(self._storage, "onboarding_profiles", None)
        if repo is None:
            return None
        try:
            profile = repo.get_for_campaign(application.campaign_id)
            intake = getattr(profile, "intake", None) or {}
            base = intake.get("base_resume", {}) if isinstance(intake, dict) else {}
            path = str(base.get("document_path", "") or "")
        except Exception:  # pragma: no cover - defensive; never break pre-fill
            return None
        if path and Path(path).is_file():
            return path
        return None
