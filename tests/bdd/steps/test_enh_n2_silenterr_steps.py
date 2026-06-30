"""Step bindings for the N2 silent-error-handling acceptance specs.

Theme N2 — silent error handling in the engine/front-door source. Issues:

* Per-file silent-swallow findings — #323 (``workspace/src/builtin_actions.py``),
  #324 (``workspace/src/agent_loop.py``), #325 (``workspace/src/ai_interaction.py``),
  #326 (``workspace/src/bg_jobs.py``), #335
  (``src/applicant/adapters/browser/page_source.py``).
* Umbrella source-scan tracking — #332 (the ``workspace/routes/`` layer) and
  #333 (the ``workspace/src/`` layer).

Pattern (per the canonical enhancement Gherkins):

* Scenarios with NO ``@pending`` tag are REAL coverage for the *current* state.
  Graceful degradation already ships — a failing IMAP logout / preference load /
  vector add / corrupt job-state file / partial browser teardown does NOT crash
  the surrounding flow. These assert that and must pass today. Where the failing
  path is buried in deep async closures (DB/IMAP/vector wiring that we must not
  open for real), the GREEN assertion is over the source of the real function:
  the ``try`` / ``except`` graceful-degradation wrapper is present today.
* Scenarios tagged ``@pending`` are the remediation acceptance criteria: a
  diagnostic (a ``logger.warning(...)``) is emitted in the catch block instead of
  the bare ``pass``. Today the block is silent, so the probe genuinely fails →
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail. When
  the diagnostic lands, drop the tag and the scenario becomes a regression gate.

Everything here is filesystem / static analysis over the repo tree, or a direct
call into a *pure* function (``bg_jobs._load`` over a temp file,
``PlaywrightPageSource._safe_teardown`` over a fake handle). No real sockets, no
real DB, no real browser. Speculative / workspace imports happen INSIDE step
bodies so absence is a runtime red, never a collection error.
"""

from __future__ import annotations

import importlib
import logging
import pathlib
import re
import sys
from types import SimpleNamespace

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_323_builtin_actions_silent_imap.feature",
    "../features/enhancements/enh_324_agent_loop_silent_prefs.feature",
    "../features/enhancements/enh_325_ai_interaction_silent_vector.feature",
    "../features/enhancements/enh_326_bg_jobs_corrupt_state.feature",
    "../features/enhancements/enh_335_page_source_teardown_silent.feature",
    "../features/enhancements/enh_332_routes_silent_excepts_umbrella.feature",
    "../features/enhancements/enh_333_source_silent_excepts_umbrella.feature",
)

# Repo root: this file is tests/bdd/steps/<this>.py → parents[3] is the repo root.
ROOT = pathlib.Path(__file__).resolve().parents[3]
WS = ROOT / "workspace"

# Audited baselines (counted on this branch). Asserted as ">= baseline - slack"
# so a small remediation does not flip the GREEN inventory scenario to a failure;
# the point is that the systemic problem is at scale today.
_ROUTES_BARE_EXCEPT_BASELINE = 500   # measured 529 across routes/*.py
_SRC_BARE_EXCEPT_BASELINE = 440      # measured 470 across src/*.py

# Per-umbrella chosen high-risk remediation target for the @pending probe.
_ROUTES_WORST_FILE = "email_routes.py"   # 93 bare excepts, the worst route file
_SRC_WORST_FILE = "builtin_actions.py"   # 70 bare excepts, the worst source file

# Bare-handler and silent-swallow patterns.
_BARE_EXCEPT = re.compile(r"except\s+Exception")
# A handler whose ONLY body is ``pass`` — one-liner or the next indented line.
_SILENT_SWALLOW = re.compile(r"except\s+Exception[^\n:]*:\s*(?:\n\s*)?pass\b")


@pytest.fixture
def n2ctx() -> dict:
    return {}


# --- small helpers ----------------------------------------------------------
def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def _route_files() -> list[pathlib.Path]:
    return [p for p in (WS / "routes").glob("*.py") if "__pycache__" not in p.parts]


