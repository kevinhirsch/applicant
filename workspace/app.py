# app.py — slim orchestrator
import os

# Windows: force HuggingFace/fastembed to COPY model files instead of symlinking.
# On a network-share/UNC data dir Windows can't follow HF's symlinks ([WinError
# 1463]), so the ONNX embedding model fails to load. huggingface_hub reads this
# at import time, so set it before anything pulls it in. (Mirrored in
# src/embeddings.py for non-server entrypoints.)
if os.name == "nt":
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from dotenv import load_dotenv
# encoding="utf-8-sig" tolerates a UTF-8 BOM in .env — a common Windows gotcha
# when the file is saved from Notepad. Without this, the first key parses as
# "﻿AUTH_ENABLED" instead of "AUTH_ENABLED", so AUTH_ENABLED=false (etc.)
# is silently ignored and the user is unexpectedly forced to log in (issue #142).
# utf-8-sig reads plain UTF-8 (no BOM) identically, so this is safe everywhere.
load_dotenv(encoding="utf-8-sig")
import uuid

import asyncio
import logging
import secrets
from datetime import datetime
from typing import Dict

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

# Core imports
from core.constants import (
    BASE_DIR, STATIC_DIR, SESSIONS_FILE,
    REQUEST_TIMEOUT, OPENAI_API_KEY,
)
from core.database import SessionLocal, ApiToken
from core.middleware import SecurityHeadersMiddleware
from core.auth import AuthManager
from core.exceptions import (
    SessionNotFoundError, InvalidFileUploadError,
    LLMServiceError, WebSearchError,
)

import bcrypt as _bcrypt

from src.app_helpers import abs_join
from starlette.responses import RedirectResponse

# ========= LOGGING =========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# ========= APP =========
app = FastAPI(
    title="AI Chat Application",
    description="Comprehensive AI chat with memory, research, and multi-modal capabilities",
    version="1.0.0",
)

# ========= CORS =========
def parse_allowed_origins(raw: str | None = None) -> list[str]:
    """Parse ALLOWED_ORIGINS env var with whitespace stripping, empty-entry
    filtering, and basic URL validation. Trailing slashes are normalised away
    so ``https://example.com/`` and ``https://example.com`` are treated as
    equivalent.

    Returns a list of well-formed origin strings suitable for
    ``CORSMiddleware(allow_origins=...)``.
    """
    from urllib.parse import urlparse

    if raw is None:
        raw = os.getenv("ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1")
    origins: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        # Normalise trailing slash
        part = part.rstrip("/")
        # Basic URL validation: must have a scheme and netloc
        parsed = urlparse(part)
        if not parsed.scheme or not parsed.netloc:
            # Accept bare hostnames like "localhost" or "127.0.0.1" by
            # prepending "http://" for validation
            test = urlparse("http://" + part)
            if not test.netloc:
                continue
        origins.append(part)
    return origins


allowed_origins = parse_allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=[
        "Accept",
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "X-Auth-Token",
        "X-Applicant-Internal-Token",
        "X-Applicant-Owner",
        "X-Requested-With",
        "X-TZ-Offset",
    ],
)

# ========= SECURITY HEADERS MIDDLEWARE =========
app.add_middleware(SecurityHeadersMiddleware)


# ========= REQUEST TIMEOUT (FALLBACK FOR HUNG HANDLERS) =========
# If a single request takes longer than REQUEST_HARD_TIMEOUT, abort it and
# return 504 instead of holding the event loop hostage. Whitelisted paths
# (streaming, long-running shell exec, research) are exempt because they
# legitimately stay open. Without this, a single hung subprocess.run or
# missing-timeout httpx call locks up the entire server for everyone.
import asyncio as _asyncio
from starlette.middleware.base import BaseHTTPMiddleware as _BaseHTTPMiddleware
from starlette.responses import JSONResponse as _JSONResponse

REQUEST_HARD_TIMEOUT = float(os.getenv("REQUEST_HARD_TIMEOUT", "45"))
_TIMEOUT_EXEMPT_PREFIXES = (
    "/api/chat",            # streaming
    "/api/shell/stream",    # SSE
    "/api/research",        # multi-minute jobs
    "/api/applicant/research",  # manual deep-research trigger (engine-backed; can be multi-minute)
    "/api/applicant/internal/research",  # engine deep-research callback (multi-minute; must not be killed)
    "/api/model/download",  # tmux setup may run pip installs
    "/api/model/probe",     # SSE; iterates models with up to 8s timeout each
    "/api/model-endpoints", # /probe sub-route also iterates models
    "/api/cookbook/setup",  # remote pacman/apt installs
    "/api/upload",          # large files
    "/api/image",           # diffusion proxies (inpaint/harmonize/upscale/etc.) — own 120s httpx timeout
)


