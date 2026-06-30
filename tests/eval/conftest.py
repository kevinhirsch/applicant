"""Pytest configuration for eval harness tests.

Marks all eval tests as ``integration`` so they are skipped in the default
unit-only CI lane (no browser, no LLM).
"""

from __future__ import annotations

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "eval: browser-agent evaluation test (requires AgentLab + BrowserGym + browser)"
    )


def pytest_collection_modifyitems(items):
    for item in items:
        if "eval" in item.keywords:
            item.add_marker(pytest.mark.integration)