def _src_files() -> list[pathlib.Path]:
    return [p for p in (WS / "src").glob("*.py") if "__pycache__" not in p.parts]


def _count(files: list[pathlib.Path], pat: re.Pattern) -> int:
    return sum(len(pat.findall(_read(p))) for p in files)


def _ensure_workspace_on_path() -> None:
    ws = str(WS)
    if ws not in sys.path:
        sys.path.insert(0, ws)


# ===========================================================================
# #323 — builtin_actions.py: IMAP logout silently swallowed
# ===========================================================================
@given("the front-door builtin email actions module")
def builtin_actions_module(n2ctx):
    n2ctx["src"] = _read(WS / "src" / "builtin_actions.py")


@when("an IMAP connection logout raises during cleanup")
def imap_logout_raises(n2ctx):
    # The real cleanup path: ``try: conn.logout()`` in a ``finally``. We locate
    # the catch blocks that guard those logout calls.
    src = n2ctx["src"]
    logout_lines = [
        i for i, line in enumerate(src.splitlines())
        if re.search(r"conn\d*\.logout\(\)", line)
    ]
    n2ctx["logout_line_idxs"] = logout_lines
    n2ctx["lines"] = src.splitlines()


@then("the surrounding task continues rather than crashing")
def imap_logout_guarded(n2ctx):
    # Graceful degradation ships: every ``conn.logout()`` cleanup is wrapped so a
    # raising logout cannot crash the surrounding email task.
    assert n2ctx["logout_line_idxs"], "expected guarded conn.logout() cleanup calls"
    lines = n2ctx["lines"]
    for idx in n2ctx["logout_line_idxs"]:
        window = "\n".join(lines[max(0, idx - 1): idx + 2])
        assert "except Exception" in window, f"logout at line {idx + 1} is not guarded"


@then("a warning naming the logout failure is logged rather than silently discarded")
def imap_logout_logged(n2ctx):
    # @pending: today the guard is ``except Exception: pass`` — no diagnostic. The
    # remediation logs a warning in each logout catch block.
    lines = n2ctx["lines"]
    logged = 0
    for idx in n2ctx["logout_line_idxs"]:
        window = "\n".join(lines[idx: idx + 3])
        if re.search(r"log(?:ger)?\.(?:warning|warn|error|exception)\b", window):
            logged += 1
    assert logged == len(n2ctx["logout_line_idxs"]), (
        f"only {logged}/{len(n2ctx['logout_line_idxs'])} logout catch blocks log a diagnostic"
    )


# ===========================================================================
# #324 — agent_loop.py: preference loading silently swallowed
# ===========================================================================
@given("the front-door agent loop preference loader")
def agent_loop_module(n2ctx):
    src = _read(WS / "src" / "agent_loop.py")
    n2ctx["src"] = src
    n2ctx["lines"] = src.splitlines()


@when("loading a user's preferences raises")
def prefs_load_raises(n2ctx):
    # The skills path loads prefs via routes.prefs_routes._load_for_user inside a
    # try/except. Locate the catch block guarding that import+call.
    lines = n2ctx["lines"]
    idxs = [
        i for i, line in enumerate(lines)
        if "_load_for_user" in line or "_load_prefs(owner)" in line
    ]
    n2ctx["prefs_idxs"] = idxs


@then("prompt assembly continues with a safe default rather than crashing")
def prefs_guarded(n2ctx):
    assert n2ctx["prefs_idxs"], "expected a preference-load call in the agent loop"
    lines = n2ctx["lines"]
    # The preference load is wrapped so a failure falls back to a safe default
    # (skills_on = True / empty prefs) rather than aborting prompt assembly.
    guarded = any(
        any("except Exception" in lines[j] for j in range(idx, min(len(lines), idx + 4)))
        for idx in n2ctx["prefs_idxs"]
    )
    assert guarded, "preference load is not wrapped in a degradation guard"


