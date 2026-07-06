"""Regression coverage for the round-2 §5 "Do this week (V:high·E:S)" tranche
of ``docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md``, confined to this batch's
five owned modules: ``applicantCore.js``, ``applicantGallery.js``,
``applicantCompare.js``, ``applicantVault.js`` and ``applicantChat.js``.

Follows the convention of ``test_applicant_round1_observability.py`` /
``test_applicant_round1_chatmind.py``: every fact is read from the actual
static file content via ``pathlib`` + regex — no browser, no DOM, no real
socket. These modules do top-level ``document``/launcher-wiring work on import
(``_boot()`` runs at module scope), so, same as those precedents, they are not
importable under a bare ``node --input-type=module`` without a DOM shim; hence
the text/regex approach throughout.

Three items, closed out as follows (each verified by hand: revert the fix,
confirm the assertion goes red, restore, confirm green):

* **#9** (AbortController + ~15s timeout in ``_fetchJSON``) — the timeout
  itself (``applicantCore.js``) was ALREADY present going into this batch
  (commit ``fd4f252``, prior round). What was still a real gap: the shared
  15s default is too short for the one call in these five files that is
  genuinely LLM-backed — Chat's ``/message`` send, which runs the engine's
  full agent loop server-side and whose own backend→engine client
  (``ApplicantEngineClient._DEFAULT_TIMEOUT`` in
  ``workspace/src/applicant_engine.py``) already waits up to a 30s read
  timeout for that reply. A 15s browser-side abort would misfire as a false
  "timed out" while the backend was still legitimately waiting on the engine.
  Fixed by (a) giving ``_post`` an optional third ``opts`` param that merges
  into the underlying ``_fetchJSON`` call, and (b) having Chat's message send
  pass ``{ timeoutMs: MESSAGE_TIMEOUT_MS }`` (35s — comfortably past the
  backend's 30s) instead of the bare 15s default. No other call site in these
  five files needed an override (Gallery/Compare/Vault calls are all plain,
  fast DB reads/writes with no LLM in the path — verified against
  ``compare_service.py``, which is pure diffing, no LLM).

* **#24** (inline Retry on every error state + 401-vs-offline messaging) —
  Gallery and Compare were ALREADY fully wired to ``errorHTML``/``wireRetry``
  going into this batch (their own ``_errLine`` helpers already existed).
  Two real gaps remained in Vault and Chat, both fixed here:
    - Vault's ``_loadTenants`` fetch-failure path rendered a bespoke
      ``emptyEl.textContent = e.message`` line with no retry affordance at
      all (the modal's separate header "Refresh" button is not the same
      thing as an inline Retry on the error itself). Now uses
      ``errorHTML``/``wireRetry`` like every other surface, plus a local
      ``_errLine`` (mirroring Gallery/Compare's) so an unreachable engine
      reads differently from a generic error.
    - Chat's ``openApplicantChat`` catch-all collapsed EVERY failure —
      including a 401 session-expired and a real network/timeout — into the
      "Connect a model in Settings" gated copy (``_renderOffline``), which is
      actively misleading for those cases (nothing to do with model
      connection) and offered no retry. Now renders ``errorHTML(errText(e))``
      + ``wireRetry`` for real thrown errors, while ``_renderOffline`` stays
      reserved for the genuine `engine_available:false` gate (which the
      ``/campaigns`` route soft-degrades to rather than throwing).

* **#15** (shared loading/empty/error/gated kit, no bespoke one-offs) —
  ``loadingHTML``/``emptyHTML``/``errorHTML``/``gatedHTML``/``wireRetry``
  already existed in ``applicantCore.js`` and were already used pervasively
  in Gallery/Compare/Chat going into this batch. The one straggler: Vault's
  ``_loadTenants`` loading state was a bespoke inline
  ``<span>Loading…</span>`` (no spinner, not the shared look). Converted to
  ``loadingHTML('Loading…')``.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
CORE_JS = JS_DIR / "applicantCore.js"
GALLERY_JS = JS_DIR / "applicantGallery.js"
COMPARE_JS = JS_DIR / "applicantCompare.js"
VAULT_JS = JS_DIR / "applicantVault.js"
CHAT_JS = JS_DIR / "applicantChat.js"
ENGINE_CLIENT_PY = REPO_ROOT / "workspace" / "src" / "applicant_engine.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    """Extract a top-level `function name(...) { ... }` body (same convention
    as test_applicant_round1_observability.py's `_top_level_fn`)."""
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...) in the source"
    return m.group(1)


