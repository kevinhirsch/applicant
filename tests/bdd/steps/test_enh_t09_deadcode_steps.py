"""Step bindings for the dead-code & asset-cleanup acceptance specs (T09).

Issues #253, #254, #255, #256, #257, #261, #262, #263, #264, #265, #270.

These are "X is dead / orphaned / unused" findings turned into cleanup acceptance
criteria. The pattern follows the canonical enhancement Gherkins:

* Scenarios with NO ``@pending`` tag are REAL coverage for the *current* state — they
  prove the canonical artifact is the one in use and/or that the duplicate/orphan exists
  today. They must pass now.
* Scenarios tagged ``@pending`` are the cleanup acceptance criteria: they assert the dead
  artifact has been REMOVED (or the consolidation has landed). Today the dead artifact
  still exists, so the assertion genuinely fails → ``conftest.pytest_bdd_apply_tag`` maps
  ``@pending`` to a non-strict xfail. When the cleanup ships, drop the tag and the
  scenario becomes a hard regression gate.

Everything here is filesystem/static analysis over the repo tree (read with pathlib
relative to the repo root) — no network, no DB, no browser. The cleanup theme is about
artifacts on disk, so the "seam" is the tree itself.
"""

from __future__ import annotations

import filecmp
import pathlib
import re

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_253_services_search_dup.feature",
    "../features/enhancements/enh_254_services_faces_dead.feature",
    "../features/enhancements/enh_255_mcp_common_orphan.feature",
    "../features/enhancements/enh_256_inter_fonts_unloaded.feature",
    "../features/enhancements/enh_257_calendar_reminders_orphan.feature",
    "../features/enhancements/enh_261_frontend_dir_deprecated.feature",
    "../features/enhancements/enh_262_workspace_fonts_partial.feature",
    "../features/enhancements/enh_263_oneshot_scripts_orphan.feature",
    "../features/enhancements/enh_264_applicant_modules_orphan.feature",
    "../features/enhancements/enh_265_style_css_bloat.feature",
    "../features/enhancements/enh_270_applicant_boilerplate_dup.feature",
)

# Repo root: this file is tests/bdd/steps/<this>.py → parents[3] is the repo root.
ROOT = pathlib.Path(__file__).resolve().parents[3]
WS = ROOT / "workspace"


@pytest.fixture
def t09ctx() -> dict:
    return {}


