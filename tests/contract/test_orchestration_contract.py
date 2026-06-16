"""Durable-orchestration contract against the CheckpointShimOrchestrator."""

from __future__ import annotations

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from tests.contract.base import OrchestrationPortContract


@pytest.mark.contract
class TestCheckpointShimContract(OrchestrationPortContract):
    @pytest.fixture
    def adapter(self, tmp_path):
        return CheckpointShimOrchestrator(str(tmp_path / "ckpt"))
