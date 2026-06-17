"""Ollama model-management routes.

A thin, admin-gated proxy to the Ollama instance Applicant is wired to (the
`ollama` Docker service, host Ollama, or whatever `OLLAMA_BASE_URL` points at).
Lets the UI install / list / remove local models without touching the command
line. Pull progress is streamed back as Server-Sent Events.
"""
from __future__ import annotations

import json
import os

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import StreamingResponse

from core.middleware import require_admin


def _in_docker() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8", errors="ignore") as fh:
            cg = fh.read()
        return any(m in cg for m in ("docker", "containerd", "kubepods"))
    except Exception:
        return False


def _ollama_root() -> str:
    """Native Ollama API root (no trailing /v1) for the configured instance."""
    base = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_URL")
    if not base:
        base = ("http://host.docker.internal:11434/v1"
                if _in_docker() else "http://127.0.0.1:11434/v1")
    base = base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base.rstrip("/")


def setup_ollama_routes():
    router = APIRouter(prefix="/api/ollama", dependencies=[Depends(require_admin)])

    @router.get("/status")
    async def status():
        """Report whether the configured Ollama is reachable."""
        root = _ollama_root()
        try:
            async with httpx.AsyncClient(timeout=4) as c:
                await c.get(f"{root}/api/tags")
            return {"reachable": True, "endpoint": root}
        except Exception:
            return {"reachable": False, "endpoint": root}

    @router.get("/models")
    async def list_models():
        """List models installed on the configured Ollama."""
        root = _ollama_root()
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{root}/api/tags")
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            raise HTTPException(503, f"Ollama not reachable: {e}")
        models = [
            {"name": m.get("name"), "size": m.get("size"),
             "modified": m.get("modified_at")}
            for m in data.get("models", [])
        ]
        return {"endpoint": root, "models": models}

    @router.post("/pull")
    async def pull_model(name: str = Form(...)):
        """Install / update a model, streaming Ollama's pull progress as SSE."""
        name = (name or "").strip()
        if not name:
            raise HTTPException(400, "model name required")
        root = _ollama_root()

        async def gen():
            timeout = httpx.Timeout(15.0, read=None)  # pulls can take many minutes
            try:
                async with httpx.AsyncClient(timeout=timeout) as c:
                    async with c.stream("POST", f"{root}/api/pull",
                                        json={"name": name, "stream": True}) as resp:
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode("utf-8", "ignore")
                            yield f"data: {json.dumps({'error': body or resp.status_code})}\n\n"
                            return
                        async for line in resp.aiter_lines():
                            if line.strip():
                                yield f"data: {line}\n\n"
                yield 'data: {"status": "done"}\n\n'
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @router.delete("/models")
    async def delete_model(name: str):
        """Remove a model from the configured Ollama."""
        name = (name or "").strip()
        if not name:
            raise HTTPException(400, "model name required")
        root = _ollama_root()
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.request("DELETE", f"{root}/api/delete",
                                    json={"name": name})
                r.raise_for_status()
        except Exception as e:
            raise HTTPException(502, f"delete failed: {e}")
        return {"ok": True}

    return router