class _RequestTimeoutMiddleware(_BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path or ""
        if any(path.startswith(p) for p in _TIMEOUT_EXEMPT_PREFIXES):
            return await call_next(request)
        try:
            return await _asyncio.wait_for(call_next(request), timeout=REQUEST_HARD_TIMEOUT)
        except _asyncio.TimeoutError:
            return _JSONResponse(
                {"detail": f"Request exceeded {REQUEST_HARD_TIMEOUT:.0f}s timeout"},
                status_code=504,
            )


app.add_middleware(_RequestTimeoutMiddleware)

# ========= AUTH =========
from routes.auth_routes import setup_auth_routes, SESSION_COOKIE

auth_manager = AuthManager()
app.state.auth_manager = auth_manager
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() != "false"
LOCALHOST_BYPASS = os.getenv("LOCALHOST_BYPASS", "false").lower() == "true"
if LOCALHOST_BYPASS:
    logger.warning("LOCALHOST_BYPASS is enabled, loopback requests bypass authentication. Do not expose this instance to a network.")

if AUTH_ENABLED:
    AUTH_EXEMPT_EXACT = {
        "/api/auth/setup",
        "/api/auth/signup",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/status",
        "/api/auth/features",
        # /api/applicant/features intentionally NOT exempt: its handler calls
        # require_user(), so exempting it left current_user unset and it 401d for
        # every browser session; the app-shell redirects to /login on any 401,
        # which aborted the whole boot. Authenticate it like sibling proxy routes.
        "/api/auth/settings",
        "/api/auth/integrations/presets",
        "/api/health",
        "/api/version",
        "/login",
    }
    AUTH_EXEMPT_PREFIXES = ["/static"]

    def _is_auth_exempt(path: str) -> bool:
        return path in AUTH_EXEMPT_EXACT or any(path.startswith(p) for p in AUTH_EXEMPT_PREFIXES)

    # In-memory token cache: prefix → list[(token_id, token_hash, owner, scopes)]. The DB
    # query was running on every API-bearer request and scanning bcrypt
    # checks linearly. With this cache, we hit the DB only when the cache
    # version bumps (token created/revoked) — see _token_cache_invalidate
    # in app.state, called by routes/api_token_routes.
    _token_cache: dict = {}
    _token_cache_lock = _asyncio.Lock()
    _token_cache_dirty = True

    def _token_cache_invalidate():
        nonlocal_dict = app.state.__dict__
        nonlocal_dict["_token_cache_dirty"] = True
    app.state.invalidate_token_cache = _token_cache_invalidate
    app.state._token_cache = _token_cache
    app.state._token_cache_dirty = True

    def _refresh_token_cache():
        """Rebuild the prefix→[(id,hash)] map from the DB."""
        from collections import defaultdict
        new_map = defaultdict(list)
        db = SessionLocal()
        try:
            rows = db.query(ApiToken).filter(ApiToken.is_active == True).all()
            for r in rows:
                scopes = [s.strip() for s in (getattr(r, "scopes", "") or "chat").split(",") if s.strip()]
                new_map[r.token_prefix].append((r.id, r.token_hash, getattr(r, "owner", None), scopes))
        finally:
            db.close()
        _token_cache.clear()
        _token_cache.update(new_map)
        app.state._token_cache_dirty = False

    # Headers that prove a request was forwarded by a proxy/tunnel (cloudflared,
    # nginx, Caddy, Tailscale Funnel, …). cloudflared connects to the app FROM
    # 127.0.0.1, so without this check every tunneled request would look like
    # loopback and could bypass auth.
    _PROXY_FWD_HEADERS = (
        "cf-connecting-ip", "cf-ray", "cf-visitor",
        "x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded",
    )

    def _is_trusted_loopback(request: Request) -> bool:
        """True ONLY for a DIRECT loopback connection with no proxy/tunnel
        forwarding headers. A bare ``client.host in ('127.0.0.1','::1')`` check is
        unsafe behind a Cloudflare tunnel / reverse proxy: those connect from
        loopback, so a remote visitor would otherwise inherit local trust and
        slip past LOCALHOST_BYPASS or spoof the internal-tool path. Applicant's own
        in-process agent loopback calls carry none of these headers, so they still
        qualify."""
        host = request.client.host if request.client else None
        if host not in ("127.0.0.1", "::1"):
            return False
        for _h in _PROXY_FWD_HEADERS:
            if request.headers.get(_h):
                return False
        return True

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if _is_auth_exempt(path):
                return await call_next(request)
            # In-process internal-tool token bypass. Used by the agent
            # tool layer when it HTTP-loopbacks to admin-gated routes
            # (no admin cookie available in that context). Restricted to
            # loopback clients + matching token to keep it locked down.
            try:
                from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN as _ITT
                _hdr = request.headers.get(INTERNAL_TOOL_HEADER)
                if _hdr and secrets.compare_digest(_hdr, _ITT) and _is_trusted_loopback(request):
                    # Impersonation: when the agent's loopback call sets
                    # X-Applicant-Owner, attribute the request to that user only if
                    # auth is configured (user store is initialised) AND the user
                    # is a known registered user. Requiring auth.is_configured means
                    # impersonation is only honoured when the workspace has a properly
                    # set-up identity store — it cannot silently activate on an
                    # unconfigured deployment. The caller is already verified as an
                    # authorized in-process agent via INTERNAL_TOOL_TOKEN + loopback.
                    _impersonate = (request.headers.get("X-Applicant-Owner") or "").strip()
                    _auth_mgr = getattr(request.app.state, "auth_manager", None) or auth_manager
                    # Defense-in-depth (#267): gate impersonation through the auth
                    # layer rather than a mere user-existence check inlined here.
                    from src.auth_helpers import require_admin_for_impersonation
                    _can_impersonate = require_admin_for_impersonation(_auth_mgr, _impersonate)
                    if _can_impersonate:
                        request.state.current_user = _impersonate
                    else:
                        request.state.current_user = "internal-tool"
                    request.state.api_token = False
                    return await call_next(request)
            except Exception:
                pass
            # Stage 2.5 engine->workspace callback channel. The engine (the
            # internal ``api`` container) calls BACK into this app over the
            # private docker network — so, UNLIKE the loopback internal-tool path
            # above, these requests are NOT loopback and must NOT require it. They
            # are honored ONLY when (a) APPLICANT_INTERNAL_TOKEN is configured (a
            # strong shared secret) and (b) X-Applicant-Internal-Token matches it
            # (constant-time). No token configured => the prefix is DISABLED (the
            # branch is skipped, so the request falls through to normal auth and
            # is rejected). This does NOT touch the loopback path or any other
            # auth. See routes/applicant_internal_routes.py for the contract.
            if path.startswith("/api/applicant/internal/"):
                _int_secret = (os.environ.get("APPLICANT_INTERNAL_TOKEN") or "").strip()
                _int_hdr = request.headers.get("X-Applicant-Internal-Token") or ""
                if _int_secret and secrets.compare_digest(_int_hdr, _int_secret):
                    # Owner attribution only (authorization stays in the routes):
                    # scope the engine's call to the user it set in X-Applicant-Owner.
                    # The token proves the CALLER is the engine; it does NOT say whose
                    # data the call is for. So an unattributed/unknown owner must NOT be
                    # promoted to the all-owner "internal-engine" principal (#230) — it
                    # is stamped as an unprivileged sentinel that owner-scoped data
                    # routes (require_internal_owner) reject. Only a real, known owner
                    # becomes the scoped current_user.
                    _owner = (request.headers.get("X-Applicant-Owner") or "").strip()
                    _auth_mgr = getattr(request.app.state, "auth_manager", None) or auth_manager
                    from src.app_helpers import require_owner_attribution
                    try:
                        request.state.current_user = require_owner_attribution(
                            _owner, getattr(_auth_mgr, "users", {})
                        )
                    except ValueError:
                        # Unattributed callback: refuse all-owner access. Keep the
                        # request alive for non-data system endpoints, but stamp a
                        # sentinel with no data scope so require_internal_owner 400s.
                        request.state.current_user = "internal-engine"
                    request.state.api_token = False
                    return await call_next(request)
                # Token missing/mismatch: do NOT short-circuit — fall through to
                # the normal auth chain below, which rejects the request.
            # Allow DIRECT localhost requests (internal service calls from
            # heartbeats etc.). Tunnel/proxy-forwarded requests are excluded by
            # _is_trusted_loopback so LOCALHOST_BYPASS can't be abused over a
            # Cloudflare tunnel / reverse proxy. Keep LOCALHOST_BYPASS=false for
            # network-exposed deployments regardless.
            if LOCALHOST_BYPASS and _is_trusted_loopback(request):
                return await call_next(request)
            if not auth_manager.is_configured:
                # No users yet — redirect to login for first-time setup
                if not path.startswith("/api/"):
                    return RedirectResponse(url="/login", status_code=302)
                return JSONResponse(status_code=401, content={"error": "Setup required"})

            # --- Bearer token auth (API tokens for external integrations) ---
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer ody_"):
                raw_token = auth_header[7:]
                # Sanity check: tokens are "ody_" + 43 chars of base64
                if len(raw_token) < 12 or len(raw_token) > 100:
                    return JSONResponse(status_code=401, content={"error": "Invalid API token"})
                prefix = raw_token[:8]
                try:
                    if app.state._token_cache_dirty:
                        async with _token_cache_lock:
                            if app.state._token_cache_dirty:
                                await _asyncio.to_thread(_refresh_token_cache)
                    candidates = list(_token_cache.get(prefix, ()))
                    matched_id = None
                    matched_owner = None
                    matched_scopes = []
                    for tid, thash, owner, scopes in candidates:
                        if _bcrypt.checkpw(raw_token.encode(), thash.encode()):
                            matched_id = tid
                            matched_owner = owner
                            matched_scopes = scopes or []
                            break
                    if matched_id:
                        # Update last_used_at off the hot path. Doing it
                        # inline used to keep the request open across an
                        # extra commit; do it fire-and-forget instead.
                        async def _touch_last_used(tid: str):
                            def _do():
                                _db = SessionLocal()
                                try:
                                    _db.query(ApiToken).filter(ApiToken.id == tid).update(
                                        {"last_used_at": datetime.utcnow()}
                                    )
                                    _db.commit()
                                finally:
                                    _db.close()
                            try:
                                await _asyncio.to_thread(_do)
                            except Exception:
                                pass
                        _asyncio.create_task(_touch_last_used(matched_id))
                        # Keep bearer-token callers out of normal cookie/user
                        # routes. API-aware routes can read api_token_owner.
                        request.state.current_user = "api"
                        request.state.api_token = True
                        request.state.api_token_id = matched_id
                        request.state.api_token_owner = matched_owner
                        request.state.api_token_scopes = matched_scopes
                        return await call_next(request)
                except Exception:
                    logger.warning("API token auth error", exc_info=False)
                # Invalid bearer token — reject immediately
                return JSONResponse(status_code=401, content={"error": "Invalid API token"})

            # --- Cookie-based session auth ---
            token = request.cookies.get(SESSION_COOKIE)
            if not auth_manager.validate_token(token):
                if path.startswith("/api/"):
                    return JSONResponse(status_code=401, content={"error": "Not authenticated"})
                return RedirectResponse(url="/login", status_code=302)

            # Attach current username to request state for downstream routes
            request.state.current_user = auth_manager.get_username_for_token(token)
            request.state.api_token = False
            return await call_next(request)

    app.add_middleware(AuthMiddleware)
    logger.info("Auth middleware enabled (AUTH_ENABLED=true)")
else:
    logger.info("Auth middleware disabled (set AUTH_ENABLED=true to enable)")

# ========= RESPONSE COMPRESSION =========
# Added LAST (after CORS/SecurityHeaders/RequestTimeout/Auth above) so it is the
# OUTERMOST middleware layer: Starlette wraps each `add_middleware` call around
# everything registered before it, so the most-recently-added middleware sees
# the request first and the response last. GZip needs to be that outermost
# wrapper so it compresses the FINAL response body every inner layer produced
# (including whatever headers/body Auth or SecurityHeaders assembled), not an
# intermediate one. Cuts wire size ~5-8x for the uncompressed text this app
# ships today: 1.24 MB style.css, 232 KB index.html, ~5.9 MB of JS modules, and
# every polled proxy JSON payload (perf lens finding #1).
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ========= STATIC FILES =========
os.makedirs(STATIC_DIR, exist_ok=True)


class _RevalidatingStatic(StaticFiles):
    """Serve static assets normally, with a Cache-Control policy tuned per
    file type so a no-build/no-versioned-URL app still avoids stale code
    without paying a conditional-GET round-trip on every single load.

    - `.js`/`.css`: `max-age=60`. Perf audit (round-3 lens #12) — blanket
      `no-cache` forced ~162 modules + the stylesheet each through a
      conditional-GET RTT on EVERY navigation; Starlette/browsers do turn
      that into a cheap 304 (ETag/Last-Modified preserved), but the RTT
      itself, times ~162, is the storm being collapsed here. A short
      `max-age=60` lets the browser skip revalidation entirely for a code
      change that's at most a minute old — acceptable staleness during dev
      iteration (`workspace/app.py` re-reads `.js/.css/.html` from disk per
      request; this only changes how long the BROWSER waits before asking
      again, not whether the server serves fresh bytes when asked) — while
      still self-healing within 60s of a real deploy, no manual hard-refresh
      needed. `static/sw.js` is network-first for `.js`/`.css`
      (`CACHE_NAME` precache + the `fetch` handler's network-first branch):
      its `fetch()` calls still go through the browser's own HTTP cache, so
      a `max-age=60` hit resolves those "network-first" fetches with ZERO
      round-trip while still fresh, and only reverts to a real
      conditional-GET after 60s — the SW strategy and this policy compose
      rather than conflict.
    - `.html`: kept on `no-cache` (unconditional revalidation) — the app
      shell should never be stale for more than one reload, so it keeps
      paying the conditional-GET RTT it always has; unchanged bytes still
      return a cheap 304 (ETag/Last-Modified preserved).

    Starlette's `FileResponse` fixes `Content-Length` from a `stat()` taken
    up front, then streams the file body in 64KB chunks over the life of the
    response. A file rewritten in place (e.g. a deploy overwriting a `.js`/
    `.css`/`.html` asset while a request is mid-flight) can change size
    between that `stat()` and a later chunk read, so the client can be
    handed a body shorter than the promised `Content-Length` — a truncated,
    partial response. Buffering the whole file into memory in one read below
    means the `Content-Length` we send always matches the exact bytes we
    send, from a single point-in-time snapshot of the file — no window for a
    concurrent rewrite to produce a partial body.
    """

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if path.endswith((".js", ".css")):
            resp.headers["Cache-Control"] = "max-age=60"
        elif path.endswith(".html"):
            resp.headers["Cache-Control"] = "no-cache"
        if isinstance(resp, FileResponse) and resp.status_code == 200:
            import anyio
            from pathlib import Path as _Path
            try:
                body = await anyio.to_thread.run_sync(_Path(resp.path).read_bytes)
            except OSError:
                return resp
            headers = dict(resp.headers)
            headers["content-length"] = str(len(body))
            resp = Response(
                content=body,
                status_code=resp.status_code,
                headers=headers,
                media_type=resp.media_type,
                background=resp.background,
            )
        return resp


app.mount("/static", _RevalidatingStatic(directory="static"), name="static")

# ========= GENERATED IMAGES =========
@app.get("/api/generated-image/{filename}")
async def serve_generated_image(filename: str, request: Request):
    """Serve generated images from the data directory."""
    from pathlib import Path
    import re
    if not re.match(r'^[a-f0-9]{8,64}\.(png|jpg|jpeg|webp|gif|mp4|mov|webm|mkv|m4v)$', filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    img_path = Path("data/generated_images") / filename
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    # SECURITY: filename is the only key, so anyone who knows / guesses a
    # 12-hex content hash could pull another user's image bytes. Require
    # auth and verify ownership via the gallery row (when one exists).
    try:
        from src.auth_helpers import get_current_user
        from core.database import SessionLocal as _SL, GalleryImage as _GI
        _user = get_current_user(request)
        if _user:
            _db = _SL()
            try:
                _row = _db.query(_GI).filter(_GI.filename == filename).first()
                # Generated-but-not-yet-imported images have no row → allow.
                # Row exists with a different owner → 404 (don't confirm existence).
                if _row is not None and _row.owner and _row.owner != _user:
                    raise HTTPException(status_code=404, detail="Image not found")
            finally:
                _db.close()
    except HTTPException:
        raise
    except Exception:
        pass
    ext = filename.rsplit('.', 1)[-1].lower()
    mime = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "gif": "image/gif",
        "mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
        "mkv": "video/x-matroska", "m4v": "video/mp4",
    }.get(ext, "application/octet-stream")
    # Generated-image filenames are content hashes → the bytes for a given
    # filename never change. Cache them hard so the gallery doesn't
    # re-download every full-size image each time it's opened. `immutable`
    # tells the browser it never needs to revalidate within the max-age.
    return FileResponse(
        str(img_path),
        media_type=mime,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )

# ========= YOUTUBE INIT =========
from services.youtube import init_youtube
init_youtube()

# ========= RAG (vector document RAG) =========
# VectorRAG (ChromaDB-backed personal-document semantic search). Initialized
# lazily via get_rag_manager() — returns None if ChromaDB isn't reachable
# (no server running on the configured host:port), in which case personal-doc
# routes return a clean 503 instead of busy-retrying every request.
#
# Note: this was previously hardcoded off because chromadb 1.4.1 / pydantic
# 2.12 were mutually incompatible at the time. With the current pins
# (chromadb 1.5.x + pydantic 2.13.x) the init works and Personal Docs
# (POST /api/personal/add_directory etc.) is functional again.
from src.rag_singleton import get_rag_manager
rag_manager = get_rag_manager()
rag_available = rag_manager is not None
if rag_available:
    logger.info("Vector document RAG initialized")
else:
    logger.info(
        "Vector document RAG not available at startup "
        "(ChromaDB may not be reachable yet — routes will retry lazily)"
    )

# ========= IMPORT CONFIG =========
from src.config import config

# ========= COMPONENT INITIALIZATION =========
from src.app_initializer import initialize_managers

components = initialize_managers(BASE_DIR, rag_manager)

session_manager   = components["session_manager"]
from src.assistant_log import set_session_manager as _set_asst_sm
_set_asst_sm(session_manager)
memory_manager    = components["memory_manager"]
memory_vector     = components.get("memory_vector")
upload_handler    = components["upload_handler"]
personal_docs_mgr = components["personal_docs_manager"]
api_key_manager   = components["api_key_manager"]
preset_manager    = components["preset_manager"]
chat_processor    = components["chat_processor"]
research_handler  = components["research_handler"]
chat_handler      = components["chat_handler"]
model_discovery   = components["model_discovery"]
skills_manager    = components["skills_manager"]

# TTS
from services.tts import get_tts_service

tts_service = get_tts_service()
logger.info("TTS service initialized (provider managed via admin settings)")

# ========= EXCEPTION HANDLERS =========
@app.exception_handler(SessionNotFoundError)
async def session_not_found_handler(request: Request, exc: SessionNotFoundError):
    return JSONResponse(status_code=404, content={"error": "SESSION_NOT_FOUND", "message": str(exc)})

@app.exception_handler(InvalidFileUploadError)
async def invalid_file_upload_handler(request: Request, exc: InvalidFileUploadError):
    return JSONResponse(status_code=400, content={"error": "INVALID_FILE_UPLOAD", "message": str(exc)})

@app.exception_handler(LLMServiceError)
async def llm_service_error_handler(request: Request, exc: LLMServiceError):
    return JSONResponse(status_code=502, content={"error": "LLM_SERVICE_ERROR", "message": str(exc)})

@app.exception_handler(WebSearchError)
async def web_search_error_handler(request: Request, exc: WebSearchError):
    return JSONResponse(status_code=502, content={"error": "WEB_SEARCH_ERROR", "message": str(exc)})

# Global catch-all: any unhandled exception that bypasses the specific handlers
# above is caught here. Logs full context server-side (path, method,
# x-request-id / x-correlation-id if present, exception type + traceback) so
# crashes are always diagnosable, and returns a generic 500 to the client so
# no internal detail or traceback is ever leaked to untrusted callers (#252).
import traceback as _traceback

@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
    )
    logger.error(
        "unhandled_exception path=%s method=%s request_id=%s exc_type=%s\n%s",
        request.url.path,
        request.method,
        request_id,
        type(exc).__name__,
        _traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again later."},
    )

