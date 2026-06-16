"""Mandatory review-before-submission gate (FR-RESUME-8, FR-ANSWER-1).

Any application carrying an edited resume, a generated cover letter, or a
generated screening answer must pass the interactive review/revision gate;
submission is impossible until the user approves. Generated material is never
auto-submitted.

Pure rule: the submission path must call ``ensure_submittable`` with the set of
materials bundled into the application; it raises if any generated material is
unapproved.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from applicant.core.errors import ReviewRequired


@dataclass(frozen=True)
class ReviewableMaterial:
    """A piece of material that may gate submission.

    Attributes:
        identifier: the material's id (for error messages).
        is_generated: True if AI-generated/adapted (resume variant, cover letter,
            screening answer). Pristine base-resume reuse is not "generated".
        approved: True once the user approved it through the review gate.
    """

    identifier: str
    is_generated: bool
    approved: bool


def material_blocks_submission(material: ReviewableMaterial) -> bool:
    """True if this single material would block submission (generated & unapproved)."""
    return material.is_generated and not material.approved


def can_submit(materials: Iterable[ReviewableMaterial]) -> bool:
    """True if no generated material is unapproved."""
    return not any(material_blocks_submission(m) for m in materials)


def ensure_submittable(materials: Iterable[ReviewableMaterial]) -> None:
    """Raise ``ReviewRequired`` if any generated material is unapproved."""
    blocking = [m.identifier for m in materials if material_blocks_submission(m)]
    if blocking:
        raise ReviewRequired(
            "Generated material must be approved via the review gate before submission "
            f"(FR-RESUME-8); unapproved: {', '.join(blocking)}."
        )
