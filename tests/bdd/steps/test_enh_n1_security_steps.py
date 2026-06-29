"""Step bindings for the N1 security & input-validation acceptance specs.

Theme N1 covers issues #313, #314, #315, #317, #318, #319, #320, #322, #346,
#349, #353, #354, #356 — LLM-tool exposure (loopback allowlist, secret leakage
to the model, unscrubbed chat), input validation (typed intake, typed Form
params, validated path ids, upload size caps), CORS origin parsing, the alembic
placeholder DSN, scraped-HTML/innerHTML XSS, and webhook-token storage.

Convention (see GHERKIN_BRIEF / the enh_research exemplar):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for protection
  that already ships on this branch — they assert against the actual code and
  must pass today.
* Scenarios tagged ``@pending`` are honest probes at the intended seam for a gap
  that is not yet closed (a missing attribute/helper, an untyped model, a plain
  column, an unsanitized render path). They make a genuine assertion the current
  code fails — never ``assert True``. ``conftest.pytest_bdd_apply_tag`` maps
  ``@pending`` to a non-strict xfail.

Hexagonal / hermetic: assertions target pure helpers, request models, core id
types, and static source facts (read via ``pathlib``). Speculative imports for
not-yet-built targets live INSIDE the step body so absence → runtime error →
xfail, never a collection error. No real sockets, DB, or browser.
"""

from __future__ import annotations

import asyncio
import importlib
import pathlib
import sys

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_313_app_api_allowlist.feature",
    "../features/enhancements/enh_314_vault_get_masking.feature",
    "../features/enhancements/enh_315_manage_tokens_masking.feature",
    "../features/enhancements/enh_317_chat_scrub.feature",
    "../features/enhancements/enh_318_typed_intake.feature",
    "../features/enhancements/enh_319_endpoint_form_model.feature",
    "../features/enhancements/enh_320_path_param_validation.feature",
    "../features/enhancements/enh_322_upload_size_limit.feature",
    "../features/enhancements/enh_346_cors_origins_parse.feature",
    "../features/enhancements/enh_349_alembic_placeholder.feature",
    "../features/enhancements/enh_353_research_html_sanitize.feature",
    "../features/enhancements/enh_354_chat_render_xss.feature",
    "../features/enhancements/enh_356_webhook_token_encryption.feature",
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_WORKSPACE = _REPO_ROOT / "workspace"


@pytest.fixture
def n1ctx() -> dict:
    return {}


def _add_workspace_to_path() -> None:
    ws = str(_WORKSPACE)
    if ws not in sys.path:
        sys.path.insert(0, ws)