# ========= WEBHOOK MANAGER =========
from src.webhook_manager import WebhookManager

webhook_manager = WebhookManager(api_key_manager=api_key_manager)

# ========= INCLUDE ROUTERS =========

# Auth
auth_router = setup_auth_routes(auth_manager)
app.include_router(auth_router)

# Uploads
from routes.upload_routes import setup_upload_routes
upload_router, upload_cleanup_func = setup_upload_routes(upload_handler)
app.include_router(upload_router)
upload_cleanup_task = None

# Emoji SVG proxy (same-origin, lazy-cached Twemoji) — lets the chat render
# emojis as flat SVG instead of system color glyphs.
from routes.emoji_routes import setup_emoji_routes
app.include_router(setup_emoji_routes())

# Sessions
from routes.session_routes import setup_session_routes
session_config = {"REQUEST_TIMEOUT": REQUEST_TIMEOUT, "OPENAI_API_KEY": OPENAI_API_KEY, "SESSIONS_FILE": SESSIONS_FILE}
app.include_router(setup_session_routes(session_manager, session_config, webhook_manager=webhook_manager))

# Admin Danger Zone wipes (Settings → System → Danger Zone)
from routes.admin_wipe_routes import setup_admin_wipe_routes
app.include_router(setup_admin_wipe_routes(session_manager))

