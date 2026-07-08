#!/usr/bin/env python
"""P1-2 real-board pre-fill proof harness (dry-run only — stops at the review boundary).

Owner decision (issue #719): dry-run ONLY, no employer trial accounts. Automation
may run against real ATS boards but MUST stop at the review boundary — pre-fill,
never submit. This harness drives the engine's REAL browser stack
(``PlaywrightPageSource``) and proves, per target, that:

  * field detection works against a real board's form (FR-PREFILL-2/3), and
  * the run never reaches a final-submit / confirmation page — the pre-fill
    stop boundary (FR-PREFILL-4/5, NFR-OPS-1) is respected.

It NEVER types a value and NEVER clicks a submit. Detection only.

Two modes, so the proof is runnable both where live browser egress is available
AND in constrained sandboxes where only saved DOM can be replayed:

  live  — navigate a real posting URL with the stealth browser, enter the
          application flow, detect fields, assert the stop boundary. This is the
          Integration-Lane path (mirrors tests/integration/test_ats_prefill_dryrun.py)
          and needs real outbound browser egress.

  dom   — load a saved real-board DOM snapshot into the SAME real browser via
          ``set_content`` (no network navigation, so it works behind an egress
          proxy that a launched browser cannot tunnel through) and run the exact
          same detection + boundary checks against the genuine board markup. The
          snapshot is captured out-of-band (e.g. ``curl``) from the live board;
          the detection + boundary logic exercised is identical.

Usage:
    # Live navigation (needs browser egress):
    uv run python scripts/proof/ats_dryrun_proof.py live \\
        --label greenhouse-figma \\
        --url "https://job-boards.greenhouse.io/figma/jobs/5364702004" \\
        --out docs/proof/p1-2

    # Saved-DOM replay (works behind an egress proxy):
    uv run python scripts/proof/ats_dryrun_proof.py dom \\
        --label greenhouse-figma \\
        --dom /path/to/greenhouse.html \\
        --source-url "https://job-boards.greenhouse.io/figma/jobs/5364702004" \\
        --out docs/proof/p1-2

Each run appends a machine-readable record to ``<out>/evidence.json`` and writes a
per-target PNG screenshot to ``<out>/<label>.png``. Exit code is non-zero if the
stop boundary was crossed (a hard safety failure) or the browser never started.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
from pathlib import Path


def _launch_source():
    """Launch the real driver on the first working channel; ``(source, channel)``.

    Launches ONCE — the probe launch IS the run launch (no probe-then-relaunch).
    Returns ``(None, None)`` when no browser binary is launchable. The caller owns
    the returned source and must ``close()`` it.
    """
    try:
        from applicant.adapters.browser.page_source import PlaywrightPageSource
        from applicant.adapters.browser.stealth import coherent_fingerprint
    except Exception:  # pragma: no cover - import guard
        return None, None
    for channel in ("chromium", "chrome"):
        try:
            src = PlaywrightPageSource(
                coherent_fingerprint(channel), headless=True, channel=channel
            )
            return src, channel
        except Exception:
            continue
    return None, None


def _run(src, *, label: str, source_url: str, out_dir: Path) -> dict:
    """Run detection + the stop-boundary assertion; return an evidence record.

    NEVER types a value and NEVER submits. Detection only.
    """
    trace: list[str] = []
    # Enter the application flow if the board gates the form behind an "Apply" click.
    try:
        src.enter_application()
        trace.append("entered_application_flow")
    except Exception as exc:  # some boards render the form inline
        trace.append(f"enter_application_skipped: {exc!s:.100}")

    fields = src.detect_fields()
    trace.append(f"detected_fields: {len(fields)}")

    # The core safety assertion: a detection-only pass must NOT have reached a
    # post-submission CONFIRMATION page — that is the only signal that a submit
    # actually fired. Reaching a page that merely *has* a final-submit button is
    # EXPECTED and correct: single-page ATS boards (Greenhouse, Lever) render all
    # fields and the "Submit application" button on one page, which is exactly the
    # pre-fill terminus where the engine stops and hands off to human review. So
    # `is_final_submit_page` is recorded as informational (the pre-fill terminus),
    # NOT as a boundary violation; only `is_confirmation_page` proves a crossing.
    on_prefill_terminus = bool(src.is_final_submit_page())
    reached_confirmation = bool(src.is_confirmation_page())
    at_account_gate = bool(src.is_account_gate())
    trace.append(f"is_final_submit_page (pre-fill terminus): {on_prefill_terminus}")
    trace.append(f"is_confirmation_page (post-submit proof): {reached_confirmation}")
    trace.append(f"is_account_gate: {at_account_gate}")

    shot_file = None
    try:
        shot_ref = src.screenshot()
        # screenshot() returns a file:// ref to a temp PNG; copy it next to the
        # evidence so the proof is self-contained under docs/proof/.
        if shot_ref and shot_ref.startswith("file://"):
            tmp_png = Path(shot_ref[len("file://") :])
            if tmp_png.exists():
                shot_file = str((out_dir / f"{label}.png").resolve())
                shutil.copyfile(tmp_png, shot_file)
    except Exception as exc:
        trace.append(f"screenshot_failed: {exc!s:.100}")

    field_inventory = [
        {"selector": f.selector, "label": f.label, "type": f.field_type}
        for f in fields
    ]
    return {
        "label": label,
        "source_url": source_url,
        "detected_field_count": len(fields),
        "fields": field_inventory,
        "stop_boundary_respected": not reached_confirmation,
        "on_prefill_terminus": on_prefill_terminus,
        "is_final_submit_page": on_prefill_terminus,
        "is_confirmation_page": reached_confirmation,
        "is_account_gate": at_account_gate,
        "screenshot": shot_file,
        "state_trace": trace,
        "typed_any_value": False,
        "submitted": False,
    }


def _mode_live(args, src) -> dict:
    src.open(args.url)
    return _run(src, label=args.label, source_url=args.url, out_dir=args.out)


def _mode_dom(args, src) -> dict:
    html = Path(args.dom).read_text(encoding="utf-8", errors="replace")
    # Inject the saved real-board markup WITHOUT a URL navigation, exactly like
    # tests/integration/test_real_browser.py — this keeps the SSRF guard intact
    # and needs no browser egress, while driving the real detection engine over
    # genuine board DOM. "commit" avoids hanging on the board's cross-origin
    # subresources (which cannot load offline).
    src._page.set_content(html, wait_until="commit")  # noqa: SLF001
    try:
        src._settle()  # noqa: SLF001
    except Exception:
        pass
    return _run(src, label=args.label, source_url=args.source_url, out_dir=args.out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Shared flags live on a parent parser so both subcommands define them once.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--label", required=True)
    common.add_argument("--out", type=Path, default=Path("docs/proof/p1-2"))
    sub = parser.add_subparsers(dest="mode", required=True)

    p_live = sub.add_parser(
        "live", parents=[common], help="Navigate a live posting URL (needs egress)."
    )
    p_live.add_argument("--url", required=True)

    p_dom = sub.add_parser(
        "dom", parents=[common], help="Replay a saved real-board DOM snapshot."
    )
    p_dom.add_argument("--dom", required=True, help="Path to the saved .html snapshot.")
    p_dom.add_argument("--source-url", default="", help="The live URL it came from.")

    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    src, channel = _launch_source()
    if src is None:
        print(
            "SKIP: no browser binary launchable. Install with "
            "`uv sync --extra browser && uv run patchright install chromium`.",
            file=sys.stderr,
        )
        return 3

    try:
        record = _mode_live(args, src) if args.mode == "live" else _mode_dom(args, src)
    finally:
        src.close()

    record["channel"] = channel
    record["ran_at"] = _dt.datetime.now(_dt.UTC).isoformat()

    # Append to the evidence ledger (one JSON array of per-target records).
    ledger = args.out / "evidence.json"
    existing = []
    if ledger.exists():
        try:
            existing = json.loads(ledger.read_text())
        except Exception:
            existing = []
    # Replace any prior record for the same label so re-runs update in place.
    existing = [r for r in existing if r.get("label") != record["label"]]
    existing.append(record)
    ledger.write_text(json.dumps(existing, indent=2) + "\n")

    print(json.dumps(record, indent=2))
    if not record["stop_boundary_respected"]:
        print(
            "FAIL: stop boundary crossed during a detection-only dry-run.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