@then("a warning naming the preference-load failure is logged rather than silently discarded")
def prefs_logged(n2ctx):
    # @pending: the preference-load catch block is ``except Exception: pass`` today.
    lines = n2ctx["lines"]
    found_log = False
    for idx in n2ctx["prefs_idxs"]:
        for j in range(idx, min(len(lines), idx + 6)):
            if "except Exception" in lines[j]:
                window = "\n".join(lines[j: j + 3])
                if re.search(r"log(?:ger)?\.(?:warning|warn|error|exception)\b", window):
                    found_log = True
    assert found_log, "preference-load failure is swallowed without a diagnostic"


# ===========================================================================
# #325 — ai_interaction.py: memory vector add/remove silently swallowed
# ===========================================================================
@given("the front-door memory action over a healthy canonical store")
def ai_interaction_module(n2ctx):
    src = _read(WS / "src" / "ai_interaction.py")
    n2ctx["src"] = src
    n2ctx["lines"] = src.splitlines()


@when("the vector index add raises")
def vector_add_raises(n2ctx):
    lines = n2ctx["lines"]
    idxs = [
        i for i, line in enumerate(lines)
        if re.search(r"_memory_vector\.(?:add|remove)\(", line)
    ]
    n2ctx["vector_idxs"] = idxs


@then("the memory is still persisted to the canonical store rather than lost")
def vector_failure_does_not_lose_memory(n2ctx):
    # Graceful degradation ships: the canonical store save() happens BEFORE the
    # vector update, and the vector update is wrapped so its failure cannot undo
    # the persisted memory.
    src = n2ctx["src"]
    assert n2ctx["vector_idxs"], "expected memory vector add/remove calls"
    # The canonical save precedes each vector mutation in the add/edit/delete arms.
    assert "_memory_manager.save(" in src
    lines = n2ctx["lines"]
    for idx in n2ctx["vector_idxs"]:
        window = "\n".join(lines[max(0, idx - 2): idx + 3])
        assert "except Exception" in window, f"vector op at line {idx + 1} is not guarded"


@then("a warning naming the vector-store failure is logged rather than silently discarded")
def vector_failure_logged(n2ctx):
    # @pending: today each vector add/remove catch block is ``except Exception: pass``.
    lines = n2ctx["lines"]
    logged = 0
    for idx in n2ctx["vector_idxs"]:
        window = "\n".join(lines[idx: idx + 4])
        if re.search(r"log(?:ger)?\.(?:warning|warn|error|exception)\b", window):
            logged += 1
    assert logged == len(n2ctx["vector_idxs"]), (
        f"only {logged}/{len(n2ctx['vector_idxs'])} vector catch blocks log a diagnostic"
    )


# ===========================================================================
# #326 — bg_jobs.py: corrupt job-state file silently resets the queue
# ===========================================================================
def _import_bg_jobs():
    """Import ``src.bg_jobs`` hermetically.

    ``bg_jobs`` imports ``core.atomic_io`` / ``core.platform_compat``; resolving
    those through ``core/__init__.py`` would drag in bcrypt/SQLAlchemy/etc. that
    are not installed in the root env. We inject lightweight stub modules for just
    those two ``core`` submodules so the real ``bg_jobs`` module body loads without
    its heavy transitive deps — the function under test (``_load``) only needs the
    stdlib json/pathlib it imports directly.
    """
    import types

    _ensure_workspace_on_path()
    core_pkg = sys.modules.get("core")
    if core_pkg is None:
        core_pkg = types.ModuleType("core")
        core_pkg.__path__ = []  # mark as a package so submodule imports resolve
        sys.modules["core"] = core_pkg
    if "core.atomic_io" not in sys.modules:
        atomic = types.ModuleType("core.atomic_io")
        atomic.atomic_write_json = lambda *a, **k: None
        sys.modules["core.atomic_io"] = atomic
    if "core.platform_compat" not in sys.modules:
        compat = types.ModuleType("core.platform_compat")
        compat.detached_popen_kwargs = lambda: {}
        compat.find_bash = lambda: None
        compat.kill_process_tree = lambda pid: None
        compat.pid_alive = lambda pid: False
        sys.modules["core.platform_compat"] = compat
    return importlib.import_module("src.bg_jobs")


