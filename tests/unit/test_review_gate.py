import pytest

from applicant.core.errors import ReviewRequired
from applicant.core.rules.review_gate import (
    ReviewableMaterial,
    can_submit,
    ensure_submittable,
    material_blocks_submission,
)


@pytest.fixture(autouse=True)
def _no_cache():
    """Module is stateless — no cache or global state to clear."""
    yield


class TestReviewableMaterial:
    """Tests for ReviewableMaterial — frozen dataclass for review-gate materials."""

    def test_constructs_with_all_fields(self):
        m = ReviewableMaterial(identifier="resume-v1", is_generated=True, approved=False)
        assert m.identifier == "resume-v1"
        assert m.is_generated is True
        assert m.approved is False

    def test_constructs_with_approved_material(self):
        m = ReviewableMaterial(identifier="cl-001", is_generated=True, approved=True)
        assert m.approved is True

    def test_constructs_with_non_generated_material(self):
        m = ReviewableMaterial(identifier="base-resume", is_generated=False, approved=False)
        assert m.is_generated is False


class TestMaterialBlocksSubmission:
    """Tests for material_blocks_submission — blocks if generated & unapproved."""

    def test_generated_and_unapproved_blocks(self):
        m = ReviewableMaterial("x", is_generated=True, approved=False)
        assert material_blocks_submission(m) is True

    def test_generated_and_approved_does_not_block(self):
        m = ReviewableMaterial("x", is_generated=True, approved=True)
        assert material_blocks_submission(m) is False

    def test_non_generated_does_not_block_even_if_unapproved(self):
        m = ReviewableMaterial("x", is_generated=False, approved=False)
        assert material_blocks_submission(m) is False

    def test_non_generated_and_approved_does_not_block(self):
        m = ReviewableMaterial("x", is_generated=False, approved=True)
        assert material_blocks_submission(m) is False


class TestCanSubmit:
    """Tests for can_submit — True if no generated material is unapproved."""

    def test_empty_materials_returns_true(self):
        assert can_submit([]) is True

    def test_no_generated_material_returns_true(self):
        materials = [
            ReviewableMaterial("base-resume", is_generated=False, approved=False),
        ]
        assert can_submit(materials) is True

    def test_all_generated_and_approved_returns_true(self):
        materials = [
            ReviewableMaterial("cv-v1", is_generated=True, approved=True),
            ReviewableMaterial("cl-v1", is_generated=True, approved=True),
        ]
        assert can_submit(materials) is True

    def test_one_generated_unapproved_blocks(self):
        materials = [
            ReviewableMaterial("cv-v1", is_generated=True, approved=True),
            ReviewableMaterial("cl-v1", is_generated=True, approved=False),
        ]
        assert can_submit(materials) is False

    def test_only_generated_unapproved_blocks(self):
        materials = [
            ReviewableMaterial("base-resume", is_generated=False, approved=False),
            ReviewableMaterial("cl-v1", is_generated=True, approved=True),
            ReviewableMaterial("answer-q1", is_generated=True, approved=False),
        ]
        assert can_submit(materials) is False


class TestEnsureSubmittable:
    """Tests for ensure_submittable — raises ReviewRequired if unapproved generated material exists."""

    def test_empty_materials_does_not_raise(self):
        ensure_submittable([])

    def test_no_generated_material_does_not_raise(self):
        ensure_submittable(
            [ReviewableMaterial("base-resume", is_generated=False, approved=False)]
        )

    def test_all_generated_and_approved_does_not_raise(self):
        ensure_submittable(
            [
                ReviewableMaterial("cv-v1", is_generated=True, approved=True),
                ReviewableMaterial("cl-v1", is_generated=True, approved=True),
            ]
        )

    def test_unapproved_generated_raises_review_required(self):
        m = ReviewableMaterial("cl-v1", is_generated=True, approved=False)
        with pytest.raises(ReviewRequired) as exc_info:
            ensure_submittable([m])
        assert "cl-v1" in str(exc_info.value)
        assert "review gate" in str(exc_info.value)

    def test_unapproved_generated_mentions_all_blocking_ids(self):
        materials = [
            ReviewableMaterial("cv-v1", is_generated=True, approved=True),
            ReviewableMaterial("cl-v1", is_generated=True, approved=False),
            ReviewableMaterial("answer-q1", is_generated=True, approved=False),
        ]
        with pytest.raises(ReviewRequired) as exc_info:
            ensure_submittable(materials)
        msg = str(exc_info.value)
        assert "cl-v1" in msg
        assert "answer-q1" in msg
        assert "cv-v1" not in msg

    def test_item_not_reviewable(self):
        """Verify the function receives an iterable of ReviewableMaterial (structural test)."""
        ensure_submittable(
            [ReviewableMaterial("safe", is_generated=False, approved=False)]
        )
