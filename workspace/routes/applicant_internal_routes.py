# routes/applicant_internal_routes.py
"""Stage 2.5 ENGINE -> WORKSPACE callback channel.

Today the Applicant bridge is one-directional: the front-door **workspace UI**
calls *into* the **engine** (``src/applicant_engine.py``, ``ENGINE_URL``). Stage
2.5 needs the *reverse* direction — the engine (the internal ``api`` container)
must be able to call BACK into the workspace ``applicant-ui`` app to read things
that only the front-door app knows: auto-detected interview calendar events
(lane A), deep-research runs (lane B), and Cookbook-served local models (lane C).

This module is the **shared channel + contract** for that reverse direction.
Three later lanes fill in the typed endpoints; this file only provides the
namespaced router (mounted at ``/api/applicant/internal/*``) plus a working
``ping`` and documented placeholders so the contract is concrete.

## Trust model (READ BEFORE EXTENDING)

The boundary is a **shared secret**, not the network alone. Unlike the existing
in-process loopback internal-tool path (``core.middleware.INTERNAL_TOOL_*`` in
``app.py``'s ``AuthMiddleware``), the engine calls the workspace from a *sibling
container on the private docker network*, so it is NOT loopback. This prefix is
therefore honored ONLY when:

1. ``APPLICANT_INTERNAL_TOKEN`` is configured (a strong secret shared by both
   containers via ``docker-compose.prod.yml`` + ``scripts/install.sh``). If it
   is unset, the entire prefix is DISABLED (every call -> 403). No token, no
   channel — there is no "open by default" fallback.
2. The request carries ``X-Applicant-Internal-Token`` matching that secret,
   compared with :func:`secrets.compare_digest` (constant time — no early-exit
   timing leak on the secret).

The gate lives in ``app.py``'s ``AuthMiddleware`` (a small, clearly-commented
branch keyed on this prefix) so an un-tokened request never reaches a handler.
This module ALSO re-checks the token defensively (defense in depth, and so the
router is safe to mount on a bare app in tests / if auth is disabled).

Every honored request is **owner-scoped**: the engine sets ``X-Applicant-Owner``
to the user the work is for, mirroring the impersonation attribution the loopback
internal-tool path already uses. Lanes MUST scope their reads/writes to
:func:`internal_owner` so one user's engine run can never read another user's
calendar / research / models.

## Lane contract (each lane implements its own placeholder below)

| Lane | Endpoint                                   | Returns |
|------|--------------------------------------------|---------|
| A    | ``GET  /api/applicant/internal/calendar/interviews`` | auto-detected interview events for the owner |
| B    | ``POST /api/applicant/internal/research``  | deep-research run for the owner |
| C    | ``GET  /api/applicant/internal/local-models`` | Cookbook-served local models |

See ``workspace/APPLICANT_INTEGRATION.md`` ("Stage 2.5 callback channel") for the
full contract + file-ownership map so the three lanes do not collide.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

#: Header the engine sets to prove it holds the shared secret.
INTERNAL_TOKEN_HEADER = "X-Applicant-Internal-Token"
#: Header the engine sets to attribute the call to a specific workspace user.
INTERNAL_OWNER_HEADER = "X-Applicant-Owner"
#: Route prefix for the whole reverse channel. The AuthMiddleware branch in
#: app.py keys on this so an un-tokened request never reaches a handler.
INTERNAL_PREFIX = "/api/applicant/internal"


def internal_token() -> str:
    """The configured shared secret, or "" when the channel is DISABLED.

    Read live (not import-time) so tests can set/clear it via monkeypatch and so
    a deploy that injects the env after import still works.
    """
    return (os.environ.get("APPLICANT_INTERNAL_TOKEN") or "").strip()


def internal_channel_enabled() -> bool:
    """True only when a non-empty shared secret is configured."""
    return bool(internal_token())


def verify_internal_token(request: Request) -> None:
    """Defense-in-depth gate re-checked inside every handler.

    Raises 403 when the channel is disabled (no secret) or the presented
    ``X-Applicant-Internal-Token`` does not match (constant-time). The
    AuthMiddleware branch in app.py performs the same check earlier; this keeps
    handlers safe when mounted on a bare app (tests) or with auth disabled.
    """
    secret = internal_token()
    if not secret:
        # Channel disabled: never reveal whether a token would have matched.
        raise HTTPException(status_code=403, detail="Internal channel disabled")
    presented = request.headers.get(INTERNAL_TOKEN_HEADER) or ""
    if not secrets.compare_digest(presented, secret):
        raise HTTPException(status_code=403, detail="Invalid internal token")


def internal_owner(request: Request) -> str:
    """The owner the engine attributed this call to (``X-Applicant-Owner``).

    May be "" when the engine did not attribute the call (single-user / system
    work). Lanes MUST use this to scope their reads/writes — never trust an owner
    embedded in the body.
    """
    return (request.headers.get(INTERNAL_OWNER_HEADER) or "").strip()


# --- Lane C (Cookbook) helpers -------------------------------------------------
#: Default serve port when a serve command does not pass ``--port`` (mirrors the
#: Cookbook UI's serve-port allocator in ``static/js/cookbookRunning.js``).
_COOKBOOK_DEFAULT_SERVE_PORT = 8000
#: Serve task statuses that mean an OpenAI-compatible endpoint is (coming) up and
#: worth advertising to the engine. ``running`` covers a server that is warming
#: up; ``ready`` is the explicit "Application startup complete" phase.
_COOKBOOK_LIVE_STATUSES = ("ready", "running")
_SERVE_PORT_RE = re.compile(r"--port\s+(\d+)")


def _cookbook_state_path() -> Path:
    """Path to the persisted Cookbook state (matches ``cookbook_routes.py``)."""
    return Path(os.environ.get("DATA_DIR", "data")) / "cookbook_state.json"


def _load_cookbook_state(path: Path | None = None) -> dict[str, Any]:
    """Read the Cookbook state JSON, or ``{}`` when missing/unreadable.

    Never raises: a missing or corrupt state file simply means "nothing served".
    """
    state_path = path or _cookbook_state_path()
    try:
        if not state_path.exists():
            return {}
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # pragma: no cover - defensive; corrupt file -> empty
        logger.warning("cookbook_state_unreadable", exc_info=True)
        return {}


def _serve_base_url(cmd: str, remote_host: str) -> str:
    """Derive the in-network OpenAI-compatible base URL for a serve task.

    The serve ``cmd`` carries ``--port N`` (default 8000). The host is the
    serve target: a remote SSH alias/host when set, else ``localhost`` (the
    Cookbook server itself). This mirrors ``cookbook_routes`` image-endpoint
    auto-registration (``http://<host>:<port>/v1``). The engine rewrites a
    ``localhost`` host to a network-reachable address on its side.
    """
    match = _SERVE_PORT_RE.search(cmd or "")
    port = int(match.group(1)) if match else _COOKBOOK_DEFAULT_SERVE_PORT
    host = (remote_host or "").strip()
    if host:
        # SSH alias form "user@host" -> bare host (Tailscale/DNS resolves it).
        host = host.split("@")[-1]
    else:
        host = "localhost"
    return f"http://{host}:{port}/v1"


def _cookbook_served_models(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the currently Cookbook-served local LLM endpoints.

    Returns a clean JSON list of ``{model_id, name, base_url, status, remote,
    served_by}`` — one per live serve task that exposes an OpenAI-compatible
    endpoint. Diffusion (image) serves are skipped (the engine LLM config wants
    text endpoints; image serves auto-register on the workspace side already).
    Empty list when nothing is served.
    """
    tasks = state.get("tasks") if isinstance(state, dict) else None
    if isinstance(tasks, dict):
        tasks = list(tasks.values())
    if not isinstance(tasks, list):
        return []

    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("type") != "serve":
            continue
        status = (task.get("status") or "").strip().lower()
        if status not in _COOKBOOK_LIVE_STATUSES:
            continue
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        cmd = payload.get("_cmd") or payload.get("cmd") or ""
        # Image (diffusion) serves are not OpenAI chat endpoints — skip them.
        if "diffusion_server.py" in cmd:
            continue
        model_id = (
            task.get("modelId")
            or task.get("repoId")
            or task.get("name")
            or payload.get("repo_id")
            or payload.get("modelId")
            or ""
        )
        if not model_id:
            continue
        remote = (task.get("remoteHost") or "").strip()
        base_url = _serve_base_url(cmd, remote)
        if base_url in seen_urls:
            continue
        seen_urls.add(base_url)
        short = model_id.split("/")[-1] if "/" in model_id else model_id
        out.append(
            {
                "model_id": model_id,
                "name": short,
                "base_url": base_url,
                "status": status,
                "remote": remote or "local",
                "served_by": "cookbook",
            }
        )
    return out


def setup_applicant_internal_routes() -> APIRouter:
    router = APIRouter(prefix=INTERNAL_PREFIX, tags=["applicant-internal"])

    @router.get("/ping")
    async def ping(request: Request) -> dict:
        """Liveness + auth probe for the engine's WorkspacePort.

        Working now: the engine calls this from ``HttpWorkspaceClient.ping()`` to
        learn the channel is reachable AND the shared secret matches. Returns the
        attributed owner so the engine can confirm impersonation wiring.
        """
        verify_internal_token(request)
        return {"ok": True, "owner": internal_owner(request) or None}

    # --- Lane placeholders (501 until the owning lane implements them) -------
    # Each lane REPLACES its own stub here (this file is the shared channel) OR,
    # preferably, mounts its own router under the same prefix and registers it in
    # app.py. Keep the path + auth contract identical to what is documented.

    @router.get("/calendar/interviews")
    async def calendar_interviews(request: Request):
        """LANE A placeholder — auto-detected interview calendar events.

        Contract: owner-scoped (``internal_owner``) list of interview events the
        workspace auto-detected from the owner's calendar, shaped as
        ``{"interviews": [...]}``. 501 until lane A lands.
        """
        verify_internal_token(request)
        raise HTTPException(status_code=501, detail="calendar/interviews not implemented (lane A)")

    @router.post("/research")
    async def research(request: Request):
        """LANE B placeholder — run deep research for the owner.

        Contract: owner-scoped; body ``{"query": str, ...}`` -> a research run /
        report handle. 501 until lane B lands.
        """
        verify_internal_token(request)
        raise HTTPException(status_code=501, detail="research not implemented (lane B)")

    @router.get("/local-models")
    async def local_models(request: Request):
        """LANE C — list Cookbook-served local model endpoints (owner-scoped).

        Returns ``{"owner": <str|null>, "models": [...]}`` where each model is a
        currently Cookbook-served OpenAI-compatible endpoint:
        ``{model_id, name, base_url, status, remote, served_by}``. The base URL is
        in-network (``http://<host>:<port>/v1``); the engine rewrites a
        ``localhost`` host to a network-reachable address on its side.

        Empty list when nothing is served (or the Cookbook state is absent). The
        Cookbook is an owner/admin surface, so the served set is the deployment's;
        the attributed owner is echoed back for the engine to confirm scoping.
        """
        verify_internal_token(request)
        owner = internal_owner(request)
        models = _cookbook_served_models(_load_cookbook_state())
        return {"owner": owner or None, "models": models}

    return router