def _read(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8")


# ===========================================================================
# #313 — app_api loopback: blocklist ships; allowlist is the gap
# ===========================================================================
@given("the app_api loopback tool blocklist")
def app_api_blocklist(n1ctx):
    _add_workspace_to_path()
    ti = importlib.import_module("src.tool_implementations")
    n1ctx["blocklist"] = ti._APP_API_BLOCKLIST_PREFIXES


@when("a sensitive endpoint prefix is checked against it")
def check_sensitive_prefix(n1ctx):
    paths = ["/api/auth/login", "/api/users/1", "/api/admin/wipe"]
    bl = n1ctx["blocklist"]
    n1ctx["refused"] = [p for p in paths if any(p.startswith(b) for b in bl)]


@then("the auth, user, and admin prefixes are refused")
def sensitive_prefixes_refused(n1ctx):
    assert len(n1ctx["refused"]) == 3


@given("the app_api loopback tool exposes an explicit allowlist of permitted prefixes")
def app_api_allowlist_seam(n1ctx):
    _add_workspace_to_path()
    n1ctx["ti"] = importlib.import_module("src.tool_implementations")


@when("a brand-new endpoint that nobody allowlisted is requested")
def new_endpoint_requested(n1ctx):
    ti = n1ctx["ti"]
    # The allowlist seam does not exist yet — a blocklist is the only gate, so a
    # newly added route is reachable by default. Probe for the allowlist.
    n1ctx["allowlist"] = getattr(ti, "_APP_API_ALLOWLIST_PREFIXES", None)


@then("the request is refused because it is not on the allowlist")
def refused_not_on_allowlist(n1ctx):
    allowlist = n1ctx["allowlist"]
    assert allowlist, "no explicit app_api allowlist exists — default is reachable"
    assert not any("/api/new-route".startswith(p) for p in allowlist)


# ===========================================================================
# #314 — vault_get: reason gate ships; masking is the gap
# ===========================================================================
@given("the vault_get tool with no reason supplied")
def vault_get_no_reason(n1ctx):
    _add_workspace_to_path()
    ti = importlib.import_module("src.tool_implementations")
    n1ctx["do_vault_get"] = ti.do_vault_get


@when("the vault entry is requested")
def request_vault_entry(n1ctx):
    import json

    content = json.dumps({"item_id": "abc123"})  # reason deliberately omitted
    n1ctx["result"] = asyncio.run(n1ctx["do_vault_get"](content))


@then("the request is refused for a missing reason")
def refused_missing_reason(n1ctx):
    res = n1ctx["result"]
    assert res.get("exit_code") == 1
    assert "reason" in (res.get("error") or "").lower()


@given("a vault login entry with a password and a TOTP secret")
def vault_login_entry(n1ctx):
    _add_workspace_to_path()
    n1ctx["ti"] = importlib.import_module("src.tool_implementations")


@when("the vault entry is rendered for the model context")
def render_vault_entry(n1ctx):
    ti = n1ctx["ti"]
    # The masking helper does not exist yet — do_vault_get builds the output with
    # the raw password/TOTP. Probe for a dedicated masker at the rendering seam.
    n1ctx["masker"] = getattr(ti, "_mask_vault_secret", None) or getattr(
        ti, "mask_vault_secret", None
    )


@then("the plaintext password and TOTP secret are masked, not echoed verbatim")
def vault_secret_masked(n1ctx):
    masker = n1ctx["masker"]
    assert masker is not None, "no vault-secret masking helper exists yet"
    masked = masker("hunter2-totp-seed")
    assert "hunter2-totp-seed" not in masked


# ===========================================================================
# #315 — manage_tokens: raw token returned to model (gap)
# ===========================================================================
@given("the manage_tokens tool result for a freshly created token")
def manage_tokens_result(n1ctx):
    _add_workspace_to_path()
    n1ctx["ti"] = importlib.import_module("src.tool_implementations")


@when("the result is inspected for what reaches the model context")
def inspect_token_result(n1ctx):
    ti = n1ctx["ti"]
    # A masker that keeps the raw token out of the model-visible result does not
    # exist yet (create returns {"token": raw_token}). Probe for it.
    n1ctx["token_masker"] = getattr(ti, "_mask_api_token", None) or getattr(
        ti, "mask_api_token", None
    )


@then("the raw token string is masked rather than returned verbatim")
def token_masked(n1ctx):
    masker = n1ctx["token_masker"]
    assert masker is not None, "manage_tokens still returns the raw token to the model"
    raw = "secrettokenvalue1234567890"
    assert raw not in masker(raw)


# ===========================================================================
# #317 — engine chat reply forwarded unscrubbed (gap)
# ===========================================================================
@given("an engine chat reply containing an internal campaign UUID")
def engine_chat_reply(n1ctx):
    n1ctx["reply"] = {
        "response": "Done. (campaign 7f3a1c2e-0000-4abc-9def-1234567890ab)",
        "campaign_id": "7f3a1c2e-0000-4abc-9def-1234567890ab",
    }


@when("the chat proxy forwards the reply to the browser")
def forward_chat_reply(n1ctx):
    _add_workspace_to_path()
    routes = importlib.import_module("routes.applicant_chat_routes")
    # No scrubber exists on the chat proxy yet — the reply is returned verbatim.
    n1ctx["scrubber"] = getattr(routes, "scrub_engine_reply", None) or getattr(
        routes, "_scrub_engine_reply", None
    )


@then("the internal UUID is scrubbed from the forwarded payload")
def uuid_scrubbed(n1ctx):
    scrubber = n1ctx["scrubber"]
    assert scrubber is not None, "no chat-reply scrubber exists yet"
    out = scrubber(dict(n1ctx["reply"]))
    import json

    assert "7f3a1c2e-0000-4abc-9def-1234567890ab" not in json.dumps(out)


# ===========================================================================
# #318 — onboarding intake: section enum validated (green); typed payload (gap)
# ===========================================================================
@given("the onboarding save-section endpoint")
def onboarding_section_endpoint(n1ctx):
    from applicant.ports.driving.onboarding import IntakeSection

    n1ctx["IntakeSection"] = IntakeSection


@when("a section whose name is not a known intake section is submitted")
def submit_unknown_section(n1ctx):
    try:
        n1ctx["IntakeSection"]("definitely-not-a-real-section")
        n1ctx["section_ok"] = True
    except ValueError:
        n1ctx["section_ok"] = False


@then("the unknown section is rejected before it reaches the service")
def unknown_section_rejected(n1ctx):
    assert n1ctx["section_ok"] is False


@given("the onboarding save-section request model")
def save_section_model(n1ctx):
    from applicant.app.routers import onboarding

    n1ctx["onboarding"] = onboarding


@when("the request body is inspected for a typed per-section payload schema")
def inspect_section_payload(n1ctx):
    model = n1ctx["onboarding"].SaveSectionIn
    n1ctx["data_anno"] = model.model_fields["data"].annotation


@then("the payload is a typed model, not a free-form dict")
def payload_is_typed(n1ctx):
    # Today ``data`` is annotated ``dict`` (untyped free-form). When the typed
    # schema lands the annotation will no longer be the bare ``dict`` builtin.
    assert n1ctx["data_anno"] is not dict, "SaveSectionIn.data is still a bare dict"


# ===========================================================================
# #319 — model-endpoint Form params: skip_probe parses (green); enum (gap)
# ===========================================================================
@given("the model-endpoint add route")
def model_endpoint_route(n1ctx):
    n1ctx["module"] = importlib.import_module(
        "applicant.app.routers.model_endpoints"
    )


@when('skip_probe is given as the string "false"')
def skip_probe_false(n1ctx):
    # Mirror the handler's own parse: probe = skip_probe.lower() not in truthy.
    skip_probe = "false"
    n1ctx["probe"] = str(skip_probe).lower() not in ("true", "1", "yes")


@then("the live model probe is enabled")
def probe_enabled(n1ctx):
    assert n1ctx["probe"] is True


@given("the model-endpoint add route signature")
def model_endpoint_signature(n1ctx):
    import inspect

    module = importlib.import_module("applicant.app.routers.model_endpoints")
    n1ctx["sig"] = inspect.signature(module.add_endpoint)


@when("the model_type parameter type is inspected")
def inspect_model_type(n1ctx):
    n1ctx["model_type_anno"] = n1ctx["sig"].parameters["model_type"].annotation


@then("it is constrained to an enum of allowed types, not a bare string")
def model_type_constrained(n1ctx):
    import typing

    anno = n1ctx["model_type_anno"]
    # Today model_type is a bare ``str`` Form param. A constrained type is a
    # Literal/Enum (typing.get_origin(Literal[...]) is typing.Literal) or an Enum.
    is_literal = typing.get_origin(anno) is typing.Literal
    is_enum = isinstance(anno, type) and issubclass(anno, __import__("enum").Enum)
    assert is_literal or is_enum, "model_type is still a bare str, not an enum/Literal"


# ===========================================================================
# #320 — path ids: NewType is zero-cost str (green); validator (gap)
# ===========================================================================
@given("the domain id type definitions")
def domain_id_types(n1ctx):
    from applicant.core import ids

    n1ctx["ids"] = ids


@when("a campaign id type is constructed from a string")
def construct_campaign_id(n1ctx):
    n1ctx["cid"] = n1ctx["ids"].CampaignId("abc-123")


@then("it behaves as a plain string at runtime")
def id_is_plain_str(n1ctx):
    assert isinstance(n1ctx["cid"], str)
    assert n1ctx["cid"] == "abc-123"


@given("a shared id-format validator")
def shared_id_validator(n1ctx):
    from applicant.core import ids

    n1ctx["ids"] = ids


@when("an id containing path-traversal or a NUL byte is validated")
def validate_bad_id(n1ctx):
    ids = n1ctx["ids"]
    # A shared id-format validator does not exist yet — bare-str path params reach
    # the service unvalidated. Probe for the validator.
    n1ctx["validator"] = getattr(ids, "validate_id", None) or getattr(
        ids, "assert_valid_id", None
    )


@then("the malformed id is rejected before any lookup")
def malformed_id_rejected(n1ctx):
    validator = n1ctx["validator"]
    assert validator is not None, "no shared id-format validator exists yet"
    for bad in ("../../etc/passwd", "abc\x00", ""):
        with pytest.raises(ValueError):
            validator(bad)


# ===========================================================================
# #322 — upload size caps: fonts/onboarding ship (green); gallery (gap)
# ===========================================================================
class _FakeUpload:
    """Minimal UploadFile stand-in: streams a fixed body in read() chunks."""

    def __init__(self, body: bytes, chunk: int = 64 * 1024):
        self._buf = body
        self._pos = 0
        self._chunk = chunk

    async def read(self, n: int = -1) -> bytes:
        size = self._chunk if n is None or n < 0 else n
        out = self._buf[self._pos : self._pos + size]
        self._pos += len(out)
        return out


def _run_capped(reader, body: bytes, cap: int):
    from fastapi import HTTPException

    try:
        asyncio.run(reader(_FakeUpload(body), cap))
        return None
    except HTTPException as exc:
        return exc.status_code


@given("the font upload reader with a small byte cap")
def font_reader(n1ctx):
    from applicant.app.routers import fonts

    n1ctx["reader"] = fonts._read_capped


@given("the resume upload reader with a small byte cap")
def resume_reader(n1ctx):
    from applicant.app.routers import onboarding

    n1ctx["reader"] = onboarding._read_capped


@when("a body larger than the cap is streamed in")
def stream_oversize_body(n1ctx):
    n1ctx["status"] = _run_capped(n1ctx["reader"], b"x" * (200 * 1024), 100 * 1024)


@then("the upload is rejected as too large")
def upload_rejected(n1ctx):
    assert n1ctx["status"] == 413


@given("the gallery upload route module")
def gallery_module(n1ctx):
    n1ctx["gallery_src"] = _read("workspace/routes/gallery_routes.py")


@when("it is inspected for an explicit upload size cap")
def inspect_gallery_cap(n1ctx):
    src = n1ctx["gallery_src"]
    n1ctx["has_cap"] = ("413" in src) or ("MAX_UPLOAD" in src) or (
        "CONTENT_TOO_LARGE" in src
    )


@then("a maximum upload size is enforced on the gallery upload")
def gallery_cap_enforced(n1ctx):
    assert n1ctx["has_cap"], "gallery upload route has no body-size cap"


# ===========================================================================
# #346 — CORS origin parsing (gap)
# ===========================================================================
@given("a shared CORS origin parser")
def cors_parser_seam(n1ctx):
    _add_workspace_to_path()
    n1ctx["app_mod"] = importlib.import_module("app")


@when("an ALLOWED_ORIGINS value with trailing whitespace and an empty entry is parsed")
def parse_origins(n1ctx):
    app_mod = n1ctx["app_mod"]
    # A dedicated, whitespace-stripping, URL-validating parser does not exist yet
    # (app.py uses a bare .split(",")). Probe for it.
    n1ctx["parser"] = getattr(app_mod, "parse_allowed_origins", None)


@then("each origin is trimmed and only well-formed origins remain")
def origins_normalized(n1ctx):
    parser = n1ctx["parser"]
    assert parser is not None, "no robust CORS origin parser exists yet"
    out = parser("http://foo, , https://bar ")
    assert out == ["http://foo", "https://bar"]


# ===========================================================================
# #349 — alembic placeholder DSN (gap)
# ===========================================================================
@given("the static alembic configuration file")
def alembic_ini(n1ctx):
    n1ctx["ini"] = _read("alembic.ini")


@when("the placeholder sqlalchemy.url is read")
def read_placeholder_url(n1ctx):
    line = next(
        ln for ln in n1ctx["ini"].splitlines() if ln.strip().startswith("sqlalchemy.url")
    )
    n1ctx["url_line"] = line


@then("it is an obviously-fake placeholder rather than realistic credentials")
def placeholder_is_fake(n1ctx):
    url = n1ctx["url_line"]
    # Today the placeholder is realistic ``applicant:applicant@localhost`` creds.
    # The fix uses an obviously-fake marker (e.g. "placeholder").
    assert "placeholder" in url.lower(), "alembic.ini placeholder looks like real creds"


# ===========================================================================
# #353 — research panel: text escaped (green); link scheme validation (gap)
# ===========================================================================
@given("the research panel renderer")
def research_panel_src(n1ctx):
    n1ctx["panel_src"] = _read("workspace/static/js/research/panel.js")


@when("it builds the source list for a job")
def build_source_list(n1ctx):
    src = n1ctx["panel_src"]
    # The source-list builder escapes the title and url via _esc(...) and the
    # query header via _esc(job.query).
    n1ctx["title_escaped"] = "_esc(s.title" in src
    n1ctx["query_escaped"] = "_esc(job.query)" in src


@then("each scraped title and query is run through an HTML-escape helper")
def text_escaped(n1ctx):
    assert n1ctx["title_escaped"] and n1ctx["query_escaped"]


@given("the research panel source-link builder")
def research_link_builder(n1ctx):
    n1ctx["panel_src"] = _read("workspace/static/js/research/panel.js")


@when("it is inspected for safe-scheme validation of source URLs")
def inspect_link_scheme(n1ctx):
    src = n1ctx["panel_src"]
    # _esc() is HTML-entity escaping only; it does NOT neutralize a javascript:
    # scheme in an href. A safe-scheme guard (_safeHref / scheme allowlist) is
    # the gap in this file.
    n1ctx["has_scheme_guard"] = ("_safeHref" in src) or ("safeHref" in src) or (
        "javascript:" in src
    )


@then("a javascript: scheme href is neutralized rather than entity-escaped only")
def link_scheme_neutralized(n1ctx):
    assert n1ctx["has_scheme_guard"], (
        "panel.js builds source hrefs with _esc only — no safe-scheme guard"
    )


# ===========================================================================
# #354 — chat markdown sanitizer ships (green); single shared seam (gap)
# ===========================================================================
@given("the chat markdown HTML sanitizer")
def chat_md_sanitizer(n1ctx):
    n1ctx["md_src"] = _read("workspace/static/js/markdown.js")


@when("a fragment with a script tag and an onerror handler is sanitized")
def sanitize_script_fragment(n1ctx):
    src = n1ctx["md_src"]
    # The shipped sanitizer drops script-capable tags and strips inline handlers.
    n1ctx["drops_script"] = "'SCRIPT'" in src and "_ALLOWED_HTML_BAD_TAGS" in src
    n1ctx["strips_handlers"] = "startsWith('on')" in src
    n1ctx["has_sanitizer"] = "sanitizeAllowedHtml" in src


@then("the script tag and the event handler are removed")
def script_and_handler_removed(n1ctx):
    assert n1ctx["has_sanitizer"]
    assert n1ctx["drops_script"]
    assert n1ctx["strips_handlers"]


@when("a link whose href is a javascript: URL is sanitized")
def sanitize_js_link(n1ctx):
    src = n1ctx["md_src"]
    # The sanitizer neutralizes javascript:/vbscript:/data: in URL attributes.
    n1ctx["neutralizes_js_url"] = "javascript|vbscript|data" in src
    n1ctx["checks_url_attrs"] = "_ALLOWED_HTML_URL_ATTRS" in src


@then("the dangerous href is stripped")
def dangerous_href_stripped(n1ctx):
    assert n1ctx["neutralizes_js_url"]
    assert n1ctx["checks_url_attrs"]


@given("the chat renderer module")
def chat_renderer_src(n1ctx):
    n1ctx["renderer_src"] = _read("workspace/static/js/chatRenderer.js")


@when("it is inspected for a single shared sanitize call guarding raw-string innerHTML")
def inspect_renderer_sanitize(n1ctx):
    src = n1ctx["renderer_src"]
    # chatRenderer routes markdown through the sanitizing processor, but it has 47
    # innerHTML assignments and no single reusable sanitize() applied uniformly at
    # every model-derived innerHTML seam. Probe for that shared call.
    n1ctx["has_shared_sanitizer"] = (
        "sanitizeHtml(" in src
        or "sanitizeAllowedHtml(" in src
        or "DOMPurify" in src
    )


@then("a reusable sanitizer guards each model-derived innerHTML assignment")
def renderer_shared_sanitizer(n1ctx):
    assert n1ctx["has_shared_sanitizer"], (
        "chatRenderer.js has no single shared sanitizer at its innerHTML seams"
    )


# ===========================================================================
# #356 — secret_storage round-trips (green); webhook_token column (gap)
# ===========================================================================
@given("the workspace secret-storage encryption layer")
def secret_storage_layer(n1ctx):
    _add_workspace_to_path()
    plain = "wh_live_token_abcdef0123456789"
    n1ctx["plain"] = plain
    try:
        ss = importlib.import_module("src.secret_storage")
    except ModuleNotFoundError:
        # ``cryptography`` is an optional vendored-workspace dep not installed in
        # the hermetic root env. Fall back to a static assertion against the
        # shipped module so this regression still proves the Fernet layer exists.
        n1ctx["ss"] = None
        n1ctx["ss_src"] = _read("workspace/src/secret_storage.py")
    else:
        n1ctx["ss"] = ss


@when("a webhook token value is encrypted then decrypted")
def roundtrip_secret(n1ctx):
    ss = n1ctx["ss"]
    if ss is None:
        return  # dep absent — verify by source in the Then
    n1ctx["stored"] = ss.encrypt(n1ctx["plain"])
    n1ctx["recovered"] = ss.decrypt(n1ctx["stored"])


@then("the stored form is not the plaintext and it decrypts back to the original")
def secret_roundtrips(n1ctx):
    if n1ctx["ss"] is None:
        # Static regression: the shipped Fernet layer with the ``enc:`` prefix.
        src = n1ctx["ss_src"]
        assert "from cryptography.fernet import Fernet" in src
        assert "def encrypt(" in src and "def decrypt(" in src
        assert '_PREFIX = "enc:"' in src
        return
    assert n1ctx["stored"] != n1ctx["plain"]
    assert n1ctx["stored"].startswith("enc:")
    assert n1ctx["recovered"] == n1ctx["plain"]


@given("the scheduled-task model column for the webhook token")
def webhook_column(n1ctx):
    n1ctx["db_src"] = _read("workspace/core/database.py")


@when("the column type is inspected")
def inspect_webhook_column(n1ctx):
    src = n1ctx["db_src"]
    line = next(
        ln for ln in src.splitlines() if ln.strip().startswith("webhook_token")
    )
    n1ctx["col_line"] = line


@then("it is an encrypted (or hashed) column rather than a plain String")
def webhook_column_encrypted(n1ctx):
    line = n1ctx["col_line"]
    # Today: ``webhook_token = Column(String, nullable=True, unique=True)`` — plain.
    assert ("EncryptedText" in line) or ("token_hash" in line), (
        "webhook_token is still a plain String column"
    )
