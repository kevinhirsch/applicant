"""pytest-bdd configuration for the acceptance scenarios.

Covers the original P0–P4 master-spec §10 anchors and the issue-tracker
enhancement specs under ``features/enhancements/``.

TDD convention for the enhancement specs: a scenario tagged ``@pending``
describes behaviour that is specified-but-not-yet-shipped. The
``pytest_bdd_apply_tag`` hook below turns that tag into a non-strict
``xfail`` so the spec is collected and run (and shows up as a tracked
xfail) without breaking the green CI gate. When the behaviour lands, drop
the ``@pending`` tag and the scenario becomes a hard regression gate.
Scenarios with NO ``@pending`` tag must pass today — they are real
regression coverage for already-shipped fixes/behaviour.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


def pytest_bdd_apply_tag(tag, function):
    """Map the ``@pending`` / ``@wip`` Gherkin tags to a non-strict xfail.

    Returning ``True`` tells pytest-bdd we have fully handled the tag, so it
    does not also try to apply it as a (would-be-unregistered, --strict-markers
    rejecting) pytest marker. ``xfail`` is a built-in marker, so this is safe.
    """
    if tag in ("pending", "wip"):
        marker = pytest.mark.xfail(
            reason="Specified enhancement not yet implemented (TDD acceptance spec).",
            strict=False,
        )
        marker(function)
        return True
    return None


@pytest.fixture
def app_client():
    app = create_app()
    with TestClient(app) as c:
        yield c
