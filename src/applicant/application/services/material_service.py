"""MaterialService (FR-RESUME-*, FR-ANSWER-1).

# STAGE B — owned by Phase 3; flesh out here.

Generates resume variants / cover letters / screening answers, applies the
truthfulness post-filter, and routes everything through the review gate. Stub
until Phase 3.
"""

from __future__ import annotations

from applicant.core.ids import ApplicationId


class MaterialService:
    def __init__(self, storage, llm, resume_tailoring) -> None:
        self._storage = storage
        self._llm = llm
        self._resume_tailoring = resume_tailoring

    def prepare_materials(self, application_id: ApplicationId) -> None:
        raise NotImplementedError("STAGE B — Phase 3: generate + post-filter + review gate.")
