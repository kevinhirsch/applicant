"""Real Neko/neko-rooms sandbox integration (FR-SANDBOX-1/2) — integration-gated.

Drives the LocalSandbox with a REAL :class:`NekoRoomsControl` against a running
neko-rooms API. Skipped unless ``NEKO_ROOMS_URL`` points at a reachable server, so
the default lane stays hermetic (no Neko/Docker/network).

To run locally:
    NEKO_ROOMS_URL=http://localhost:8080 NEKO_ROOMS_TOKEN=... \\
        uv run pytest -m integration tests/integration/test_neko_sandbox.py
"""

from __future__ import annotations

import os

import pytest

from applicant.core.ids import ApplicationId, new_id

pytestmark = pytest.mark.integration

_NEKO_URL = os.getenv("NEKO_ROOMS_URL", "")

skip_no_neko = pytest.mark.skipif(
    not _NEKO_URL,
    reason="Set NEKO_ROOMS_URL (+ NEKO_ROOMS_TOKEN) to drive a real neko-rooms server.",
)


@skip_no_neko
def test_real_neko_room_lifecycle():
    from applicant.adapters.sandbox.local_sandbox import LocalSandbox
    from applicant.adapters.sandbox.remote_view import NekoRoomsControl

    control = NekoRoomsControl(_NEKO_URL, os.getenv("NEKO_ROOMS_TOKEN", ""))
    sandbox = LocalSandbox(room_control=control)
    session = sandbox.provision(ApplicationId(new_id()))
    try:
        assert session.remote_view_url  # signed join URL from the real server
    finally:
        sandbox.teardown(session.session_id)  # destroys the ephemeral room
