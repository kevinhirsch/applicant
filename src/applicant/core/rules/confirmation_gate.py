"""Confirmation-on-integral-change gate (FR-FB-3).

Any **integral** change (a core attribute value or a core criterion) requires
explicit user confirmation before commit. Non-integral updates may auto-apply
(e.g. from FR-LEARN-4 cross-referencing).

Pure rule: the attribute/criteria services must route every proposed change
through ``ensure_change_allowed`` so an integral change can never be silently
committed.
"""

from __future__ import annotations

from applicant.core.errors import ConfirmationRequired


def requires_confirmation(is_integral: bool) -> bool:
    """True if a change to a field with this integrality needs confirmation."""
    return bool(is_integral)


def ensure_change_allowed(*, is_integral: bool, user_confirmed: bool) -> None:
    """Raise ``ConfirmationRequired`` if an integral change lacks confirmation.

    Args:
        is_integral: whether the attribute/criterion being changed is integral.
        user_confirmed: whether the user has explicitly confirmed this change.
    """
    if requires_confirmation(is_integral) and not user_confirmed:
        raise ConfirmationRequired(
            "Integral change requires explicit user confirmation before commit (FR-FB-3)."
        )
