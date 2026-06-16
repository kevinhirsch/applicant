"""pytest-bdd configuration for the P0 acceptance scenarios (master spec §10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture
def app_client():
    app = create_app()
    with TestClient(app) as c:
        yield c
