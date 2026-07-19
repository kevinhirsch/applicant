"""AZ1-3 (#831) — base-resume upload proxy: forward file to the engine.

The engine's ``/api/onboarding/{cid}/base-resume`` endpoint accepts a multipart
file upload.  This handler builds the multipart body, forwards it via urllib,
and returns the normalized envelope — same error-handling pattern as
:mod:`a0_applicant.api.onboarding`.
"""
from __future__ import annotations

import base64
import json
import os
import uuid
import urllib.error
import urllib.request

from helpers.api import ApiHandler
from flask import Request


def _engine() -> str:
    return os.getenv("ENGINE_URL", "http://api:8000").rstrip("/")


def build_multipart_body(file_bytes: bytes, filename: str, field_name: str = "file") -> tuple[bytes, str]:
    """Build multipart/form-data body with a UUID boundary.

    Returns ``(body_bytes, content_type_string)`` — pure function, unit-testable.
    """
    boundary = uuid.uuid4().hex
    preamble = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    body = preamble + file_bytes + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def forward(cid: str, file_bytes: bytes, filename: str, timeout: int = 120) -> dict:
    """POST a multipart base-resume file to the engine; return normalized envelope."""
    body, content_type = build_multipart_body(file_bytes, filename)
    headers = {"Content-Type": content_type}
    req = urllib.request.Request(
        f"{_engine()}/api/onboarding/{cid}/base-resume",
        data=body, headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "{}"
            return {"ok": True, "status": r.status, "data": json.loads(raw) if raw.strip() else {}}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": e.read().decode()[:300]}
    except Exception as e:  # engine down / network — honest surface, no crash
        return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}"}


class BaseResume(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        """Extract file, then forward to engine with a 120 s timeout to accommodate the LLM parse-verify+fallback."""
        cid = str((input or {}).get("campaign_id") or "__system__").strip() or "__system__"

        # Try Flask-style file upload from the request object
        file = request.files.get("file") if hasattr(request, "files") else None
        if file and file.filename:
            file_bytes = file.read()
            filename = file.filename
        else:
            # Fallback: base64-decoded bytes from input
            raw = (input or {}).get("file_bytes")
            if raw:
                file_bytes = base64.b64decode(raw)
                filename = str((input or {}).get("filename", "resume.pdf"))
            else:
                return {"ok": False, "status": 400, "error": "no file provided"}

        return forward(cid, file_bytes, filename, timeout=120)
