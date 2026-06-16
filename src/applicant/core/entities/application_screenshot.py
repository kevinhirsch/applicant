"""ApplicationScreenshot entity — per-page archived screenshot (FR-LOG-2)."""

from __future__ import annotations

from dataclasses import dataclass

from applicant.core.ids import ApplicationId, ScreenshotId


@dataclass(frozen=True)
class ApplicationScreenshot:
    """A per-page screenshot archived during pre-fill (FR-LOG-2).

    ``page_ref`` is the storage ref returned by the browser port (a path/blob/URI
    seam — bytes can be a path/blob behind the storage port).
    """

    id: ScreenshotId
    application_id: ApplicationId
    page_ref: str
    page_url: str = ""