# Memory
from routes.memory_routes import setup_memory_routes
app.include_router(setup_memory_routes(memory_manager, session_manager, memory_vector=memory_vector))
from routes.entity_routes import setup_entity_routes
app.include_router(setup_entity_routes())
from routes.skills_routes import setup_skills_routes
app.include_router(setup_skills_routes(skills_manager))

# Chat
from routes.chat_routes import setup_chat_routes
app.include_router(setup_chat_routes(
    session_manager, chat_handler, chat_processor,
    memory_manager, research_handler, upload_handler,
    memory_vector=memory_vector,
    webhook_manager=webhook_manager,
    skills_manager=skills_manager,
))

# Research (background deep-research tasks)
from routes.research_routes import setup_research_routes
app.include_router(setup_research_routes(research_handler, session_manager=session_manager))

# History
from routes.history_routes import setup_history_routes
app.include_router(setup_history_routes(session_manager))

# Search
from routes.search_routes import setup_search_routes
app.include_router(setup_search_routes(config))

# Presets
from routes.preset_routes import setup_preset_routes
app.include_router(setup_preset_routes(preset_manager))

# Diagnostics
from routes.diagnostics_routes import setup_diagnostics_routes
app.include_router(setup_diagnostics_routes(rag_manager, rag_available, research_handler))

# Cleanup
from routes.cleanup_routes import setup_cleanup_routes
app.include_router(setup_cleanup_routes(session_manager))

