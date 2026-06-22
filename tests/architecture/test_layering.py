"""NFR-ARCH-1 traceability anchor — hexagonal layer boundary.

Structural enforcement is the ``lint-imports`` CI step (see .github/workflows/ci.yml).
This test is the pytest-visible traceability marker so the architecture contract appears
in the test inventory alongside unit/contract/integration.  It validates that the
import-linter configuration is present and declares the expected contracts, ensuring
the CI step cannot be silently removed without breaking this test too.
"""

import tomllib
from pathlib import Path

import pytest


@pytest.mark.architecture
def test_importlinter_contracts_configured() -> None:
    """pyproject.toml must declare the two import-linter contracts for NFR-ARCH-1."""
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())

    il = data.get("tool", {}).get("importlinter", {})
    assert il, "Missing [tool.importlinter] — NFR-ARCH-1 contract removed from pyproject.toml"

    contracts = il.get("contracts", [])
    names = {c["name"] for c in contracts}

    assert any("layering" in n.lower() or "hexagonal" in n.lower() for n in names), (
        f"No hexagonal layering contract found in import-linter contracts: {names}"
    )
    assert any("pure" in n.lower() or "core" in n.lower() for n in names), (
        f"No core-purity forbidden contract found in import-linter contracts: {names}"
    )
