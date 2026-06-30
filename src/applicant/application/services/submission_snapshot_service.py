"""Durable, immutable per-application submission snapshot (Issue #372).

On submission (or review-approval at the stop-boundary), the engine persists an
immutable snapshot per application — the exact answers/field values, the
material versions, the posting, and a timestamp — retrievable later (and in the
front-door) as the durable record of *what was actually submitted*.

The pre-fill loop already records a transient per-page log of what it filled
(``PrefillResult.filled_by_page``); this service turns the values approved at
the stop-boundary into a durable, frozen :class:`SubmissionSnapshot`.

The snapshot entity is a frozen dataclass, so it cannot be mutated after the
fact. The service persists through the ``submission_snapshots`` repository when a
storage is wired; with no storage (e.g. a unit context) it keeps an in-process
map so ``record``/``get`` still round-trip.
"""

from __future__ import annotations

from collections.abc import Mapping

from applicant.core.entities.submission_snapshot import SubmissionSnapshot
from applicant.core.ids import ApplicationId, SubmissionSnapshotId, new_id


class SubmissionSnapshotService:
    """Record and retrieve immutable per-application submission snapshots (#372).

    ``storage`` is optional: when provided it must expose a
    ``submission_snapshots`` repository (``add`` / ``get_for_application``);
    otherwise the service falls back to an in-process map.
    """

    def __init__(self, storage=None) -> None:
        self._storage = storage
        self._fallback: dict[str, SubmissionSnapshot] = {}

    def _repo(self):
        return getattr(self._storage, "submission_snapshots", None)

    def record(
        self,
        *,
        application_id: str,
        answers: Mapping | None = None,
        material_versions: Mapping | None = None,
        posting_url: str = "",
    ) -> SubmissionSnapshot:
        """Persist an immutable snapshot of a submission at the stop-boundary."""
        snapshot = SubmissionSnapshot(
            id=SubmissionSnapshotId(new_id()),
            application_id=ApplicationId(str(application_id)),
            answers=dict(answers or {}),
            material_versions=dict(material_versions or {}),
            posting_url=posting_url or "",
        )
        repo = self._repo()
        if repo is not None:
            repo.add(snapshot)
        else:
            self._fallback[str(application_id)] = snapshot
        return snapshot

    def get(self, application_id: str) -> SubmissionSnapshot | None:
        """Retrieve the snapshot recorded for an application, if any."""
        repo = self._repo()
        if repo is not None:
            return repo.get_for_application(ApplicationId(str(application_id)))
        return self._fallback.get(str(application_id))