# Personal docs
from routes.personal_routes import setup_personal_routes
app.include_router(setup_personal_routes(personal_docs_mgr, rag_manager, rag_available))

# Embedding model management
from routes.embedding_routes import setup_embedding_routes
app.include_router(setup_embedding_routes())

# Models
from routes.model_routes import setup_model_routes
app.include_router(setup_model_routes(model_discovery))

# Ollama local-model management (install/list/remove via the UI)
from routes.ollama_routes import setup_ollama_routes
app.include_router(setup_ollama_routes())

# TTS
from routes.tts_routes import setup_tts_routes
app.include_router(setup_tts_routes(tts_service))

# STT
from services.stt import get_stt_service
stt_service = get_stt_service()
from routes.stt_routes import setup_stt_routes
app.include_router(setup_stt_routes(stt_service))
logger.info("STT service initialized (provider managed via settings)")

# Documents (artifacts/canvas)
from routes.document_routes import setup_document_routes
app.include_router(setup_document_routes(session_manager, upload_handler))

# Signatures (reusable image stamps)
from routes.signature_routes import setup_signature_routes
app.include_router(setup_signature_routes())

# Gallery (image library)
from routes.gallery_routes import setup_gallery_routes
app.include_router(setup_gallery_routes())

# Persisted image-editor drafts (server-backed projects)
from routes.editor_draft_routes import setup_editor_draft_routes
app.include_router(setup_editor_draft_routes())

# Scheduled tasks + event bus
from src.task_scheduler import TaskScheduler
task_scheduler = TaskScheduler(session_manager)
from src.event_bus import set_task_scheduler
set_task_scheduler(task_scheduler)
from routes.task_routes import setup_task_routes
app.include_router(setup_task_routes(task_scheduler))

from routes.assistant_routes import setup_assistant_routes
app.include_router(setup_assistant_routes(task_scheduler))

# Calendar (CalDAV)
from routes.calendar_routes import setup_calendar_routes
app.include_router(setup_calendar_routes())

# Shell (user-facing command execution)
from routes.shell_routes import setup_shell_routes
app.include_router(setup_shell_routes())

# Cookbook (model download/serve/cache, cookbook state sync)
from routes.cookbook_routes import setup_cookbook_routes
app.include_router(setup_cookbook_routes())

# Hardware model fitting (cookbook "What Fits?" tab)
from routes.hwfit_routes import setup_hwfit_routes
app.include_router(setup_hwfit_routes())

# Model A/B Comparison
from routes.compare_routes import setup_compare_routes
app.include_router(setup_compare_routes(session_manager))

# User Preferences
from routes.prefs_routes import setup_prefs_routes
app.include_router(setup_prefs_routes())

# Backup (export/import user data)
from routes.backup_routes import setup_backup_routes
app.include_router(setup_backup_routes(memory_manager, preset_manager, skills_manager))

from routes.font_routes import setup_font_routes
app.include_router(setup_font_routes())


# MCP (Model Context Protocol)
from src.mcp_manager import McpManager
from src.agent_tools import set_mcp_manager
from routes.mcp_routes import setup_mcp_routes

mcp_manager = McpManager()
set_mcp_manager(mcp_manager)
app.include_router(setup_mcp_routes(mcp_manager))
logger.info("MCP routes initialized")

# AI Interaction tools (debates, pipelines, self-managing AI, UI control)
from src.ai_interaction import set_session_manager as set_ai_session_manager, set_memory_manager as set_ai_memory_manager, set_rag_manager as set_ai_rag_manager
set_ai_session_manager(session_manager)
set_ai_memory_manager(memory_manager, memory_vector)
set_ai_rag_manager(rag_manager, personal_docs_mgr)
logger.info("AI interaction tools initialized (session, memory, RAG, UI control)")

# Webhooks
from routes.webhook_routes import setup_webhook_routes
app.include_router(setup_webhook_routes(webhook_manager, auth_manager, session_manager, api_key_manager))

# API Tokens
from routes.api_token_routes import setup_api_token_routes
app.include_router(setup_api_token_routes())

logger.info("Webhook & API token routes initialized")

# Notes (Google Keep-style notes/todos)
from routes.note_routes import setup_note_routes
app.include_router(setup_note_routes(task_scheduler))

# Email
from routes.email_routes import setup_email_routes
app.include_router(setup_email_routes())

from routes.vault_routes import setup_vault_routes
app.include_router(setup_vault_routes())

# Contacts (CardDAV)
from routes.contacts_routes import setup_contacts_routes
app.include_router(setup_contacts_routes())

# Applicant engine integration (Stage-2 foundation). Exposes the derived
# Applicant feature-state at /api/applicant/features so the nav activates the
# engine-backed sections progressively. Read-only; does not touch auth/users.
from routes.applicant_routes import setup_applicant_routes
app.include_router(setup_applicant_routes())
# First-run setup wizard — engine OOBE + onboarding intake proxy (/api/applicant/setup/*).
from routes.applicant_setup_routes import setup_applicant_setup_routes
app.include_router(setup_applicant_setup_routes())
# Model-endpoint edit/remove + conversion-preview download (dark-engine audit items
# 19/20) — a standalone sibling of the setup routes above under the same prefix,
# kept in its own file/router to avoid touching that in-flight file.
from routes.applicant_model_connections_routes import setup_applicant_model_connections_routes
app.include_router(setup_applicant_model_connections_routes())
# Lane A — engine resume/cover-letter library + redline review (/api/applicant/documents/*).
from routes.applicant_documents_routes import setup_applicant_documents_routes
app.include_router(setup_applicant_documents_routes())
# Lane B — Memory/Profile: attribute cloud + conversion-learning engine proxy.
from routes.applicant_memory_routes import setup_applicant_memory_routes
app.include_router(setup_applicant_memory_routes())
# Lane C — Chat/Agent ↔ engine assistant + job actions (additive; auth-protected).
from routes.applicant_chat_routes import setup_applicant_chat_routes
app.include_router(setup_applicant_chat_routes())
# FR-MIND — "What the assistant remembers" + "Saved playbooks" + learning curation
# approvals: thin owner-scoped proxy over the engine's /api/agent-memory/* surface.
from routes.applicant_mind_routes import setup_applicant_mind_routes
app.include_router(setup_applicant_mind_routes())
# Lane D — Applicant Email: digest/notifications + feedback proxy (/api/applicant/email).
from routes.applicant_email_routes import setup_applicant_email_routes
app.include_router(setup_applicant_email_routes())
# CRIT-portal: Pending-Actions Portal (primary home-base) — aggregates every open
# pending action across ALL the owner's campaigns into one feed + resolve +
# supply-a-missing-detail (/api/applicant/portal/*). Auth-protected, owner-scoped.
from routes.applicant_portal_routes import setup_applicant_portal_routes
app.include_router(setup_applicant_portal_routes())
# CRIT-portal end
# Stage 2.5 — ENGINE -> WORKSPACE callback channel (/api/applicant/internal/*).
# Gated in AuthMiddleware by the shared APPLICANT_INTERNAL_TOKEN (NOT loopback,
# since the engine calls from a sibling container). Disabled when no token is set.
from routes.applicant_internal_routes import setup_applicant_internal_routes
# Lane B (research): expose the native deep-research handler to the internal
# /research callback so the engine can run owner-scoped research synchronously.
app.state.research_handler = research_handler
# FR-MIND agent-memory bridge: expose the front-door memory/skills substrate to the
# internal /memory + /skills + /recall callbacks so the engine reaches "what the
# assistant remembers" + "saved playbooks" over the same token-gated channel (§10).
app.state.memory_manager = memory_manager
app.state.skills_manager = skills_manager
app.include_router(setup_applicant_internal_routes())
# CRIT-auto: live remote view/takeover + final-submit controls (/api/applicant/remote/*)
# and the engine credential vault (/api/applicant/vault/*). Auth + owner-scoped.
from routes.applicant_remote_routes import setup_applicant_remote_routes
app.include_router(setup_applicant_remote_routes())
from routes.applicant_vault_routes import setup_applicant_vault_routes
app.include_router(setup_applicant_vault_routes())

