"""Regression coverage: the discovery-sources router's ``live`` field.

Dark-engine audit item 65 -- with ``DISCOVERY_LIVE=false`` (the default and ALWAYS
the test lane), EVERY discovery source is backed by an offline fake client with the
exact same registry shape as the real thing (``adapters/discovery/factory.py``), and
the offline ``SampleSource`` emits synthetic ``example.test`` rows indistinguishable
in the UI from real discovery. Without a marker, a user cannot tell whether a source
row is real or sample data. The router now derives a per-source ``live: bool`` from
``DISCOVERY_LIVE`` (sample is ALWAYS synthetic, regardless of the flag).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.config import Settings
from applicant.app.main import create_app
from tests.conftest import open_automated_work_gate


def _gated_client(settings: Settings) -> TestClient:
    app = create_app(settings)
    client = TestClient(app)
    client.__enter__()
    open_automated_work_gate(client)
    return client


@pytest.mark.unit
def test_offline_default_marks_every_source_not_live():
    """DISCOVERY_LIVE unset (default False): every source, including the real-board
    keys (jobspy:*, searxng, rss:*), reports ``live: False`` -- they are all backed
    by fake offline clients."""
    client = _gated_client(Settings())
    try:
        res = client.get("/api/discovery-sources/camp-offline-1")
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) > 0
        assert all(item["live"] is False for item in items)
        # The sample source is explicitly present and, unsurprisingly, not live.
        sample = next(i for i in items if i["source_key"] == "sample")
        assert sample["live"] is False
    finally:
        client.__exit__(None, None, None)


@pytest.mark.unit
def test_live_mode_marks_real_boards_live_but_sample_stays_synthetic():
    """DISCOVERY_LIVE=true: every non-sample source flips to ``live: True`` (real
    network clients wired in), but the ``sample`` source stays ``live: False`` --
    it is always the hardcoded example.test filler regardless of the flag
    (adapters/discovery/factory.py: SampleSource is unconditionally included)."""
    client = _gated_client(Settings(DISCOVERY_LIVE=True))
    try:
        res = client.get("/api/discovery-sources/camp-live-1")
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) > 0

        sample = next(i for i in items if i["source_key"] == "sample")
        assert sample["live"] is False

        real_boards = [i for i in items if i["source_key"] != "sample"]
        assert real_boards, "expected at least one non-sample registered source"
        assert all(item["live"] is True for item in real_boards)
    finally:
        client.__exit__(None, None, None)


@pytest.mark.unit
def test_live_field_present_on_toggle_listing_roundtrip():
    """The ``live`` field survives a toggle roundtrip and is independent of
    ``enabled`` -- disabling a source doesn't change whether it's real or sample."""
    client = _gated_client(Settings())
    try:
        listing = client.get("/api/discovery-sources/camp-toggle-1").json()
        key = listing["items"][0]["source_key"]
        before_live = listing["items"][0]["live"]

        client.put(f"/api/discovery-sources/camp-toggle-1/{key}", json={"enabled": False})
        after = client.get("/api/discovery-sources/camp-toggle-1").json()
        toggled = next(i for i in after["items"] if i["source_key"] == key)
        assert toggled["enabled"] is False
        assert toggled["live"] == before_live
    finally:
        client.__exit__(None, None, None)
