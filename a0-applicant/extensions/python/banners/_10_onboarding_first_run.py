"""redesign-conversational-onboarding.md §3.1 — first-run OOBE auto-popup.

On the welcome surface, force-open the onboarding wizard (`main.html`) exactly
once: when the intake has never been shown before AND is not yet complete. This
reuses the framework's already-built, already-wired auto-modal mechanism end to
end — `agent-zero/api/banners.py` calls every `banners` extension with the
frontend's `frontend_context` (surface/ctxid/etc); the welcome-screen client
(`agent-zero/plugins/_discovery/extensions/webui/initFw_end/auto-modal.js`) polls
`POST /banners` and force-opens any returned banner's `auto_modal_path` unless it
is session-suppressed or already open. Nothing here is new frontend JS — only the
banner producer, mirroring `plugins/_discovery/extensions/python/banners/10_discovery_cards.py`'s
shape.

Fires "never marked shown AND not complete" — a PERSISTENT (not session-scoped)
one-shot: it survives across browser sessions/devices until the user has actually
seen the wizard once (`mark_shown`, fired from `main.html`'s `init()`). The
auto-modal client's own session-scoped suppression additionally stops it from
re-popping mid-session if the user closes it and keeps chatting.

``agent=None`` in this hook (`agent-zero/api/banners.py:16`), so — like every
other ``a0-applicant/api/*.py`` proxy — this must be self-contained. Reusing the
sibling ``api/onboarding.py`` proxy's ``dispatch()`` is done by loading that file
directly by path (exactly how the framework's own dispatcher in
``agent-zero/helpers/api.py`` loads plugin api handlers,
``helpers/modules.py:import_module``), NOT via a ``plugins.applicant.api...``
package import: this plugin's api handlers are loaded by the framework as bare
top-level modules (never registered under a ``plugins.applicant`` package path),
which is exactly why ``a0-applicant/api/onboarding.py``'s own docstring calls
plugin sibling-imports unreliable.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from helpers.extension import Extension


def _load_onboarding_proxy():
    """Load the sibling ``api/onboarding.py`` module by file path (self-contained).

    See the module docstring: this mirrors ``helpers/modules.py:import_module``
    rather than assuming any particular package import path resolves.
    """
    path = Path(__file__).resolve().parents[3] / "api" / "onboarding.py"
    spec = importlib.util.spec_from_file_location("_applicant_onboarding_proxy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load onboarding proxy from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OnboardingFirstRun(Extension):
    async def execute(self, banners: list | None = None, frontend_context: dict | None = None, **kwargs):
        if banners is None:
            return
        frontend_context = frontend_context or {}
        if frontend_context.get("surface") != "welcome":
            return

        try:
            onboarding_dispatch = _load_onboarding_proxy().dispatch
            result = onboarding_dispatch({"action": "state"})
        except Exception:
            return  # proxy/engine unavailable — fail closed, no popup this time

        if not result.get("ok"):
            return
        state = result.get("data") or {}
        if state.get("oobe_shown") or state.get("complete"):
            return

        banners.append({
            "id": "applicant-onboarding-first-run",
            "auto_modal_path": "plugins/applicant/webui/main.html",
            "auto_modal_priority": 100,
            "auto_modal_surfaces": ["welcome"],
            "auto_modal_reason": "onboarding-incomplete",
            "dismissible": True,
        })