# CRIT-ops: Debug/Activity (read-only observability) + Update button + run-mode/
# throughput controls + discovery-source toggles. Admin-scoped engine proxies;
# additive, disjoint prefixes (/api/applicant/admin, /api/applicant/ops).
from routes.applicant_admin_routes import setup_applicant_admin_routes
app.include_router(setup_applicant_admin_routes())
from routes.applicant_ops_routes import setup_applicant_ops_routes
app.include_router(setup_applicant_ops_routes())
# end CRIT-ops

# Agent-activity feed — owner-scoped, read-only proxy over the engine's existing
# run status / intent / history (/api/applicant/activity/*). Surfaces the engine's
# plain-language "verb-noun" account in two front-door surfaces: the always-visible
# status strip in the app chrome and the dedicated Activity page in the left nav.
# Like the Portal, it is NOT gated behind one active campaign — it resolves the
# owner's campaign(s) and degrades soft when the engine is unreachable / there is
# no campaign / there is no activity yet.
from routes.applicant_activity_routes import setup_applicant_activity_routes
app.include_router(setup_applicant_activity_routes())

# Gallery (#296) — owner-scoped proxy over the engine's gallery collections
# (/api/applicant/gallery/*). Surfaces the per-campaign screenshots + generated
# materials the engine already captured as a browsable grid (applicantGallery.js).
# Separate from the workspace's own native image gallery; read-only; degrades soft.
from routes.applicant_gallery_routes import setup_applicant_gallery_routes
app.include_router(setup_applicant_gallery_routes())

# Campaign + discovery-source settings (#301) — owner-scoped proxy over the
# engine's campaign config (rename/archive/run-mode/throughput/budget) and
# per-campaign discovery-source toggles (Settings → Campaign tab).
from routes.applicant_campaigns_routes import setup_applicant_campaigns_routes
app.include_router(setup_applicant_campaigns_routes())

# Manual deep-research trigger — owner-scoped proxy over the engine's manual
# research run + budget (/api/applicant/research/*). The agent auto-escalates to
# research already; this gives the user a front-door "Research this" affordance
# (wired from the Daily updates row in static/js/emailLibrary/applicantDigest.js).
from routes.applicant_research_routes import setup_applicant_research_routes
app.include_router(setup_applicant_research_routes())

# Compare — owner-scoped proxy over the engine's cross-entity comparison
# (/api/applicant/compare/*, #297/#184/#486). Compares two or more applications or
# postings side-by-side and returns a dimension table. Distinct from the vendored
# model arena's own /api/compare. The engine route is itself llm-configured-gated;
# this layer forwards that gate verbatim. Auth-protected, owner-scoped.
from routes.applicant_compare_routes import setup_applicant_compare_routes
app.include_router(setup_applicant_compare_routes())

# Results (#1 audit finding) — owner-scoped, NON-admin proxy over the engine's
# learning summary (/api/admin/learning → /api/applicant/results). Surfaces the
# outcome funnel (matched→approved→submitted with pass-through rates), per-source
# conversion, and the learned "what converts for you" signature that was otherwise
# locked in the admin-only Debug tab. The engine route is setup-gated; this layer
# forwards that gate verbatim and degrades soft. Auth-protected, owner-scoped.
from routes.applicant_results_routes import setup_applicant_results_routes
app.include_router(setup_applicant_results_routes())

# Post-submission tracker (design-audit Top-25 #4) — owner-scoped proxy over the
# engine's PostSubmissionService state machine (/api/post-submission ->
# /api/applicant/tracker). Surfaces the applied -> awaiting response ->
# interview/offer signals -> rejected/ghosted/archived board, plus the owner's
# manual "record what happened" write. Aggregates across the owner's own
# campaigns (fanned out via list_campaigns()); the write additionally validates
# the application id against that same fan-out before forwarding. Auth-protected,
# owner-scoped.
from routes.applicant_tracker_routes import setup_applicant_tracker_routes
app.include_router(setup_applicant_tracker_routes())

# Global pause / kill-switch — owner-scoped proxy (/api/applicant/control) that
# fans the engine's per-campaign agent-run pause/resume across all of the owner's
# campaigns, so the always-visible status strip carries a one-tap supervisory brake
# (today pause is admin-only + per-campaign). Auth-protected, owner-scoped.
from routes.applicant_control_routes import setup_applicant_control_routes
app.include_router(setup_applicant_control_routes())

# Pre-submit snapshot — owner-scoped read proxy (/api/applicant/snapshot) over the
# engine's immutable submission snapshot (admin→owner read downgrade, mirrors
# results), so the final-submit gate can preview "exactly what will be sent" before
# the user authorizes the single irreversible action. Auth-protected, owner-scoped.
from routes.applicant_snapshot_routes import setup_applicant_snapshot_routes
app.include_router(setup_applicant_snapshot_routes())

# Post-submission "attention" feed (dark-engine audit B2 items 8/9/60) —
# owner-scoped read proxy (/api/applicant/followups) over the scheduler's daily
# ghosting-detection + follow-up-drafting sweep. Both surface as pending actions
# through the EXISTING Portal substrate already; this is an additional queryable
# per-campaign read (no new UI — see routes/applicant_followups_routes.py).
from routes.applicant_followups_routes import setup_applicant_followups_routes
app.include_router(setup_applicant_followups_routes())

# Assistant capability disclosure (dark-engine audit item 24) — owner-scoped,
# read-only proxy (/api/applicant/capabilities) over the engine's native MCP
# tool surface (GET /mcp/tools). Surfaces the plain-language "what the
# assistant can do" list in the front door; renders only what the engine
# actually advertises, never a fabricated list.
from routes.applicant_capabilities_routes import setup_applicant_capabilities_routes
app.include_router(setup_applicant_capabilities_routes())

# ========= ROUTES (kept in app.py) =========