# --- small filesystem helpers ----------------------------------------------
def _py_files(base: pathlib.Path) -> list[pathlib.Path]:
    return [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def _grep_tree(base: pathlib.Path, needle: str, *, suffixes: tuple[str, ...]) -> list[pathlib.Path]:
    hits: list[pathlib.Path] = []
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix not in suffixes:
            continue
        if "__pycache__" in p.parts:
            continue
        if needle in _read(p):
            hits.append(p)
    return hits


# ===========================================================================
# #253 — services/search is a dead duplicate of src/search
# ===========================================================================
_SHARED_SEARCH_FILES = ("cache.py", "query.py", "ranking.py", "analytics.py")


@given("the workspace search packages")
def search_packages(t09ctx):
    t09ctx["src_search"] = WS / "src" / "search"
    t09ctx["svc_search"] = WS / "services" / "search"


@then("the canonical search package under src is importable by the app modules")
def canonical_src_search(t09ctx):
    src = t09ctx["src_search"]
    assert (src / "__init__.py").exists()
    # The live app modules import the src/search package, not the services copy.
    importers = _grep_tree(WS / "src", "src.search", suffixes=(".py",))
    importers += _grep_tree(WS / "src", "from src import search", suffixes=(".py",))
    assert importers, "expected app modules under src/ to import the canonical search package"


@then("the duplicate package is only reached from the search route")
def duplicate_only_route(t09ctx):
    # The services/search copy is reached from the search route (and the security
    # regression test that shadows it) — never from the live src/ app modules.
    src_importers = _grep_tree(WS / "src", "services.search", suffixes=(".py",))
    assert not src_importers, f"src/ app modules should not import the duplicate: {src_importers}"
    route = WS / "routes" / "search_routes.py"
    assert "services.search" in _read(route)


@when("the shared search files are compared between the two packages")
def compare_search_files(t09ctx):
    identical = []
    for name in _SHARED_SEARCH_FILES:
        a = t09ctx["src_search"] / name
        b = t09ctx["svc_search"] / name
        if a.exists() and b.exists() and filecmp.cmp(a, b, shallow=False):
            identical.append(name)
    t09ctx["identical_search"] = identical


@then("the cache, query, ranking and analytics files are duplicated verbatim")
def search_files_duplicated(t09ctx):
    assert set(t09ctx["identical_search"]) == set(_SHARED_SEARCH_FILES)


@then("the duplicated cache, query, ranking and analytics files no longer exist under services")
def search_dupes_removed(t09ctx):
    # Cleanup acceptance criterion: the dead duplicate files are gone.
    still_present = [n for n in _SHARED_SEARCH_FILES if (t09ctx["svc_search"] / n).exists()]
    assert still_present == [], f"duplicate search files still present: {still_present}"


# ===========================================================================
# #254 — services/faces package is entirely dead
# ===========================================================================
@given("the workspace source tree")
def workspace_tree(t09ctx):
    t09ctx["ws"] = WS


@when("every Python file is scanned for an import of the face package")
def scan_faces_imports(t09ctx):
    pat = re.compile(r"(?:^|\b)(?:from|import)\s+services\.faces|from\s+services\s+import\s+faces")
    hits = []
    for p in _py_files(WS):
        if (WS / "services" / "faces") in p.parents:
            continue
        if pat.search(_read(p)):
            hits.append(p)
    t09ctx["faces_importers"] = hits


@then("no file imports it")
def no_faces_importers(t09ctx):
    assert t09ctx["faces_importers"] == []


@then("the face package directory no longer exists")
def faces_removed(t09ctx):
    assert not (WS / "services" / "faces").exists()


# ===========================================================================
# #255 — mcp_servers/_common.py is orphaned
# ===========================================================================
_MCP_SERVERS = ("email_server.py", "memory_server.py", "rag_server.py", "image_gen_server.py")


@given("the built-in MCP servers")
def mcp_servers(t09ctx):
    t09ctx["mcp_dir"] = WS / "mcp_servers"


@when("each server module is scanned for an import of the shared helper")
def scan_common_imports(t09ctx):
    pat = re.compile(r"(?:from|import)\s+\.?_common|from\s+mcp_servers\._common")
    importers = []
    for name in _MCP_SERVERS:
        p = t09ctx["mcp_dir"] / name
        if p.exists() and pat.search(_read(p)):
            importers.append(name)
    t09ctx["common_importers"] = importers


@then("none of them import it")
def no_common_importers(t09ctx):
    assert t09ctx["common_importers"] == []


@then("the orphaned shared helper module no longer exists")
def common_removed(t09ctx):
    assert not (t09ctx["mcp_dir"] / "_common.py").exists()


# ===========================================================================
# #256 / #262 — Inter fonts (loaded via shell) + dead GohuFont bitmap
# ===========================================================================
@given("the served workspace shell and its styles")
def shell_and_styles(t09ctx):
    t09ctx["index"] = WS / "static" / "index.html"
    t09ctx["style"] = WS / "static" / "style.css"


@then("the Inter font family is declared with a face for each shipped Inter file")
def inter_faces_declared(t09ctx):
    html = _read(t09ctx["index"])
    # The served shell declares @font-face for the Inter family — so the browser fetches
    # the woff2 files; they are NOT dead. One face per shipped Inter variant.
    for variant in ("Inter-Regular.woff2", "Inter-Medium.woff2", "Inter-SemiBold.woff2"):
        assert variant in html, f"{variant} should be referenced by an @font-face in the shell"
    assert "@font-face" in html and "'Inter'" in html


@then("the Inter family is named in the CSS font stacks")
def inter_in_stacks(t09ctx):
    css = _read(t09ctx["style"])
    assert re.search(r"font-family:\s*'Inter'", css)


@given("the workspace font directory")
def font_dir(t09ctx):
    t09ctx["fonts"] = WS / "static" / "fonts"


@then("the unreferenced bitmap font file no longer exists")
def gohu_removed(t09ctx):
    fonts = t09ctx.get("fonts", WS / "static" / "fonts")
    assert not (fonts / "custom" / "GohuFont.ttf").exists()


# --- #262 stylesheet face declarations + GohuFont unreferenced --------------
@given("the workspace main stylesheet")
def main_stylesheet(t09ctx):
    t09ctx["style"] = WS / "static" / "style.css"


@then("it declares a font face for each FiraCode file it ships")
def firacode_faces(t09ctx):
    css = _read(t09ctx["style"])
    for variant in ("FiraCode-Light.woff2", "FiraCode-Regular.woff2", "FiraCode-SemiBold.woff2"):
        assert variant in css and "@font-face" in css


@when("the tree is scanned for any reference to the bitmap font file")
def scan_gohu(t09ctx):
    # Any textual reference to the bitmap font, excluding the binary file itself.
    hits = []
    for p in WS.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        if p.suffix in (".css", ".js", ".html", ".py"):
            if "GohuFont" in _read(p):
                hits.append(p)
    t09ctx["gohu_refs"] = hits


@then("nothing references it")
def nothing_refs_gohu(t09ctx):
    assert t09ctx["gohu_refs"] == []


# ===========================================================================
# #257 — calendar/reminders.js is orphaned
# ===========================================================================
@given("the workspace browser modules")
def browser_modules(t09ctx):
    t09ctx["js"] = WS / "static" / "js"


@when("every module is scanned for an import of the calendar reminders module")
def scan_reminders_imports(t09ctx):
    js = t09ctx["js"]
    pat = re.compile(r"""(?:from|import)\s*\(?\s*['"][^'"]*calendar/reminders(?:\.js)?['"]""")
    hits = []
    for p in js.rglob("*.js"):
        if p == js / "calendar" / "reminders.js":
            continue
        if pat.search(_read(p)):
            hits.append(p)
    # Also check the served shell does not pull it in.
    if pat.search(_read(WS / "static" / "index.html")):
        hits.append(WS / "static" / "index.html")
    t09ctx["reminders_importers"] = hits


@then("no module imports it")
def no_reminders_importers(t09ctx):
    assert t09ctx["reminders_importers"] == []


@then("the calendar module imports only its own utilities helper")
def calendar_imports_utils(t09ctx):
    cal = _read(t09ctx["js"] / "calendar.js")
    assert "calendar/utils.js" in cal
    assert "calendar/reminders" not in cal


@then("the notes module contains the reminder scheduling logic")
def notes_owns_reminders(t09ctx):
    notes = _read(t09ctx["js"] / "notes.js")
    # The live reminder loop/scheduling lives here, not in the orphaned module.
    assert "_reminderTimer" in notes
    assert "REMINDER_FIRED_KEY" in notes


@then("the orphaned calendar reminders module no longer exists")
def reminders_removed(t09ctx):
    assert not (t09ctx["js"] / "calendar" / "reminders.js").exists()


# ===========================================================================
# #261 — frontend/ directory deprecated and not served
# ===========================================================================
@given("the workspace application module")
def workspace_app(t09ctx):
    t09ctx["app_py"] = WS / "app.py"
    t09ctx["routes"] = WS / "routes"


@then("it mounts only its own static directory")
def mounts_own_static(t09ctx):
    app = _read(t09ctx["app_py"])
    assert 'directory="static"' in app


@then("it never mounts or routes to the deprecated frontend directory")
def no_frontend_mount(t09ctx):
    app = _read(t09ctx["app_py"])
    # No StaticFiles mount or directory= pointing at the sibling frontend/ tree.
    assert 'directory="frontend' not in app
    assert "../frontend" not in app
    for p in t09ctx["routes"].rglob("*.py"):
        text = _read(p)
        assert "../frontend" not in text and 'directory="frontend' not in text


@given("the deprecated frontend directory")
def frontend_dir(t09ctx):
    t09ctx["frontend"] = ROOT / "frontend"


@when("its font files are compared with the workspace font files")
def compare_frontend_fonts(t09ctx):
    fe = t09ctx["frontend"] / "static" / "fonts"
    ws = WS / "static" / "fonts"
    identical = []
    for p in fe.glob("*.woff2"):
        twin = ws / p.name
        if twin.exists() and filecmp.cmp(p, twin, shallow=False):
            identical.append(p.name)
    t09ctx["dup_fonts"] = identical


@then("they are byte-identical duplicates")
def fonts_are_dupes(t09ctx):
    # At least the shared families are exact duplicates wasting space.
    assert len(t09ctx["dup_fonts"]) >= 3, f"expected duplicate fonts, found {t09ctx['dup_fonts']}"


@then("it contains applicant modules that do not exist in the workspace")
def frontend_unique_modules(t09ctx):
    fe_js = {p.name for p in (t09ctx["frontend"]).rglob("applicant*.js")}
    ws_js = {p.name for p in (WS / "static" / "js").rglob("applicant*.js")}
    orphan_only = fe_js - ws_js
    assert orphan_only, "expected frontend-only applicant modules with no workspace counterpart"


@then("the deprecated frontend directory no longer exists")
def frontend_removed(t09ctx):
    assert not (ROOT / "frontend").exists()


# ===========================================================================
# #263 — one-shot scripts with zero cross-references
# ===========================================================================
_ONESHOT_SCRIPTS = (
    "fix_paths.py",
    "index_documents.py",
    "migrate_faiss_to_chroma.py",
    "update_database.py",
    "add_hwfit_models.py",
)


@given("the workspace scripts directory")
def scripts_dir(t09ctx):
    t09ctx["scripts"] = WS / "scripts"


@then("the five one-shot tools are present on disk")
def oneshot_tools_present(t09ctx):
    # The cleanup targets are concrete files that exist today.
    missing = [n for n in _ONESHOT_SCRIPTS if not (t09ctx["scripts"] / n).exists()]
    assert missing == [], f"expected one-shot tools on disk, missing: {missing}"


@when("each one-shot tool is scanned for references across the project")
def scan_oneshot_refs(t09ctx):
    refs: dict[str, list[str]] = {}
    for name in _ONESHOT_SCRIPTS:
        hits = []
        for p in WS.rglob("*"):
            if not p.is_file() or "__pycache__" in p.parts:
                continue
            if p.suffix not in (".py", ".sh", ".md", ".yml", ".yaml", ".toml"):
                continue
            if p == WS / "scripts" / name:
                continue
            if name in _read(p):
                hits.append(str(p.relative_to(WS)))
        refs[name] = hits
    t09ctx["oneshot_refs"] = refs


@then("none of them are referenced anywhere")
def oneshot_unreferenced(t09ctx):
    referenced = {k: v for k, v in t09ctx["oneshot_refs"].items() if v}
    assert referenced == {}, f"unexpected references to one-shot tools: {referenced}"


@then("the orphaned one-shot tools no longer exist")
def oneshot_removed(t09ctx):
    still = [n for n in _ONESHOT_SCRIPTS if (t09ctx["scripts"] / n).exists()]
    assert still == [], f"one-shot tools still present: {still}"


# ===========================================================================
# #264 — applicantPortal / applicantActivity / applicantUpdate orphaned
# ===========================================================================
_SUSPECT_MODULES = ("applicantPortal.js", "applicantActivity.js", "applicantUpdate.js")


@given("the served workspace shell")
def served_shell(t09ctx):
    t09ctx["index"] = WS / "static" / "index.html"


@when("the module script tags are read")
def read_script_tags(t09ctx):
    html = _read(t09ctx["index"])
    # Only <script type="module" src=...> tags actually load a module on page load.
    t09ctx["script_srcs"] = set(re.findall(r'<script[^>]+src="([^"]+)"', html))


@then("none of them load the portal, activity or update module")
def script_tags_skip_suspects(t09ctx):
    loaded = " ".join(t09ctx["script_srcs"])
    for name in _SUSPECT_MODULES:
        assert name not in loaded, f"{name} is loaded by a script tag after all"


@given("the applicant browser modules")
def applicant_modules(t09ctx):
    t09ctx["js"] = WS / "static" / "js"


@when("the loaded modules are scanned for imports of the three suspect modules")
def scan_suspect_imports(t09ctx):
    js = t09ctx["js"]
    # Modules that ARE loaded by a script tag (the reachable roots) plus everything they
    # could pull in: scan ALL applicant modules for a STATIC/dynamic import of a suspect.
    importers: dict[str, list[str]] = {n: [] for n in _SUSPECT_MODULES}
    for name in _SUSPECT_MODULES:
        stem = name[:-3]  # drop .js
        pat = re.compile(
            r"""(?:from|import)\s*\(?\s*['"][^'"]*""" + re.escape(stem) + r"""(?:\.js)?['"]"""
        )
        for p in js.glob("*.js"):
            if p.name == name:
                continue
            if pat.search(_read(p)):
                importers[name].append(p.name)
    t09ctx["suspect_importers"] = importers


@then("none of them import the portal, activity or update module")
def no_suspect_importers(t09ctx):
    offenders = {k: v for k, v in t09ctx["suspect_importers"].items() if v}
    assert offenders == {}, f"suspect modules are statically imported: {offenders}"


@then("the orphaned portal, activity and update modules no longer exist")
def suspects_removed(t09ctx):
    js = t09ctx["js"]
    still = [n for n in _SUSPECT_MODULES if (js / n).exists()]
    assert still == [], f"orphaned modules still present: {still}"


# ===========================================================================
# #265 — 1.1MB style.css likely contains substantial dead CSS
# ===========================================================================
_ONE_MB = 1_000_000
# Conservative post-audit ceiling: even a modest 20% trim of a ~1.1MB sheet lands under
# this. The @pending scenario fails today (sheet is well over a megabyte).
_POST_AUDIT_CEILING = 900_000


@then("it is larger than one megabyte")
def style_over_mb(t09ctx):
    size = (WS / "static" / "style.css").stat().st_size
    t09ctx["style_size"] = size
    assert size > _ONE_MB


@then("it is smaller than the post-audit size ceiling")
def style_under_ceiling(t09ctx):
    size = (WS / "static" / "style.css").stat().st_size
    assert size < _POST_AUDIT_CEILING, f"style.css is {size} bytes; still above the audit ceiling"


# ===========================================================================
# #270 — _fetchJSON / esc / _toast duplicated across applicant modules
# ===========================================================================
@when("the modules are scanned for their own copy of the shared helpers")
def scan_boilerplate(t09ctx):
    js = t09ctx["js"]
    fetch_dupes = []
    esc_dupes = []
    fetch_def = re.compile(r"(?:async\s+)?function\s+_fetchJSON\s*\(")
    esc_def = re.compile(r"function\s+esc\s*\(")
    for p in sorted(js.glob("applicant*.js")):
        text = _read(p)
        if fetch_def.search(text):
            fetch_dupes.append(p.name)
        if esc_def.search(text):
            esc_dupes.append(p.name)
    t09ctx["fetch_dupes"] = fetch_dupes
    t09ctx["esc_dupes"] = esc_dupes


@then("many modules define their own identical copies")
def boilerplate_duplicated(t09ctx):
    # The duplication is rampant today — far more than a couple of modules carry copies.
    assert len(t09ctx["fetch_dupes"]) >= 5, t09ctx["fetch_dupes"]
    assert len(t09ctx["esc_dupes"]) >= 5, t09ctx["esc_dupes"]


@then("there is no shared applicant core helper module today")
def no_core_module(t09ctx):
    assert not (t09ctx["js"] / "applicantCore.js").exists()


@then("a shared applicant core helper module exists")
def core_module_exists(t09ctx):
    assert (t09ctx["js"] / "applicantCore.js").exists()


@then("the other applicant modules import the shared helpers from it")
def modules_import_core(t09ctx):
    js = t09ctx["js"]
    pat = re.compile(r"""(?:from|import)\s*\(?\s*['"][^'"]*applicantCore(?:\.js)?['"]""")
    importers = [
        p.name
        for p in js.glob("applicant*.js")
        if p.name != "applicantCore.js" and pat.search(_read(p))
    ]
    # The cleanup is meaningful only when most modules actually consume the shared core.
    assert len(importers) >= 5, f"too few modules import the shared core: {importers}"
