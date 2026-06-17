"""Model-endpoint service — add a model source (local or cloud) and auto-list its models.

This backs the setup page's "Add Models" section, ported from the Applicant settings
flow. The user adds an endpoint by base URL (+ an optional API key); the server then
calls that address and lists the models available there. The browser never sees the
raw API key — the server does the live model fetch and the key is sealed in the
encrypted vault, so there are no CORS or key-leak concerns.

Endpoint records are persisted in the app-config key/value store (no plaintext keys:
only a vault marker is kept). Each record matches the shape the settings UI expects:
``{id, name, base_url, is_enabled, online, models: [...]}``.

Live model listing mirrors the LLM adapter:
  * Cloud / OpenAI-compatible (OpenRouter, OpenAI, …): ``GET {base}/models`` with a
    ``Authorization: Bearer <key>`` header; response ``{"data": [{"id": ...}]}``.
  * Local (Ollama): ``GET {base}/api/tags``; response ``{"models": [{"name": ...}]}``.

The live fetch is mockable: an ``httpx`` transport can be injected so tests never
touch the network. Results are cached briefly so repeated dropdown refreshes don't
re-hit the provider on every open.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

import httpx

from applicant.application.services.setup_service import validate_operator_url
from applicant.core.errors import InvalidInput
from applicant.observability.logging import get_logger

log = get_logger(__name__)

_ENDPOINTS_KEY = "model.endpoints"
_CACHE_TTL_SECONDS = 30.0


def _normalize_base(base_url: str) -> str:
    """Trim trailing slashes from a base URL (mirrors the LLM adapter)."""
    return (base_url or "").strip().rstrip("/")


def _looks_local(base_url: str) -> bool:
    """Heuristic: localhost / private hosts read as a local endpoint."""
    u = (base_url or "").lower()
    return (
        "localhost" in u
        or "127.0.0.1" in u
        or "0.0.0.0" in u
        or "://192.168." in u
        or "://10." in u
        or ".local" in u
        or ":11434" in u  # default Ollama port
    )


def _is_ollama(base_url: str) -> bool:
    """Ollama exposes /api/tags rather than the OpenAI /models route."""
    u = (base_url or "").lower()
    return "11434" in u or "ollama" in u


class ModelEndpointService:
    """Add/list/delete model endpoints and live-list their available models.

    ``config_store`` persists endpoint records; ``credentials`` seals API keys.
    ``transport`` (optional) lets tests inject a stub ``httpx`` transport so the
    live model fetch is hermetic.
    """

    def __init__(
        self,
        *,
        config_store: Any,
        credentials: Any | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        workspace: Any | None = None,
        cookbook_local_host: str = "applicant-ui",
    ) -> None:
        self._store = config_store
        self._credentials = credentials
        self._transport = transport
        self._timeout = timeout
        # Lane C: optional engine -> workspace callback client. When configured
        # (shared secret set), Cookbook-served local models are merged into the
        # endpoint list as auto-discovered, read-only endpoints. None/unavailable
        # => the engine just shows user-configured endpoints (graceful degrade).
        self.workspace = workspace
        # Host the engine uses to reach a workspace-local ("localhost") serve over
        # the docker network (see ``_rewrite_local_host``).
        self.cookbook_local_host = cookbook_local_host
        # base_url -> (expires_at, models). Brief cache, like the Applicant flow.
        self._cache: dict[str, tuple[float, list[str]]] = {}

    # --- persistence -----------------------------------------------------
    def _load(self) -> list[dict[str, Any]]:
        rec = self._store.get(_ENDPOINTS_KEY)
        if not rec:
            return []
        return list(rec.get("endpoints", []))

    def _save(self, endpoints: list[dict[str, Any]]) -> None:
        self._store.set(_ENDPOINTS_KEY, {"endpoints": endpoints})

    # --- public records (UI shape, no secrets) ---------------------------
    def list_endpoints(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        """Return endpoints in the shape the settings UI expects (no API keys).

        Each record carries its live model list; offline endpoints report
        ``online=False`` with an empty model list so the dropdowns stay usable.
        """
        out: list[dict[str, Any]] = []
        configured_bases: set[str] = set()
        for rec in self._load():
            models, online, error = self._models_for(rec, refresh=refresh)
            configured_bases.add(_normalize_base(rec.get("base_url", "")))
            out.append(
                {
                    "id": rec["id"],
                    "name": rec.get("name") or rec.get("base_url", ""),
                    "base_url": rec.get("base_url", ""),
                    "is_enabled": bool(rec.get("is_enabled", True)),
                    "online": online,
                    "category": "local" if _looks_local(rec.get("base_url", "")) else "api",
                    "has_key": bool(rec.get("api_key_ref") or rec.get("api_key")),
                    "models": models,
                    "ping_error": error,
                }
            )
        # Lane C: append Cookbook-served local endpoints (auto-discovered). They
        # never clobber a user-configured endpoint with the same base URL — the
        # user's record wins; the Cookbook one is dropped.
        out.extend(self._cookbook_endpoints(configured_bases, refresh=refresh))
        return out

    def get_endpoint(self, endpoint_id: str) -> dict[str, Any] | None:
        for rec in self._load():
            if rec["id"] == endpoint_id:
                return rec
        return None

    # --- Lane C: Cookbook-served local endpoints (auto-discovered) --------
    def _rewrite_local_host(self, base_url: str) -> str:
        """Rewrite a workspace-local ("localhost") host to a docker-reachable one.

        The workspace reports a Cookbook serve's base URL from the UI's vantage
        point — typically ``http://localhost:PORT`` because the serve runs on the
        workspace host. The engine is a *sibling container*, so ``localhost`` would
        point at the engine itself. We swap a loopback host for
        ``cookbook_local_host`` (the front-door container that runs local serves)
        so the engine reaches the same process over the private docker network. A
        serve with an explicit remote host is already network-addressable and is
        left untouched.

        Assumption: Cookbook local serves run inside / alongside the
        ``applicant-ui`` container and bind a port reachable from the ``api``
        container at ``http://applicant-ui:PORT`` (override via COOKBOOK_LOCAL_HOST).
        """
        host = (self.cookbook_local_host or "").strip()
        if not host:
            return base_url
        return re.sub(
            r"^(https?://)(localhost|127\.0\.0\.1|0\.0\.0\.0)(?=[:/]|$)",
            rf"\1{host}",
            base_url,
            count=1,
        )

    def _cookbook_endpoints(
        self, configured_bases: set[str], *, refresh: bool
    ) -> list[dict[str, Any]]:
        """Auto-discovered Cookbook endpoints from the workspace callback channel.

        Returns ``[]`` (graceful degrade) when the channel is off
        (``workspace.available()`` False), unreachable, or nothing is served.
        Each returned record is clearly labeled (``category="cookbook"``,
        ``source="cookbook"``) and read-only (no stored credentials / id is
        derived, not persisted). Never raises — a flaky workspace must not break
        the user's own endpoint list.
        """
        ws = self.workspace
        if ws is None or not getattr(ws, "available", lambda: False)():
            return []
        try:
            payload = ws.local_models()
        except Exception as exc:  # WorkspaceError or anything else
            log.warning("cookbook_local_models_unavailable", error=str(exc))
            return []
        models = (payload or {}).get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return []

        out: list[dict[str, Any]] = []
        for m in models:
            if not isinstance(m, dict):
                continue
            raw_base = _normalize_base(m.get("base_url", ""))
            if not raw_base:
                continue
            base = self._rewrite_local_host(raw_base)
            norm = _normalize_base(base)
            # Never clobber a user-configured endpoint with the same address.
            if norm in configured_bases:
                continue
            configured_bases.add(norm)
            model_id = m.get("model_id") or m.get("name") or ""
            label = m.get("name") or model_id or base
            # Probe the (rewritten) endpoint so the dropdown shows live models;
            # tolerate offline (serve still warming up) without dropping it.
            live, online, error = self._fetch_models(base, "", refresh=refresh)
            listed = live or ([model_id] if model_id else [])
            out.append(
                {
                    "id": f"cookbook:{norm}",
                    "name": f"{label} (Cookbook)",
                    "base_url": base,
                    "is_enabled": True,
                    "online": online,
                    "category": "cookbook",
                    "source": "cookbook",
                    "read_only": True,
                    "has_key": False,
                    "models": listed,
                    "ping_error": error,
                }
            )
        return out

    # --- mutations -------------------------------------------------------
    def add_endpoint(
        self,
        *,
        base_url: str,
        api_key: str = "",
        name: str = "",
        model_type: str = "llm",
        probe: bool = True,
    ) -> dict[str, Any]:
        """Register an endpoint and (by default) live-list its models on save.

        Returns the UI record, including the freshly fetched ``models`` list and
        ``online``/``status`` so the form can report "found N models" inline.
        """
        base = _normalize_base(base_url)
        if not base:
            raise InvalidInput("Enter a base URL (e.g. http://localhost:11434/v1).")
        # SSRF guard (operator-supplied URL): same policy as the LLM base URL —
        # localhost / private endpoints allowed, cloud-metadata blocked.
        validate_operator_url(base, field="base URL")

        endpoints = self._load()
        # Dedupe on base URL so re-adding the same address updates in place.
        existing = next((e for e in endpoints if _normalize_base(e.get("base_url", "")) == base), None)
        endpoint_id = existing["id"] if existing else uuid.uuid4().hex
        record: dict[str, Any] = {
            "id": endpoint_id,
            "name": name.strip() or (existing or {}).get("name") or base,
            "base_url": base,
            "is_enabled": True,
            "model_type": model_type or "llm",
        }
        if api_key:
            self._seal_key(endpoint_id, api_key, record)
        elif existing:
            # Preserve a previously sealed key when re-adding without a new one.
            for k in ("api_key_ref", "api_key"):
                if k in existing:
                    record[k] = existing[k]

        if existing:
            endpoints = [record if e["id"] == endpoint_id else e for e in endpoints]
        else:
            endpoints.append(record)
        self._save(endpoints)
        self._cache.pop(base, None)

        models: list[str] = []
        online = False
        error: str | None = None
        if probe:
            models, online, error = self._models_for(record, refresh=True)
        log.info(
            "model_endpoint_added",
            base_url=base,
            online=online,
            models=len(models),
            existing=bool(existing),
        )
        return {
            "id": endpoint_id,
            "name": record["name"],
            "base_url": base,
            "is_enabled": True,
            "online": online,
            "existing": bool(existing),
            "status": "empty" if (online and not models) else ("online" if online else "offline"),
            "models": models,
            "ping_error": error,
        }

    def test_endpoint(self, *, base_url: str, api_key: str = "") -> dict[str, Any]:
        """Probe an endpoint WITHOUT saving it (the form's "Test" button)."""
        base = _normalize_base(base_url)
        if not base:
            raise InvalidInput("Enter a base URL to test.")
        validate_operator_url(base, field="base URL")
        models, online, error = self._fetch_models(base, api_key)
        return {
            "base_url": base,
            "online": online,
            "models": models,
            "ping_error": error,
        }

    def set_enabled(self, endpoint_id: str, enabled: bool) -> None:
        endpoints = self._load()
        for rec in endpoints:
            if rec["id"] == endpoint_id:
                rec["is_enabled"] = bool(enabled)
        self._save(endpoints)

    def toggle_enabled(self, endpoint_id: str) -> None:
        endpoints = self._load()
        for rec in endpoints:
            if rec["id"] == endpoint_id:
                rec["is_enabled"] = not bool(rec.get("is_enabled", True))
        self._save(endpoints)

    def delete_endpoint(self, endpoint_id: str) -> None:
        endpoints = [e for e in self._load() if e["id"] != endpoint_id]
        self._save(endpoints)

    def models_for_id(self, endpoint_id: str, *, refresh: bool = False) -> list[str]:
        rec = self.get_endpoint(endpoint_id)
        if rec is None:
            return []
        models, _, _ = self._models_for(rec, refresh=refresh)
        return models

    # --- live model fetch -------------------------------------------------
    def _models_for(
        self, rec: dict[str, Any], *, refresh: bool
    ) -> tuple[list[str], bool, str | None]:
        base = _normalize_base(rec.get("base_url", ""))
        key = self._resolve_key(rec)
        return self._fetch_models(base, key, refresh=refresh)

    def _fetch_models(
        self, base: str, api_key: str, *, refresh: bool = False
    ) -> tuple[list[str], bool, str | None]:
        """Live-list models at ``base``. Returns (models, online, error).

        Brief cache so re-opening the dropdowns doesn't re-hit the provider; a
        ``refresh`` forces a fresh call (used on add / explicit refresh).
        """
        base = _normalize_base(base)
        if not base:
            return [], False, "no base URL"
        now = time.monotonic()
        if not refresh:
            cached = self._cache.get(base)
            if cached and cached[0] > now:
                return cached[1], True, None

        if _is_ollama(base):
            tags_base = base[: -len("/v1")] if base.endswith("/v1") else base
            url = f"{tags_base}/api/tags"
        else:
            url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
        headers = {"Content-Type": "application/json"}
        if api_key and not _is_ollama(base):
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            log.warning("model_endpoint_list_failed", base_url=base, error=str(exc))
            return [], False, str(exc)
        models = self._parse_models(data)
        self._cache[base] = (now + _CACHE_TTL_SECONDS, models)
        return models, True, None

    @staticmethod
    def _parse_models(data: dict[str, Any]) -> list[str]:
        if not isinstance(data, dict):
            return []
        # Ollama: {"models": [{"name": "llama3.1:8b", ...}, ...]}
        if isinstance(data.get("models"), list):
            return [
                m.get("name", m.get("model", ""))
                for m in data["models"]
                if isinstance(m, dict) and (m.get("name") or m.get("model"))
            ]
        # OpenAI / OpenRouter: {"data": [{"id": "gpt-4o", ...}, ...]}
        if isinstance(data.get("data"), list):
            return [m.get("id", "") for m in data["data"] if isinstance(m, dict) and m.get("id")]
        return []

    # --- secret handling (reuse the credential vault) --------------------
    def _seal_key(self, endpoint_id: str, api_key: str, record: dict[str, Any]) -> None:
        ref = f"model.endpoint.{endpoint_id}"
        if self._credentials is not None:
            from applicant.core.ids import CampaignId
            from applicant.ports.driven.credential_store import Credential

            self._credentials.store(
                CampaignId("__system__"),
                Credential(tenant_key=ref, username="api_key", secret=api_key),
            )
            record["api_key_ref"] = ref
        else:
            # No vault wired (tests): keep inline but never logged.
            record["api_key"] = api_key

    def _resolve_key(self, record: dict[str, Any]) -> str:
        if "api_key" in record:
            return record["api_key"]
        ref = record.get("api_key_ref")
        if ref and self._credentials is not None:
            from applicant.core.ids import CampaignId

            cred = self._credentials.retrieve(CampaignId("__system__"), ref)
            return cred.secret if cred else ""
        return ""