def _serve_html_with_nonce(request: Request, file_path: str) -> HTMLResponse:
    """Read an HTML file and inject the CSP nonce into inline <script> tags.

    Containment guard: ``file_path`` must resolve inside ``BASE_DIR`` before it is
    opened. Current callers pass a path built from ``abs_join(BASE_DIR, ...)``, but
    that only absolutizes — it does not verify containment, so a future caller
    threading user input here would otherwise be a path-traversal sink. Reject
    anything that escapes the served-app root.

    Perf (round-3 lens #11): the file's bytes are cached by mtime via
    ``read_cached_html_parts`` (``src/app_helpers.py``) — split once around the
    ``{{CSP_NONCE}}`` token and re-joined here with a FRESH nonce every call.
    That keeps this a cheap ``str.join`` per request instead of a disk read +
    full 232 KB scan-and-replace on every navigation (index.html is shared by
    nine deep-link routes), while every response still gets its own unique
    nonce — the cache never stores or reuses a nonce value, only the static
    text either side of it.
    """
    from src.app_helpers import read_cached_html_parts
    try:
        parts = read_cached_html_parts(BASE_DIR, file_path)
    except ValueError:
        raise HTTPException(404, "not found")
    nonce = getattr(request.state, "csp_nonce", "")
    html = nonce.join(parts)
    return HTMLResponse(html)

@app.get("/")
async def serve_index(request: Request):
    static_path = abs_join(BASE_DIR, "static/index.html")
    if os.path.exists(static_path):
        return _serve_html_with_nonce(request, static_path)
    root_path = abs_join(BASE_DIR, "index.html")
    if os.path.exists(root_path):
        return _serve_html_with_nonce(request, root_path)
    raise HTTPException(404, "index.html not found")

@app.get("/notes")
async def serve_notes(request: Request):
    return await serve_index(request)

@app.get("/calendar")
async def serve_calendar(request: Request):
    return await serve_index(request)

# Per-tool deep-link routes — all serve the same SPA, the JS auto-opens
# the matching modal based on window.location.pathname. Each route also
# gets a unique favicon + page title via inline script in index.html so
# bookmarks render with tool-specific icons.
@app.get("/cookbook")
async def serve_cookbook(request: Request):
    return await serve_index(request)

@app.get("/email")
async def serve_email(request: Request):
    return await serve_index(request)

@app.get("/memory")
async def serve_memory(request: Request):
    return await serve_index(request)

@app.get("/gallery")
async def serve_gallery(request: Request):
    return await serve_index(request)

@app.get("/tasks")
async def serve_tasks(request: Request):
    return await serve_index(request)

@app.get("/library")
async def serve_library(request: Request):
    return await serve_index(request)

@app.get("/backgrounds")
async def serve_backgrounds(request: Request):
    """Sandbox page for prototyping background effects. No auth required."""
    return _serve_html_with_nonce(request, abs_join(BASE_DIR, "static/backgrounds.html"))

@app.get("/login")
async def serve_login(request: Request):
    return _serve_html_with_nonce(request, abs_join(BASE_DIR, "static/login.html"))

@app.get("/api/version")
async def get_version():
    from core.constants import APP_VERSION
    return {"version": APP_VERSION}

@app.get("/api/health")
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/api/runtime")
async def runtime_info() -> Dict[str, object]:
    in_docker = os.path.exists("/.dockerenv")
    if not in_docker:
        try:
            with open("/proc/1/cgroup", "r", encoding="utf-8", errors="ignore") as fh:
                cg = fh.read()
            in_docker = any(marker in cg for marker in ("docker", "containerd", "kubepods"))
        except Exception:
            in_docker = False
    ollama_url = (
        os.getenv("OLLAMA_BASE_URL")
        or os.getenv("OLLAMA_URL")
        or ("http://host.docker.internal:11434/v1" if in_docker else "http://127.0.0.1:11434/v1")
    )
    return {
        "in_docker": in_docker,
        "ollama_base_url": ollama_url,
    }

# ========= LIFECYCLE =========