def _async_top_level_fn(src: str, name: str) -> str:
    m = re.search(rf"async function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level async function {name}(...) in the source"
    return m.group(1)


# ── #9: shared _fetchJSON timeout baseline (pre-existing; locked here) ──────

def test_fetchjson_has_abortcontroller_with_default_timeout_and_kind_tagging():
    """Baseline the round-2 batch built on: _fetchJSON must abort via a real
    AbortController on a 15s default timeout, and tag a resulting abort as a
    distinct 'timeout' kind (not lumped in with a plain 'network' failure)."""
    src = _read(CORE_JS)
    body = _async_top_level_fn(src, "_fetchJSON")
    assert "new AbortController()" in body
    assert re.search(r"timeoutMs\s*=\s*15000", body), "expected a 15000ms default timeout"
    assert re.search(r"setTimeout\(\s*\(\)\s*=>\s*controller\.abort\(\)\s*,\s*timeoutMs\s*\)", body)
    assert re.search(r"err\.kind\s*=\s*aborted\s*\?\s*'timeout'\s*:\s*'network'", body), (
        "an aborted request must be tagged kind='timeout', distinct from a plain network failure"
    )


# ── #9: _post gets an opts override so a slow call can widen the timeout ────

def test_post_wrapper_accepts_optional_opts_merged_into_fetchjson():
    """_post must accept an optional third `opts` argument and spread it into
    the underlying _fetchJSON call, so a caller can override e.g. timeoutMs
    without bypassing the shared helper. Existing 2-arg callers must be
    unaffected (opts defaults to {})."""
    src = _read(CORE_JS)
    body = _top_level_fn(src, "_post")
    assert re.search(r"export function _post\(url,\s*body,\s*opts\s*=\s*\{\}\)", src), (
        "_post must declare an optional third `opts = {}` parameter"
    )
    assert "...opts" in body, "_post must spread opts into the _fetchJSON call"


def test_chat_message_send_overrides_default_timeout_above_backend_engine_timeout():
    """Chat's /message send is the one call in this batch's five files that is
    genuinely LLM-backed (the engine's agent loop). It must override the
    shared helper's 15s default with something comfortably longer than the
    workspace backend's own engine-client read timeout (30s), so a real
    in-flight agentic reply doesn't get aborted client-side out from under a
    request the backend is still legitimately waiting on."""
    chat_src = _read(CHAT_JS)
    m = re.search(r"const MESSAGE_TIMEOUT_MS\s*=\s*(\d+)\s*;", chat_src)
    assert m, "expected a named MESSAGE_TIMEOUT_MS constant in applicantChat.js"
    message_timeout_ms = int(m.group(1))

    engine_src = _read(ENGINE_CLIENT_PY)
    dm = re.search(r"_DEFAULT_TIMEOUT\s*=\s*httpx\.Timeout\([^)]*read=([\d.]+)", engine_src)
    assert dm, "expected to find the backend engine client's read timeout"
    backend_read_timeout_ms = float(dm.group(1)) * 1000

    assert message_timeout_ms > 15000, "must override the shared 15s default"
    assert message_timeout_ms > backend_read_timeout_ms, (
        f"MESSAGE_TIMEOUT_MS ({message_timeout_ms}ms) must exceed the backend's own "
        f"engine-client read timeout ({backend_read_timeout_ms}ms), or the browser can "
        "still abort while the backend is legitimately still waiting on the engine"
    )

    # And the override must actually be wired onto the /message _post call.
    send_body = _async_top_level_fn(chat_src, "_sendToBubble")
    assert re.search(
        r"_post\(`\$\{API\}/message`,\s*\{[^}]*\},\s*\{\s*timeoutMs:\s*MESSAGE_TIMEOUT_MS\s*\}\)",
        send_body,
    ), "the /message _post call must pass { timeoutMs: MESSAGE_TIMEOUT_MS } as its third argument"


# ── #24: Vault's tenant-list fetch failure gets a real inline Retry ─────────

def test_vault_load_tenants_error_path_uses_errorhtml_and_wireretry():
    src = _read(VAULT_JS)
    body = _async_top_level_fn(src, "_loadTenants")
    catch_m = re.search(r"catch\s*\(e\)\s*\{(.*?)\n  \}", body, re.S)
    assert catch_m, "expected a catch(e) block in _loadTenants"
    catch_body = catch_m.group(1)
    assert "errorHTML(" in catch_body, "the fetch-failure path must render via the shared errorHTML kit"
    assert re.search(r"wireRetry\(listEl,\s*_loadTenants\)", catch_body), (
        "the fetch-failure path must wire an inline Retry back to _loadTenants itself"
    )
    # The old bespoke, retry-less error line must be gone.
    assert "emptyEl.textContent = e.message" not in src


def test_vault_err_line_distinguishes_offline_from_generic_error():
    src = _read(VAULT_JS)
    fn = re.search(r"function _errLine\(err\)\s*\{(.*?)\n\}", src, re.S)
    assert fn, "expected a local _errLine(err) helper in applicantVault.js"
    body = fn.group(1)
    assert "kind === 'offline'" in body or "kind === 'network'" in body
    assert "errText(err)" in body, "must fall back to the shared errText() for other kinds (e.g. 401 auth)"


def test_vault_imports_the_shared_state_and_retry_helpers():
    src = _read(VAULT_JS)
    import_line = re.search(r"import \{([^}]*)\} from '\./applicantCore\.js';", src)
    assert import_line, "expected an applicantCore.js import"
    names = {n.strip() for n in import_line.group(1).split(",")}
    for required in ("errText", "loadingHTML", "errorHTML", "wireRetry"):
        assert required in names, f"applicantVault.js must import {required} from applicantCore.js"


# ── #15: Vault's bespoke loading span replaced with the shared kit ──────────

def test_vault_uses_shared_loadinghtml_not_a_bespoke_span():
    src = _read(VAULT_JS)
    body = _async_top_level_fn(src, "_loadTenants")
    assert "loadingHTML('Loading…')" in body, "must render the loading state via the shared loadingHTML() kit"
    assert '<span style="opacity:0.6;font-size:12px;">Loading' not in src, (
        "the old one-off, spinner-less loading span must be gone"
    )


# ── #24: Chat's open-panel catch distinguishes real errors from the gate ────

def test_chat_open_catch_uses_errorhtml_wireretry_not_blanket_offline():
    """Chat-unification recast of the original #24 contract: opening the Job
    Assistant now means resolving its session and selecting it in the NATIVE
    surface, so a thrown open failure surfaces as a kind-aware errText toast
    (there is no modal body to render into); the errorHTML+wireRetry pair
    moved to the job-search bar's own loader (_refreshBar), which is the
    async panel that can genuinely fail after the surface is open. Neither
    path may collapse a real error into the gated "connect a model" copy."""
    src = _read(CHAT_JS)
    open_body = _async_top_level_fn(src, "openApplicantChat")
    catch_m = re.search(r"catch\s*\(e\)\s*\{(.*?)$", open_body, re.S)
    assert catch_m, "expected a catch(e) block in openApplicantChat"
    catch_body = catch_m.group(1)
    assert re.search(r"_toast\(errText\(e\)\)", catch_body), (
        "a genuinely thrown open error must surface through the kind-aware errText"
    )
    assert "_renderOffline" not in catch_body

    bar_body = _async_top_level_fn(src, "_refreshBar")
    bar_catch = re.search(r"catch\s*\(e\)\s*\{(.*?)$", bar_body, re.S)
    assert bar_catch, "expected a catch(e) block in _refreshBar"
    assert re.search(r"errorHTML\(errText\(e\)\)", bar_catch.group(1)), (
        "a genuinely thrown bar-load error must render via errorHTML(errText(e))"
    )
    assert re.search(r"wireRetry\(bar,\s*_refreshBar\)", bar_catch.group(1)), (
        "a genuinely thrown bar-load error must offer an inline Retry"
    )
    assert "_renderOffline(bar)" not in bar_catch.group(1)


def test_chat_engine_unavailable_gate_still_uses_renderoffline():
    """The one legitimate case for the "connect a model" gated copy — the
    `/campaigns` route's soft-degrade to `engine_available:false` — must be
    untouched by the catch-block fix above (it now lives in the job-search
    bar's loader)."""
    src = _read(CHAT_JS)
    body = _async_top_level_fn(src, "_refreshBar")
    assert re.search(
        r"if\s*\(data\s*&&\s*data\.engine_available\s*===\s*false\)\s*\{\s*_renderOffline\(bar\);\s*return;\s*\}",
        body,
    ), "the engine_available:false branch must still route to _renderOffline"


# ── #24: confirm Gallery/Compare's pre-existing wireRetry wiring (no regressions) ─

def test_gallery_error_states_already_wire_retry():
    src = _read(GALLERY_JS)
    render_body = _async_top_level_fn(src, "_renderGallery")
    assert "errorHTML(" in render_body and re.search(r"wireRetry\(_body\(\),\s*_renderGallery\)", render_body)
    open_body = _async_top_level_fn(src, "openApplicantGallery")
    assert "errorHTML(" in open_body and re.search(r"wireRetry\(_body\(\),\s*openApplicantGallery\)", open_body)


def test_compare_run_error_state_already_wires_retry():
    src = _read(COMPARE_JS)
    body = _async_top_level_fn(src, "_runCompare")
    assert "errorHTML(" in body and re.search(r"wireRetry\(result,\s*_runCompare\)", body)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
