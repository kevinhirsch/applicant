"""Real screenshot IMAGES, not just filename labels (dark-engine audit item 28).

``GET /api/admin/screenshots/{application_id}`` (``src/applicant/app/routers/
admin.py``) already listed per-page captures, but only as metadata (id/page_ref/
page_url) -- the workspace Debug modal rendered that as a plain-text label, never
the actual pixels. ``page_ref`` is a ``file://`` ref into the sandbox's local
capture directory (``ApplicationScreenshot`` docstring, FR-LOG-2); there was no
route that could turn that ref into bytes a browser ``<img>`` could load.

This proves the new ``GET /api/admin/screenshots/{application_id}/{screenshot_id}
/image`` route:
  * streams the REAL captured PNG bytes for a ``file://`` ref (not a placeholder),
  * 404s for an unknown screenshot id,
  * 404s for a non-``file://`` ref (e.g. the deterministic ``screenshot://fake``
    ref the in-memory sandbox uses in tests) rather than fabricating bytes, and
  * 404s when the referenced file no longer exists on disk (ephemeral ``/tmp``
    capture dir, reclaimed after a restart).

Hermetic: in-memory storage (unreachable DATABASE_URL), real container services,
LLM gate opened like the peer router tests (test_admin_lessons_route.py).
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.application_screenshot import ApplicationScreenshot
from applicant.core.ids import ApplicationId, ScreenshotId, new_id

_REAL_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n" + b"fake-but-nonempty-capture-bytes-for-tests" * 4
)


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        # Open the LLM gate (the router carries require_llm_configured).
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _registered_paths(app) -> set[str]:
    paths: set[str] = set()
    for r in app.routes:
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for sub in getattr(orig, "routes", []):
                sp = getattr(sub, "path", None)
                if sp:
                    paths.add(sp)
    return paths


def _seed_screenshot(client, page_ref: str, *, application_id: str | None = None) -> tuple[str, str]:
    """Write a real ApplicationScreenshot row via the SAME process-lived storage
    the route reads from (container.storage), so the response is proven to
    reflect real capture state, not a fabricated value."""
    container = client.app.state.container
    app_id = application_id or new_id()
    shot_id = new_id()
    container.storage.screenshots.add(
        ApplicationScreenshot(
            id=ScreenshotId(shot_id),
            application_id=ApplicationId(app_id),
            page_ref=page_ref,
            page_url="https://boards.example.com/apply/1",
        )
    )
    return app_id, shot_id


def test_screenshot_image_route_is_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/admin/screenshots/{application_id}/{screenshot_id}/image" in paths


def test_returns_real_captured_image_bytes(client, tmp_path: pathlib.Path):
    png_path = tmp_path / "capture.png"
    png_path.write_bytes(_REAL_PNG_BYTES)
    app_id, shot_id = _seed_screenshot(client, page_ref=f"file://{png_path}")

    resp = client.get(f"/api/admin/screenshots/{app_id}/{shot_id}/image")

    assert resp.status_code == 200
    assert resp.content == _REAL_PNG_BYTES  # the REAL bytes, not a placeholder image
    assert resp.headers["content-type"] == "image/png"


def test_unknown_screenshot_id_404s(client):
    app_id, _shot_id = _seed_screenshot(client, page_ref="file:///tmp/unused.png")
    resp = client.get(f"/api/admin/screenshots/{app_id}/never-seen-id/image")
    assert resp.status_code == 404


def test_non_file_ref_404s_instead_of_fabricating_bytes(client):
    # The deterministic in-memory sandbox ref used elsewhere in the test suite
    # (adapters/browser/page_source.py's FakePageSource.screenshot) -- proves
    # the route never invents bytes for a ref it can't resolve to a real file.
    app_id, shot_id = _seed_screenshot(client, page_ref="screenshot://fake/0/1")
    resp = client.get(f"/api/admin/screenshots/{app_id}/{shot_id}/image")
    assert resp.status_code == 404


def test_missing_file_on_disk_404s(client, tmp_path: pathlib.Path):
    png_path = tmp_path / "gone.png"
    png_path.write_bytes(_REAL_PNG_BYTES)
    app_id, shot_id = _seed_screenshot(client, page_ref=f"file://{png_path}")
    png_path.unlink()  # simulate the ephemeral capture dir being reclaimed

    resp = client.get(f"/api/admin/screenshots/{app_id}/{shot_id}/image")
    assert resp.status_code == 404


def test_two_applications_screenshots_are_not_cross_readable(client, tmp_path: pathlib.Path):
    png_path = tmp_path / "a.png"
    png_path.write_bytes(_REAL_PNG_BYTES)
    app_a, shot_a = _seed_screenshot(client, page_ref=f"file://{png_path}")
    app_b, _shot_b = _seed_screenshot(client, page_ref=f"file://{png_path}")

    # shot_a belongs to app_a, not app_b -- looking it up under the wrong
    # application id must not resolve.
    resp = client.get(f"/api/admin/screenshots/{app_b}/{shot_a}/image")
    assert resp.status_code == 404
