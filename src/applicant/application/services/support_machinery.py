"""Support-request handling scaffold (P5-1, #703).

A pure module that captures a support/help request (subject, body, context)
into a structured record with a stable schema. No external service dependency;
storage is an in-memory list that can be swapped for a file-backed stub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence


@dataclass(frozen=True)
class SupportRequest:
    """A captured support/help request.

    Stable schema fields: an auto-generated sequential id, the free-form
    subject line, the body text, optional structured context (e.g. the page
    or feature the user was on), and an auto-populated UTC timestamp.
    """

    #: Human-readable subject line for the support request.
    subject: str
    #: Body text of the support request — the user's description or question.
    body: str
    #: Optional structured context — e.g. page name, feature ID, or diagnostics.
    context: dict = field(default_factory=dict)
    #: Monotonic id within the storage session (auto-assigned on capture).
    id: int = 0
    #: UTC timestamp of when the request was captured.
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class SupportMachinery:
    """In-memory support request handler with a stable capture interface.

    Records every support request in an ordered list and provides read access.
    The storage can be swapped for a file-backed or database stub later without
    changing the capture contract.
    """

    def __init__(self, storage: list[SupportRequest] | None = None) -> None:
        """Initialise with an optional pre-existing storage list."""
        self._storage: list[SupportRequest] = list(storage) if storage else []

    def capture(
        self,
        subject: str,
        body: str,
        context: dict | None = None,
    ) -> SupportRequest:
        """Capture a support request and store it.

        Args:
            subject: A short subject line.
            body: The request body / description.
            context: Optional structured context (defaults to empty dict).

        Returns:
            The newly created ``SupportRequest`` (frozen dataclass).
        """
        record = SupportRequest(
            subject=subject,
            body=body,
            context=context or {},
            id=len(self._storage) + 1,
        )
        self._storage.append(record)
        return record

    def list_requests(self) -> Sequence[SupportRequest]:
        """Return all captured support requests in capture order."""
        return list(self._storage)

    def get_request(self, request_id: int) -> SupportRequest | None:
        """Look up a single request by its id, or None if not found."""
        for r in self._storage:
            if r.id == request_id:
                return r
        return None

    def clear(self) -> None:
        """Clear all stored requests (useful for test isolation)."""
        self._storage.clear()
