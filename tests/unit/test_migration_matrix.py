import pytest
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


@pytest.fixture
def matrix():
    path = CONFIG_DIR / "migration_matrix.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# (a) DISJOINT: no entity appears in BOTH migrates and never_migrates
# ---------------------------------------------------------------------------

def test_migrates_and_never_migrates_are_disjoint(matrix):
    """No source_entity appears in both the migrates and never_migrates lists."""
    migrating_entities = {row["source_entity"] for row in matrix["migrates"]}
    never_migrating_entities = {row["entity"] for row in matrix["never_migrates"]}
    overlap = migrating_entities & never_migrating_entities
    assert not overlap, f"Entities appear in both migrates and never_migrates: {overlap}"


# ---------------------------------------------------------------------------
# (b) INVARIANT (D15): every engine-owned entity is in never_migrates
#     and ABSENT from migrates
# ---------------------------------------------------------------------------

def test_all_engine_owned_entities_in_never_migrates(matrix):
    """All engine-owned entities (D15) must be listed in never_migrates."""
    required_never_migrate = {
        "applications", "generated_documents", "provenance", "curation", "attributes"
    }
    declared_never = {row["entity"] for row in matrix["never_migrates"]}
    missing = required_never_migrate - declared_never
    assert not missing, (
        f"Engine-owned entities missing from never_migrates: {missing}"
    )


def test_no_engine_owned_entity_in_migrates(matrix):
    """No engine-owned entity (D15) appears in the migrates list."""
    engine_owned = {"applications", "generated_documents", "provenance", "curation", "attributes"}
    migrating_entities = {row["source_entity"] for row in matrix["migrates"]}
    leaked = engine_owned & migrating_entities
    assert not leaked, (
        f"Engine-owned entities must NEVER appear in migrates; found: {leaked}"
    )


# ---------------------------------------------------------------------------
# (c) D19: job-search memory uses curation-gated mechanism
# ---------------------------------------------------------------------------

def test_job_search_memory_is_curation_gated(matrix):
    """The job_search_memories row must use mechanism 'curation-gated' (D19)."""
    job_memories = [
        row for row in matrix["migrates"]
        if row["source_entity"] == "job_search_memories"
    ]
    assert len(job_memories) == 1, (
        f"Expected exactly 1 migrates row for job_search_memories, found {len(job_memories)}"
    )
    assert job_memories[0]["mechanism"] == "curation-gated", (
        f"job_search_memories must use 'curation-gated' mechanism, "
        f"got '{job_memories[0]['mechanism']}'"
    )


# ---------------------------------------------------------------------------
# (d) Schema: every row has required fields
# ---------------------------------------------------------------------------

def test_every_migrates_row_has_required_fields(matrix):
    """Every migrates row must have source_entity, target_system, and a valid mechanism."""
    valid_mechanisms = {"direct", "curation-gated"}
    for i, row in enumerate(matrix["migrates"]):
        assert "source_entity" in row, f"migrates[{i}] missing 'source_entity'"
        assert "target_system" in row, f"migrates[{i}] missing 'target_system'"
        assert "mechanism" in row, f"migrates[{i}] missing 'mechanism'"
        assert row["mechanism"] in valid_mechanisms, (
            f"migrates[{i}] invalid mechanism '{row['mechanism']}'; "
            f"valid: {valid_mechanisms}"
        )


def test_every_never_migrates_row_has_reason(matrix):
    """Every never_migrates row must have a reason."""
    for i, row in enumerate(matrix["never_migrates"]):
        assert "entity" in row, f"never_migrates[{i}] missing 'entity'"
        assert "reason" in row, f"never_migrates[{i}] missing 'reason'"
        assert isinstance(row["reason"], str) and len(row["reason"]) > 10, (
            f"never_migrates[{i}] reason too short or missing"
        )
