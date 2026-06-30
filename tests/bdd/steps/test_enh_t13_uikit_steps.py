"""Step bindings for the FR-UIKIT component-kit migration specs (theme T13).

Tracks the epic #458 backlog (issues #459–#486): vendor the upstream window kit's
component kits (Foundation / Elements / Window / Notice / Gadget / Decision / Chat Hint)
and map them, drop-in, onto every visible front-door surface.

Convention (mirrors ``test_enh_t08_frontend_steps.py``):

* The un-tagged scenario per feature pins the **pre-migration baseline** — a structural
  fact that ships TODAY (the surface module exists, the overlapping primitive exists, the
  CI denylist / node-check gate exists, the Compare section is present-but-disabled). It
  must pass on this branch.
* The ``@pending`` scenario probes the **migration target** — the vendored ``appkit*``
  module is present and/or the surface markup references the kit's ``.ow-/.on-/.og-/.odec-``
  classes. These are genuine reds today (no ``assert True``); ``conftest.pytest_bdd_apply_tag``
  maps ``@pending`` to a non-strict xfail. When a surface's PR lands the kit, its tag is
  dropped and the scenario becomes a hard regression gate.

All probes are coarse structural facts read off the real repo tree — no browser is
launched and no socket is opened. The probe table lives in :mod:`uikit_registry`.
"""

from __future__ import annotations

import importlib
import pathlib
import sys

import pytest
from pytest_bdd import given, parsers, scenarios, then

# Import the shared item registry (sibling helper module, not a test module).
_STEPS_DIR = pathlib.Path(__file__).resolve().parent
if str(_STEPS_DIR) not in sys.path:
    sys.path.insert(0, str(_STEPS_DIR))
from uikit_registry import ITEMS  # noqa: E402

# Repo root: tests/bdd/steps/<this file> -> parents[3] is the repo root.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
STATIC = REPO_ROOT / "workspace" / "static"
STYLE_CSS = STATIC / "style.css"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Bind every generated feature to this step module.
scenarios(*[str(REPO_ROOT / "tests" / "bdd" / "features" / "enhancements" / f"uikit_{k}.feature") for k in ITEMS])


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _section_present_but_disabled(section_key: str) -> bool:
    """True iff the workspace ``applicant_features`` section map flags the section
    present-but-disabled (the Compare contract). Imports the workspace module the same
    way ``test_enh_t08_frontend_steps.py`` does."""
    ws = str(REPO_ROOT / "workspace")
    if ws not in sys.path:
        sys.path.insert(0, ws)
    feats = importlib.import_module("src.applicant_features")
    for section in feats.APPLICANT_SECTIONS:
        if section.get("key") == section_key:
            return bool(section.get("present_but_disabled"))
    return False


def probe(spec: tuple) -> bool:
    """Interpret a ``(kind, *args)`` probe tuple against the real repo tree."""
    kind = spec[0]
    if kind == "file_exists":
        return (STATIC / spec[1]).is_file()
    if kind == "file_contains":
        path = STATIC / spec[1]
        return path.is_file() and spec[2] in _read(path)
    if kind == "css_contains":
        return spec[1] in _read(STYLE_CSS)
    if kind == "ci_contains":
        return spec[1] in _read(CI_YML)
    if kind == "section_present_but_disabled":
        return _section_present_but_disabled(spec[1])
    raise AssertionError(f"unknown probe kind: {kind!r}")


@pytest.fixture
def uikitctx() -> dict:
    return {}


@given(parsers.parse('the UI-kit migration item "{key}"'))
def given_item(uikitctx, key):
    assert key in ITEMS, f"unknown FR-UIKIT item {key!r}"
    uikitctx["item"] = ITEMS[key]


@then("its pre-migration baseline anchor is satisfied today")
def baseline_satisfied(uikitctx):
    item = uikitctx["item"]
    assert probe(item["baseline"]) is True, (
        f"baseline anchor not satisfied: {item['baseline']!r}"
    )


@then("its post-migration kit target is satisfied")
def target_satisfied(uikitctx):
    item = uikitctx["item"]
    # Genuine red today: the vendored kit module / kit-class adoption does not exist yet.
    assert probe(item["target"]) is True, (
        f"kit migration target not yet satisfied: {item['target']!r}"
    )
