"""Regression coverage for the vault master-key rotation UI affordance
(dark-engine audit item 18): "Rotate encryption key" in ``applicantVault.js``.

The engine's ``POST /api/credentials/rotate-key`` (FR-VAULT-3) re-encrypts
every stored secret under a fresh key but had no proxy, client method, or UI
control in ``workspace/`` — curl-only. This file pins the SOURCE-level shape
of the front-end control: a labeled button in the vault modal, a danger-styled
confirm before it does anything (this is a heavy, destructive-adjacent
operation touching every saved sign-in at once), and that it posts to the new
proxy route. No `FR-`/`NFR-` jargon or upstream codenames may leak into the
user-facing strings.

Follows the ``test_applicant_round2_emailscan_ui.py`` convention for this
kind of module: source-text regex assertions for the browser-only vault
modal (no DOM-independent entry point cheap enough to shim here). Each
assertion below was hand-verified to go red when the corresponding piece of
the affordance is reverted (dropping the button, dropping the confirm,
un-wiring the click handler, dropping the client method / proxy route), then
confirmed green again after restoring.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
VAULT_JS = WORKSPACE_DIR / "static" / "js" / "applicantVault.js"
VAULT_ROUTES_PY = WORKSPACE_DIR / "routes" / "applicant_vault_routes.py"
ENGINE_CLIENT_PY = WORKSPACE_DIR / "src" / "applicant_engine.py"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── the button: visible, labeled, reuses the design system ─────────────────


def test_rotate_key_button_exists_in_vault_modal_markup():
    src = _read(VAULT_JS)
    assert 'id="applicant-vault-rotate-key"' in src
    assert 'Rotate encryption key' in src
    # Reuses the existing button class — no hand-rolled button styling.
    m = re.search(r'<button id="applicant-vault-rotate-key"[^>]*>', src)
    assert m, "expected the rotate-key button markup"
    assert 'class="cal-btn"' in m.group(0)


def test_rotate_key_button_is_wired_to_a_click_handler():
    src = _read(VAULT_JS)
    assert re.search(
        r"on\('applicant-vault-rotate-key',\s*'click',\s*_onRotateKey\)", src
    ), "expected the rotate-key button wired to _onRotateKey"


# ── the confirm: destructive-adjacent, must not fire without it ────────────


def test_rotate_key_handler_confirms_before_calling_the_engine():
    src = _read(VAULT_JS)
    fn = re.search(r"async function _onRotateKey\(\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected an async _onRotateKey() handler"
    body = fn.group(0)
    # Uses the shared danger-styled confirm helper (not a bespoke prompt).
    assert "_confirm(" in body
    assert "danger: true" in body
    assert "cannot be undone" in body.lower()
    # The confirm result must gate the network call — no confirm, no request.
    confirm_pos = body.index("_confirm(")
    post_pos = body.index("_post(")
    assert confirm_pos < post_pos, "must confirm before posting to the engine"
    assert "if (!ok) return;" in body


def test_rotate_key_handler_posts_to_the_new_proxy_route():
    src = _read(VAULT_JS)
    fn = re.search(r"async function _onRotateKey\(\) \{.*?\n\}\n", src, re.S)
    assert fn
    assert "_post(`${API}/rotate-key`)" in fn.group(0)


def test_rotate_key_handler_disables_the_button_while_busy():
    src = _read(VAULT_JS)
    fn = re.search(r"async function _onRotateKey\(\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "btn.disabled = true" in body
    assert "btn.disabled = false" in body


# ── white-label: no jargon / codenames in the user-facing copy ─────────────


def test_rotate_key_copy_has_no_fr_nfr_jargon():
    src = _read(VAULT_JS)
    fn = re.search(r"async function _onRotateKey\(\) \{.*?\n\}\n", src, re.S)
    assert fn
    combined = fn.group(0)
    # The confirm / toast copy must read as plain language, not spec jargon.
    assert not re.search(r"\bFR-|\bNFR-", combined)


# ── the chain behind the button: client method + proxy route ───────────────


def test_engine_client_has_a_rotate_key_method():
    src = _read(ENGINE_CLIENT_PY)
    fn = re.search(r"async def vault_rotate_key\(self\) -> Any:.*?\n\n", src, re.S)
    assert fn, "expected ApplicantEngineClient.vault_rotate_key"
    assert '"/api/credentials/rotate-key"' in fn.group(0)
    assert '"POST"' in fn.group(0)


def test_proxy_rotate_key_route_is_registered_under_the_vault_prefix():
    src = _read(VAULT_ROUTES_PY)
    assert '@router.post("/rotate-key")' in src


def test_proxy_rotate_key_route_matches_sibling_privilege_gate():
    """The rotation route must require the SAME privilege as the other
    mutating vault routes (store/capture/account) — not a weaker one."""
    src = _read(VAULT_ROUTES_PY)
    fn = re.search(
        r"async def rotate_key\(request: Request\) -> JSONResponse:.*?\n\n    @router|"
        r"async def rotate_key\(request: Request\) -> JSONResponse:.*?\Z",
        src,
        re.S,
    )
    assert fn, "expected an async rotate_key(...) route handler"
    body = fn.group(0)
    assert 'require_privilege(request, "can_use_documents")' in body
    assert "engine.vault_rotate_key()" in body


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_vault_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(VAULT_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