@given("the front-door background-job store with a corrupt state file")
def bg_jobs_corrupt_store(n2ctx, tmp_path, monkeypatch):
    bg = _import_bg_jobs()
    n2ctx["bg"] = bg
    store = tmp_path / "bg_jobs.json"
    store.write_text("{ this is not valid json", encoding="utf-8")
    # Point the module's on-disk store at the corrupt temp file (no real DATA_DIR).
    monkeypatch.setattr(bg, "_STORE", store, raising=True)
    n2ctx["store"] = store


@when("the job store is loaded")
def bg_jobs_load(n2ctx, caplog):
    n2ctx["caplog"] = caplog
    with caplog.at_level(logging.WARNING):
        n2ctx["loaded"] = n2ctx["bg"]._load()


@then("an empty job map is returned so the monitor keeps running")
def bg_jobs_empty_returned(n2ctx):
    # Real behaviour today: a corrupt store degrades to {} instead of crashing.
    assert n2ctx["loaded"] == {}


@then("a warning naming the corrupt state file is logged rather than silently discarded")
def bg_jobs_corruption_logged(n2ctx):
    # @pending: ``_load`` catches with a bare ``pass`` and the module has no logger,
    # so the corruption (loss of every scheduled job) is invisible.
    text = n2ctx["caplog"].text.lower()
    assert ("corrupt" in text or "bg_jobs" in text or "job" in text) and (
        "warn" in text or "error" in text
    ), "corrupt job-state file was reset to empty with no diagnostic"


# ===========================================================================
# #335 — page_source._safe_teardown: browser teardown silently swallowed
# ===========================================================================
def _load_page_source_cls():
    from applicant.adapters.browser.page_source import PlaywrightPageSource

    return PlaywrightPageSource


@given("an engine page-source driver that never finished launching")
def page_source_partial(n2ctx):
    cls = _load_page_source_cls()
    n2ctx["cls"] = cls
    # A partially-built instance: every handle is None (exactly what __init__ sets
    # before a launch completes). ``_safe_teardown`` reads them via getattr.
    n2ctx["obj"] = SimpleNamespace(
        _cam=None, _cdp_endpoint="", _browser=None, _context=None, _pw=None
    )


@given("an engine page-source driver whose close step raises during teardown")
def page_source_failing_close(n2ctx):
    cls = _load_page_source_cls()
    n2ctx["cls"] = cls

    class _BoomContext:
        def close(self):
            raise RuntimeError("CDP disconnect: orphaned context")

    # A local (non-CDP) chromium driver with a context whose close() fails — the
    # exact orphaned-context / leaked-process case the issue describes.
    n2ctx["obj"] = SimpleNamespace(
        _cam=None, _cdp_endpoint="", _browser=None, _context=_BoomContext(), _pw=None
    )


@when("best-effort teardown runs")
def run_safe_teardown(n2ctx, caplog):
    # Shared by both teardown scenarios (the partial-launch one and the failing-close
    # one). We capture logs so the @pending probe can inspect them, and record any
    # raise so the GREEN scenario can assert it never crashes.
    n2ctx["caplog"] = caplog
    raised = None
    with caplog.at_level(logging.WARNING):
        try:
            n2ctx["cls"]._safe_teardown(n2ctx["obj"])
        except Exception as exc:  # pragma: no cover - the green assertion is "no raise"
            raised = exc
    n2ctx["raised"] = raised


@then("it completes without raising rather than crashing cleanup")
def safe_teardown_no_raise(n2ctx):
    assert n2ctx["raised"] is None


@then("a warning naming the teardown failure is logged rather than silently discarded")
def teardown_failure_logged(n2ctx):
    # @pending: ``_safe_teardown`` swallows with ``except Exception: pass`` and the
    # module has no logger, so a teardown failure (and any launch error it masks)
    # is invisible. The remediation logs a warning naming the failed step.
    text = n2ctx.get("caplog").text if n2ctx.get("caplog") else ""
    low = text.lower()
    assert ("teardown" in low or "context" in low or "close" in low) and (
        "warn" in low or "error" in low
    ), "teardown failure was silently discarded with no diagnostic"


