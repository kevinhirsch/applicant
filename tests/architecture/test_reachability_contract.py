"""Reachability contract — CLAUDE.md principle #2, automated (release-readiness §3.1).

CLAUDE.md principle #2: *"Reachability is the definition of done. A requirement is not
done because the engine implements it and tests pass — it is done when it is reachable/
operable in the white-labeled front-door."* The traceability docs verify only the
engine; this test verifies dimension (3) of the coverage audit — that each white-label
``/api/applicant/*`` proxy route has a front-end consumer — so a NEW engine capability
that gets a workspace proxy but never gets wired into the JS **fails CI** instead of
silently shipping as dead UI.

How it works (pure file-content; no app boot, fully hermetic):

* Enumerate the workspace applicant proxy route files
  ``workspace/routes/applicant_*_routes.py`` and, for each, the ``/api/applicant/<area>``
  prefix it mounts plus every ``@router.<verb>(...)`` sub-path it declares.
* For each declared proxy path, assert at least one consumer under
  ``workspace/static/js/`` references it — matching either the full literal path or the
  area base (``/api/applicant/<area>``) combined with the path's first distinctive
  segment, which is how the JS builds these URLs (``const API = '/api/applicant/<area>'``
  then ``fetch(`${API}/<segment>/...`)``).
* An explicit ``KNOWN_UNWIRED`` allowlist carries the BE→FE gaps already filed in the
  1.0 release-readiness ledger (docs/release-readiness-1.0.md §2d). A path in the
  allowlist MAY be unconsumed; **any other unconsumed proxy path fails the test**, with
  a message naming the offending path so a future unwired feature is obvious.

``applicant_internal_routes.py`` is excluded: it is the token-gated engine→workspace
callback channel (``/api/applicant/internal/*``), not a front-door surface, so it has no
``workspace/static/js`` consumer by design.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

# Repo root: tests/architecture/<this file> -> repo root is two parents up.
ROOT = Path(__file__).resolve().parents[2]
ROUTES_DIR = ROOT / "workspace" / "routes"
JS_DIR = ROOT / "workspace" / "static" / "js"

_PREFIX_RE = re.compile(r"""APIRouter\(\s*prefix\s*=\s*["']([^"']+)["']""")
_ROUTE_RE = re.compile(r"""@router\.(get|post|put|delete|patch)\(\s*["']([^"']*)["']""")


# --- KNOWN_UNWIRED allowlist ------------------------------------------------
# BE→FE gaps already filed in the 1.0 release-readiness ledger (the marginal /
# dormant BE→FE niceties of docs/release-readiness-1.0.md §2d). Each entry is an
# applicant proxy path that exists but has NO front-end consumer YET, with the
# issue / readiness reference that tracks wiring it. A path here is permitted to be
# unconsumed; ANY OTHER unconsumed applicant proxy path FAILS this test.
#
# These are the concrete proxy paths behind the readiness doc's named BE→FE gaps
# (#401 digest deliver, #402 digest email, #403 chat confirm-criteria,
# #404 criteria learned, #405 documents ensure-submittable): the digest deliver/
# email paths are in fact already consumed today, so the genuinely-unconsumed
# residue that keeps this test GREEN is the dormant/debug-only reads below.
KNOWN_UNWIRED: dict[str, str] = {
    # #403-adjacent — chat-steering pending actions superseded by the Portal feed
    # (applicantChat surfaces /api/applicant/portal/pending; the dedicated chat
    # pending-actions endpoints are unconsumed). Pull in if chat-steering is a 1.0
    # selling point (docs/release-readiness-1.0.md §2d note on #403).
    "GET /api/applicant/chat/pending-actions/{campaign_id}": "release-readiness §2d (#403)",
    "POST /api/applicant/chat/pending-actions/{action_id}/resolve": "release-readiness §2d (#403)",
    # #405 — résumé aggressiveness dial is wired backend-side but the front-door
    # control is intentionally dormant (docs/dormant-surfaces.md #1, FR-RESUME-9 / #187).
    "POST /api/applicant/documents/aggressiveness": "release-readiness §2d (#187 / FR-RESUME-9 dormant)",
    # #404-adjacent — debug-only engine reads not surfaced in the front-door:
    # the detection monitor (FR-PREFILL-6) and the stealth-profile readout are
    # operator/diagnostic reads, not user surfaces.
    "GET /api/applicant/admin/detections/{campaign_id}": "release-readiness §2d (#404, debug-only read)",
    "GET /api/applicant/admin/stealth": "release-readiness §2d (#404, debug-only read)",
    # Exploration-budget READ for research: the front-door reads the budget via the
    # ops/discovery surface (applicantDebug renders data.exploration_budget); the
    # research-scoped budget GET is the unconsumed twin.
    "GET /api/applicant/research/{campaign_id}/budget": "release-readiness §2d (FR-LEARN-6 read via ops/discovery)",
    # G27 dead-code removal: applicantActivity.js and applicantPortal.js were deleted
    # (orphaned — replaced by applicantChat.js and applicantMind.js). Their proxy
    # routes are preserved for backward compat but have no front-end consumer.
    "GET /api/applicant/activity/status": "G27 dead-code cleanup (#261, #264)",
    "GET /api/applicant/activity/intent": "G27 dead-code cleanup (#261, #264)",
    "GET /api/applicant/activity/runs": "G27 dead-code cleanup (#261, #264)",
    "GET /api/applicant/activity/snapshot": "G27 dead-code cleanup (#261, #264)",
    "POST /api/applicant/portal/missing-attribute": "G27 dead-code cleanup (#261, #264)",
}


def _proxy_files() -> list[Path]:
    """All applicant proxy route files except the internal callback channel."""
    files = sorted(ROUTES_DIR.glob("applicant_*_routes.py"))
    assert files, f"No applicant proxy route files found under {ROUTES_DIR}"
    return [f for f in files if f.name != "applicant_internal_routes.py"]


def _declared_paths() -> list[tuple[str, str, str]]:
    """Enumerate ``(method, full_path, area)`` for every proxy route declaration."""
    out: list[tuple[str, str, str]] = []
    for f in _proxy_files():
        text = f.read_text()
        m = _PREFIX_RE.search(text)
        assert m, f"{f.name}: no APIRouter(prefix=...) found"
        prefix = m.group(1)
        assert prefix.startswith("/api/applicant/"), (
            f"{f.name}: unexpected proxy prefix {prefix!r} (must mount /api/applicant/<area>)"
        )
        area = prefix[len("/api/applicant/") :].split("/")[0]
        for method, sub in _ROUTE_RE.findall(text):
            full = (prefix + sub).rstrip("/") or prefix
            out.append((method.upper(), full, area))
    return out


def _js_blob() -> str:
    """Concatenated content of every front-end JS module (the consumer surface)."""
    parts = [p.read_text(errors="ignore") for p in JS_DIR.rglob("*.js")]
    assert parts, f"No JS consumer files found under {JS_DIR}"
    return "\n".join(parts)


def _first_segment(full: str, area: str) -> str | None:
    """First distinctive (non-param) path segment after ``/api/applicant/<area>``."""
    tail = full[len(f"/api/applicant/{area}") :]
    for seg in tail.strip("/").split("/"):
        if seg and not seg.startswith("{"):
            return seg
    return None


def _is_consumed(full: str, area: str, js: str) -> bool:
    """True if some JS module references this proxy path.

    Robust to the JS's dynamic URL construction (a base constant
    ``/api/applicant/<area>`` joined with a literal sub-segment): a path counts as
    consumed when the JS contains the full literal path, OR contains both the area
    base and the path's first distinctive segment, OR (for area-root/param-only
    paths) just references the area base.
    """
    if full in js:
        return True
    area_base = f"/api/applicant/{area}"
    if area_base not in js:
        return False
    seg = _first_segment(full, area)
    if seg is None:
        # The path is the area root (or only path params) — area-base reference is enough.
        return True
    return f"/{seg}" in js


def test_known_unwired_entries_are_real_unconsumed_proxy_paths() -> None:
    """The allowlist must not rot: every entry must still name a real, unconsumed path.

    Guards against the allowlist silently masking a path that no longer exists (typo /
    renamed route) or one that has since been wired (should be removed so the contract
    re-asserts it).
    """
    declared = {f"{m} {p}" for m, p, _ in _declared_paths()}
    js = _js_blob()
    by_full = {p: area for _, p, area in _declared_paths()}

    for key in KNOWN_UNWIRED:
        assert key in declared, (
            f"KNOWN_UNWIRED entry {key!r} is not a declared proxy route anymore — "
            "remove it or fix the path (the route was renamed/deleted)."
        )
        full = key.split(" ", 1)[1]
        assert not _is_consumed(full, by_full[full], js), (
            f"KNOWN_UNWIRED entry {key!r} now HAS a front-end consumer — "
            "remove it from the allowlist so the reachability contract re-asserts it."
        )


def test_every_applicant_proxy_path_is_reachable_in_the_front_door() -> None:
    """CLAUDE.md principle #2: every /api/applicant/* proxy route must have a JS consumer.

    Any unconsumed proxy path that is NOT in the KNOWN_UNWIRED allowlist fails CI — so a
    newly-added engine capability cannot ship as dead UI.
    """
    js = _js_blob()
    offenders: list[str] = []
    for method, full, area in _declared_paths():
        key = f"{method} {full}"
        if _is_consumed(full, area, js):
            continue
        if key in KNOWN_UNWIRED:
            continue
        offenders.append(key)

    assert not offenders, (
        "Unreachable applicant proxy route(s) — engine capability with a workspace "
        "proxy but NO workspace/static/js consumer (CLAUDE.md principle #2: reachability "
        "is the definition of done). Wire a front-end consumer, or, if this is a known "
        "BE→FE gap, add it to KNOWN_UNWIRED with its issue ref:\n  "
        + "\n  ".join(sorted(offenders))
    )
