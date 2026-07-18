import pytest

from applicant.core.entities.viability_scoring import ViabilityScoring
from applicant.core.ids import JobPostingId


@pytest.fixture(autouse=True)
def _no_state():
    """No-op fixture for xdist parallel safety."""
    pass


@pytest.mark.unit
class TestViabilityScoringConstruction:
    """ViabilityScoring minimal and full construction."""

    def test_minimal_construction(self):
        vs = ViabilityScoring(posting_id=JobPostingId("post-1"), score=0.5)
        assert vs.posting_id == "post-1"
        assert vs.score == 0.5
        assert vs.rationale == ""

    def test_full_construction(self):
        vs = ViabilityScoring(
            posting_id=JobPostingId("post-2"),
            score=0.85,
            rationale="Good match with experience",
        )
        assert vs.posting_id == "post-2"
        assert vs.score == 0.85
        assert vs.rationale == "Good match with experience"

    def test_default_rationale_is_empty_string(self):
        vs = ViabilityScoring(posting_id=JobPostingId("post-3"), score=0.3)
        assert vs.rationale == ""

    def test_score_float_edge_cases(self):
        for val in [0.0, 0.5, 1.0]:
            vs = ViabilityScoring(posting_id=JobPostingId(f"post-{val}"), score=val)
            assert vs.score == val


@pytest.mark.unit
class TestViabilityScoringFrozen:
    """ViabilityScoring is a frozen dataclass."""

    def test_cannot_modify_posting_id(self):
        vs = ViabilityScoring(posting_id=JobPostingId("post-10"), score=0.5)
        with pytest.raises(AttributeError):
            vs.posting_id = JobPostingId("post-11")

    def test_cannot_modify_score(self):
        vs = ViabilityScoring(posting_id=JobPostingId("post-12"), score=0.5)
        with pytest.raises(AttributeError):
            vs.score = 0.9

    def test_cannot_modify_rationale(self):
        vs = ViabilityScoring(posting_id=JobPostingId("post-13"), score=0.5)
        with pytest.raises(AttributeError):
            vs.rationale = "changed"


@pytest.mark.unit
class TestViabilityScoringEqualityAndHash:
    """ViabilityScoring equality and hashability."""

    def test_equal_instances(self):
        vs1 = ViabilityScoring(posting_id=JobPostingId("post-20"), score=0.7, rationale="ok")
        vs2 = ViabilityScoring(posting_id=JobPostingId("post-20"), score=0.7, rationale="ok")
        assert vs1 == vs2

    def test_different_posting_id(self):
        vs1 = ViabilityScoring(posting_id=JobPostingId("post-21"), score=0.7)
        vs2 = ViabilityScoring(posting_id=JobPostingId("post-22"), score=0.7)
        assert vs1 != vs2

    def test_different_score(self):
        vs1 = ViabilityScoring(posting_id=JobPostingId("post-23"), score=0.5)
        vs2 = ViabilityScoring(posting_id=JobPostingId("post-23"), score=0.9)
        assert vs1 != vs2

    def test_different_rationale(self):
        vs1 = ViabilityScoring(posting_id=JobPostingId("post-24"), score=0.5, rationale="a")
        vs2 = ViabilityScoring(posting_id=JobPostingId("post-24"), score=0.5, rationale="b")
        assert vs1 != vs2

    def test_hashable(self):
        vs = ViabilityScoring(posting_id=JobPostingId("post-30"), score=0.6)
        s = {vs}
        assert vs in s

    def test_same_values_have_same_hash(self):
        vs1 = ViabilityScoring(posting_id=JobPostingId("post-31"), score=0.6)
        vs2 = ViabilityScoring(posting_id=JobPostingId("post-31"), score=0.6)
        assert hash(vs1) == hash(vs2)

    def test_different_values_have_different_hash(self):
        vs1 = ViabilityScoring(posting_id=JobPostingId("post-32"), score=0.6)
        vs2 = ViabilityScoring(posting_id=JobPostingId("post-33"), score=0.6)
        assert hash(vs1) != hash(vs2)
