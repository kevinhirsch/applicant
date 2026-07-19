"""AZ1-3 (#831) — base-resume upload proxy: multipart body builder + forward.

The handler lives in the a0-applicant plugin which imports the A0 framework
(helpers.api, flask), so we stub those imports and load the module via
importlib — same pattern as ``test_az12_onboarding_proxy.py``.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
import types
from pathlib import Path
from unittest.mock import patch

import pytest

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/base_resume.py"


@pytest.fixture(autouse=True)
def _no_cache():
    """xdist-safe: any module-level cache would be cleared here; none yet."""
    pass


@pytest.fixture()
def mod():
    """Load base_resume.py with framework stubs, same pattern as test_az12_onboarding_proxy."""
    api = types.ModuleType("helpers.api")

    class _AH:
        def __init__(self, *a, **k):
            pass

    api.ApiHandler = _AH
    helpers = sys.modules.setdefault("helpers", types.ModuleType("helpers"))
    helpers.api = api
    sys.modules["helpers.api"] = api
    flask = sys.modules.setdefault("flask", types.ModuleType("flask"))
    flask.Request = object

    spec = importlib.util.spec_from_file_location("_az13_br", HANDLER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── build_multipart_body ────────────────────────────────────────────────────


class TestBuildMultipartBody:
    """
    ``build_multipart_body(file_bytes, filename, field_name)`` must return a
    ``(body_bytes, content_type)`` tuple where:
    - ``content_type`` contains the boundary
    - ``body`` starts with ``--<boundary>``
    - ``body`` ends with ``--<boundary>--``
    - ``body`` contains the filename
    """

    def test_contains_boundary_in_content_type(self, mod):
        body, ct = mod.build_multipart_body(b"hello", "resume.pdf")
        assert ct.startswith("multipart/form-data; boundary=")
        boundary = ct.split("boundary=", 1)[1]
        assert len(boundary) == 32  # uuid4 hex
        assert body.startswith(f"--{boundary}".encode())
        assert body.rstrip().endswith(f"--{boundary}--".encode())

    def test_body_includes_filename(self, mod):
        body, _ = mod.build_multipart_body(b"content", "my_cv.pdf")
        assert b'filename="my_cv.pdf"' in body

    def test_body_contains_file_bytes(self, mod):
        payload = b"PDF content here"
        body, _ = mod.build_multipart_body(payload, "doc.pdf")
        assert payload in body

    def test_custom_field_name(self, mod):
        body, ct = mod.build_multipart_body(b"x", "f", field_name="resume")
        assert b'name="resume"' in body


# ── forward ─────────────────────────────────────────────────────────────────


class TestForward:
    """
    ``forward(cid, file_bytes, filename)`` must return the normalized envelope
    ``{ok, status, data|error}`` and never raise.
    """

    def test_success_returns_envelope(self, mod):
        fake_data = {"status": "accepted"}
        fake_resp = FakeResponse(200, json.dumps(fake_data))

        with patch.object(mod, "build_multipart_body", return_value=(b"--boundary--", "multipart/xyz")):
            with patch("urllib.request.urlopen", return_value=fake_resp):
                r = mod.forward("c1", b"pdf-data", "resume.pdf")

        assert r["ok"] is True
        assert r["status"] == 200
        assert r["data"] == fake_data

    def test_http_error(self, mod):
        err = _make_http_error(413, "too large")

        with patch.object(mod, "build_multipart_body", return_value=(b"--boundary--", "multipart/xyz")):
            with patch("urllib.request.urlopen", side_effect=err):
                r = mod.forward("c1", b"x", "big.pdf")

        assert r["ok"] is False
        assert r["status"] == 413
        assert r["error"] is not None

    def test_generic_exception(self, mod):
        with patch.object(mod, "build_multipart_body", return_value=(b"--bnd--", "multipart/xy")):
            with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
                r = mod.forward("c1", b"x", "resume.pdf")

        assert r["ok"] is False
        assert r["status"] == 0
        assert "refused" in r["error"]

    def test_forward_calls_build_multipart_body_with_correct_args(self, mod):
        fake_resp = FakeResponse(200, json.dumps({"status": "ok"}))

        with patch.object(mod, "build_multipart_body") as mock_build:
            mock_build.return_value = (b"--body--", "multipart/xyz")
            with patch("urllib.request.urlopen", return_value=fake_resp):
                mod.forward("c1", b"pdf-bytes", "my_resume.pdf")

        mock_build.assert_called_once_with(b"pdf-bytes", "my_resume.pdf")


# ── helpers for the fake responses ──────────────────────────────────────────


class FakeResponse:
    """Mimics the minimal ``urllib.response.addinfourl`` interface used in the handler."""

    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _make_http_error(code: int, msg: str):
    import io
    return urllib.error.HTTPError(
        url="http://api:8000/api/onboarding/c1/base-resume",
        code=code,
        msg=msg,
        hdrs={},
        fp=io.BytesIO(msg.encode()),
    )