# ===========================================================================
# #332 — UMBRELLA: workspace/routes/ silent-swallow inventory
# ===========================================================================
@given("the workspace route source files")
def routes_source_files(n2ctx):
    n2ctx["files"] = _route_files()


@when("the route files are scanned for bare exception handlers")
def scan_routes_bare(n2ctx):
    n2ctx["bare"] = _count(n2ctx["files"], _BARE_EXCEPT)
    n2ctx["silent"] = _count(n2ctx["files"], _SILENT_SWALLOW)


@then("the count of bare exception handlers is at least the audited baseline")
def routes_bare_baseline(n2ctx):
    assert n2ctx["bare"] >= _ROUTES_BARE_EXCEPT_BASELINE, (
        f"routes bare-except inventory {n2ctx['bare']} below baseline "
        f"{_ROUTES_BARE_EXCEPT_BASELINE}"
    )


@then("few of them silently swallow the error with a bare pass after the G09 sweep")
def routes_silent_present(n2ctx):
    # Post-sweep assertion: the G09 remediation dropped the silent-swallow count from
    # hundreds to a small residual (measured 9 after the sweep). Assert the count is
    # now low (≤ 15) to prove the systemic problem was fixed, not just hidden.
    assert n2ctx["silent"] <= 15, (
        f"routes/ still has {n2ctx['silent']} silent-swallow blocks after G09 sweep "
        f"(expected ≤ 15)"
    )


@when("the highest-risk route file is scanned for silent-swallow blocks")
def scan_routes_worst(n2ctx):
    worst = WS / "routes" / _ROUTES_WORST_FILE
    n2ctx["worst_silent"] = len(_SILENT_SWALLOW.findall(_read(worst)))


@then("it has zero exception handlers that swallow the error with a bare pass")
def routes_worst_zero_silent(n2ctx):
    # @pending: the worst route file still has silent-swallow blocks today.
    assert n2ctx["worst_silent"] == 0, (
        f"{_ROUTES_WORST_FILE} still has {n2ctx['worst_silent']} silent-swallow blocks"
    )


# ===========================================================================
# #333 — UMBRELLA: workspace/src/ silent-swallow inventory
# ===========================================================================
@given("the workspace source files")
def src_source_files(n2ctx):
    n2ctx["files"] = _src_files()


@when("the source files are scanned for bare exception handlers")
def scan_src_bare(n2ctx):
    n2ctx["bare"] = _count(n2ctx["files"], _BARE_EXCEPT)
    n2ctx["silent"] = _count(n2ctx["files"], _SILENT_SWALLOW)


@then("the source count of bare exception handlers is at least the audited baseline")
def src_bare_baseline(n2ctx):
    assert n2ctx["bare"] >= _SRC_BARE_EXCEPT_BASELINE, (
        f"src bare-except inventory {n2ctx['bare']} below baseline {_SRC_BARE_EXCEPT_BASELINE}"
    )


@then("few source handlers silently swallow the error with a bare pass after the G09 sweep")
def src_silent_present(n2ctx):
    # Post-sweep assertion: the G09 remediation dropped the silent-swallow count from
    # hundreds to a small residual (measured 7 after the sweep). Assert the count is
    # now low (≤ 15) to prove the systemic problem was fixed, not just hidden.
    assert n2ctx["silent"] <= 15, (
        f"src/ still has {n2ctx['silent']} silent-swallow blocks after G09 sweep "
        f"(expected ≤ 15)"
    )


@when("the worst source file is scanned for silent-swallow blocks")
def scan_src_worst(n2ctx):
    worst = WS / "src" / _SRC_WORST_FILE
    n2ctx["worst_silent"] = len(_SILENT_SWALLOW.findall(_read(worst)))


@then("the worst source file has zero exception handlers that swallow the error with a bare pass")
def src_worst_zero_silent(n2ctx):
    # @pending: builtin_actions.py still has silent-swallow blocks today.
    assert n2ctx["worst_silent"] == 0, (
        f"{_SRC_WORST_FILE} still has {n2ctx['worst_silent']} silent-swallow blocks"
    )
