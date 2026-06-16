"""Tool-registry contract against the ToolRegistry adapter."""

from __future__ import annotations

import pytest

from applicant.adapters.tools.tool_registry import ToolRegistry
from tests.contract.base import ToolRegistryPortContract


@pytest.mark.contract
class TestToolRegistryContract(ToolRegistryPortContract):
    @pytest.fixture
    def adapter(self):
        return ToolRegistry()