@app.on_event("startup")
async def startup_event():
    global upload_cleanup_task
    logger.info("Application starting up...")

    # One app-lifetime httpx.AsyncClient for every workspace -> engine proxy
    # call (perf lens finding #3). ~180 routes previously did
    # `async with ApplicantEngineClient()` per request, each opening a brand
    # new connection pool (fresh TCP/TLS handshake, zero keep-alive reuse).
    # Routes that resolve this via `src.applicant_engine.shared_engine_http_client(
    # request)` and pass it in as `ApplicantEngineClient(client=...)` now ride
    # this single pooled client instead; closed once, below, in shutdown_event.
    from src.applicant_engine import build_shared_http_client
    app.state.http_client = build_shared_http_client()

    webhook_manager.set_loop(asyncio.get_running_loop())
    # Strong refs to fire-and-forget startup tasks. Without this, Python may
    # GC tasks created with `asyncio.create_task(...)` before they finish.
    _startup_tasks: list[asyncio.Task] = getattr(app.state, "_startup_tasks", [])
    app.state._startup_tasks = _startup_tasks
    if upload_cleanup_func:
        upload_cleanup_task = asyncio.create_task(upload_cleanup_func())
    # Always-on monitor that auto-continues the agent when a background bash
    # job (#!bg) finishes — re-invokes the turn with the job output.
    try:
        from src.bg_monitor import start_bg_monitor
        _startup_tasks.append(start_bg_monitor())
    except Exception as _e:
        logger.warning("Failed to start background-job monitor: %s", _e)
    # MCP servers can be slow or blocked by local tooling. Connect them after
    # the web server is accepting traffic instead of delaying the whole UI.
    async def _startup_mcp_connections():
        try:
            from src.builtin_mcp import register_builtin_servers
            await register_builtin_servers(mcp_manager)
        except BaseException as e:
            logger.warning(f"Built-in MCP registration failed (non-critical): {type(e).__name__}: {e}")
        try:
            await asyncio.wait_for(mcp_manager.connect_all_enabled(), timeout=20)
        except asyncio.TimeoutError:
            logger.warning("User MCP startup timed out (non-critical)")
        except BaseException as e:
            logger.warning(f"MCP startup failed (non-critical): {type(e).__name__}: {e}")

    _startup_tasks.append(asyncio.create_task(_startup_mcp_connections()))

    # Pre-warm the RAG tool index off the request path. Loading the local
    # embedding model + opening ChromaDB + indexing the built-in tools is a
    # one-time ~1-3s cost that otherwise lands on the user's FIRST message
    # (showing up as a big `tool_selection` time). Doing it here makes the
    # first turn as fast as subsequent ones (warm embed ≈ a few ms).
    async def _warmup_tool_index():
        try:
            from src.tool_index import get_tool_index
            idx = await asyncio.to_thread(get_tool_index)
            if idx:
                await asyncio.to_thread(idx.get_tools_for_query, "warmup", 8)
                logger.info("[startup] Tool index pre-warmed")
        except Exception as e:
            logger.warning(f"Tool index warmup failed (non-critical): {type(e).__name__}: {e}")

    _startup_tasks.append(asyncio.create_task(_warmup_tool_index()))
    # Warmup: ping all known LLM endpoints to prime connections
    async def _warmup_endpoints():
        try:
            import httpx
            endpoints = model_discovery.get_endpoints() if model_discovery else []
            for ep in endpoints[:5]:
                url = ep.get("url", "").replace("/chat/completions", "/models")
                if url:
                    try:
                        async with httpx.AsyncClient(timeout=5.0) as client:
                            await client.get(url)
                        logger.info(f"Warmup ping OK: {url}")
                    except Exception as e:
                        logger.debug(f"Warmup ping failed for endpoint: {e}")
        except Exception as e:
            logger.debug(f"Warmup ping skipped: {e}")

    _startup_tasks.append(asyncio.create_task(_warmup_endpoints()))

    # Keep-alive: ping endpoints every 60 seconds to prevent cold starts
    async def _keepalive_loop():
        while True:
            try:
                await asyncio.sleep(60)
                await _warmup_endpoints()
            except Exception as e:
                logger.warning(f"Keepalive loop error: {e}")
                await asyncio.sleep(300)  # Back off on error

    _startup_tasks.append(asyncio.create_task(_keepalive_loop()))

    async def _ensure_default_tasks():
        # Create/reconcile default automation tasks + personal assistant for every user.
        owners = set()
        try:
            import json as _json
            auth_path = "data/auth.json"
            with open(auth_path, encoding="utf-8") as f:
                users = _json.load(f).get("users", {})
            owners.update(users.keys())
        except Exception as e:
            logger.debug(f"Default task auth-owner scan: {e}")

        # Also reconcile owners already present in scheduled_tasks. This cleans
        # up stale/demo/deleted-user built-ins that are no longer in auth.json;
        # otherwise their old scheduled rows can keep firing forever.
        try:
            from core.database import SessionLocal, ScheduledTask
            from src.task_scheduler import HOUSEKEEPING_DEFAULTS
            builtin_names = []
            for defs in HOUSEKEEPING_DEFAULTS.values():
                builtin_names.append(defs["name"])
                builtin_names.extend(defs.get("legacy_names") or [])
            db_seed = SessionLocal()
            try:
                rows = db_seed.query(ScheduledTask.owner).filter(
                    (ScheduledTask.action.in_(list(HOUSEKEEPING_DEFAULTS.keys())))
                    | (ScheduledTask.name.in_(builtin_names))
                ).distinct().all()
                owners.update(row[0] for row in rows if row[0])
            finally:
                db_seed.close()
        except Exception as e:
            logger.debug(f"Default task existing-owner scan: {e}")

        try:
            for uname in sorted(owners):
                try:
                    await task_scheduler.ensure_defaults(uname)
                except Exception as e:
                    logger.debug(f"ensure_defaults({uname}): {e}")
        except Exception as e:
            logger.debug(f"Default tasks: {e}")

    # Reconcile built-in tasks before the runner starts. Otherwise legacy
    # scheduled built-ins can fire once before being converted to event tasks.
    await _ensure_default_tasks()

    # Disk-backed skills are not covered by the DB legacy-owner sweep. Repair
    # ownerless or deleted/test-owner SKILL.md files so strict owner filtering
    # does not make an existing library look empty after auth/account changes.
    try:
        import json as _json
        auth_path = "data/auth.json"
        with open(auth_path, encoding="utf-8") as f:
            users = _json.load(f).get("users", {})
        primary_owner = None
        for uname, udata in users.items():
            if udata.get("is_admin") is True:
                primary_owner = uname
                break
        if not primary_owner and users:
            primary_owner = next(iter(users))
        if primary_owner:
            changed = skills_manager.backfill_owner(primary_owner, set(users.keys()))
            if changed:
                logger.info("Assigned %s legacy skill file(s) to %s", changed, primary_owner)
    except Exception as e:
        logger.debug(f"Skill owner backfill skipped: {e}")

    # Start scheduled task runner — skip when running under a cron-driven
    # deployment where an external worker drives task firing. Mirrors
    # `APPLICANT_INPROCESS_POLLERS` from the email pollers.
    _tasks_inprocess = os.environ.get("APPLICANT_INPROCESS_TASKS", "1").strip().lower()
    if _tasks_inprocess not in ("0", "false", "no", "off", ""):
        await task_scheduler.start()
    else:
        logger.info(
            "In-process task scheduler disabled (APPLICANT_INPROCESS_TASKS=0); "
            "drive task firing externally (e.g. cron)."
        )
    # Periodic null-owner sweep — re-runs the legacy-owner assignment hourly
    # so any data created while auth was disabled / localhost-bypassed gets
    # claimed by the admin instead of staying world-visible (M19).
    async def _null_owner_sweep_loop():
        while True:
            try:
                await asyncio.sleep(3600)
                from core.database import _migrate_assign_legacy_owner
                await asyncio.to_thread(_migrate_assign_legacy_owner)
            except Exception as e:
                logger.debug(f"Null-owner sweep skipped: {e}")
                await asyncio.sleep(3600)

    _startup_tasks.append(asyncio.create_task(_null_owner_sweep_loop()))

    # Nightly skill audit — at ~02:00 local, test + judge a batch of the
    # least-recently-checked skills, auto-fixing/escalating weak ones (never
    # deletes). Rotates through the library so each night covers different
    # skills. Gated by the `skill_audit_nightly` setting (default on); hour via
    # `skill_audit_hour` (default 2), batch size via `skill_audit_batch` (8).
    async def _skill_audit_nightly_loop():
        from datetime import timedelta
        while True:
            try:
                from src.settings import get_setting
                hour = int(get_setting("skill_audit_hour", 2) or 2)
            except Exception:
                hour = 2
            now = datetime.now()
            nxt = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
            await asyncio.sleep(max(60, (nxt - now).total_seconds()))
            try:
                from src.settings import get_setting
                if not get_setting("skill_audit_nightly", True):
                    continue
                batch = int(get_setting("skill_audit_batch", 8) or 8)
                from routes.skills_routes import run_scheduled_skill_audit
                await run_scheduled_skill_audit(skills_manager, owner=None, max_skills=batch)
            except Exception as e:
                logger.warning(f"Nightly skill audit failed: {e}")

    _startup_tasks.append(asyncio.create_task(_skill_audit_nightly_loop()))

    logger.info("Application startup complete")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutting down...")
    # Close the shared engine-proxy client opened in startup_event. Individual
    # ApplicantEngineClient instances built with `client=app.state.http_client`
    # never close it themselves (see ApplicantEngineClient.aclose) — this is
    # the one place its lifecycle actually ends.
    http_client = getattr(app.state, "http_client", None)
    if http_client is not None:
        try:
            await http_client.aclose()
        except Exception as e:
            logger.warning(f"Shared engine http_client shutdown error: {e}")
    if upload_cleanup_task:
        upload_cleanup_task.cancel()
        try:
            await upload_cleanup_task
        except asyncio.CancelledError:
            pass
    # Stop task scheduler (no-op if it never started under the gate)
    try:
        await task_scheduler.stop()
    except Exception:
        pass
    # Close webhook manager
    try:
        await webhook_manager.close()
    except Exception as e:
        logger.warning(f"Webhook manager shutdown error: {e}")
    # Disconnect all MCP servers
    try:
        await mcp_manager.disconnect_all()
    except Exception as e:
        logger.warning(f"MCP shutdown error: {e}")
    logger.info("Application shutdown complete")
