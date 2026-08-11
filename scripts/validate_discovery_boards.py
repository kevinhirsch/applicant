#!/usr/bin/env python3
"""Pre-deploy gate: prove every configured ATS board actually serves real postings.

Kevin's explicit, standing rule: "verified data sources that actually serve real
jobs" is a REQUIREMENT for adding a discovery source, not a nice-to-have. This
script is the enforcement mechanism for that rule at the ``DISCOVERY_*`` env-var
layer (``adapters/discovery/validate.py``'s ``validate_provider_rows`` is the
mechanism at the runtime ``add_board`` API layer -- see its module docstring).

Run it BEFORE appending a new token to ``DISCOVERY_GREENHOUSE_BOARDS`` /
``DISCOVERY_LEVER_COMPANIES`` / ``DISCOVERY_ASHBY_ORGS`` /
``DISCOVERY_SMARTRECRUITERS_COMPANIES`` / ``DISCOVERY_WORKDAY_BOARDS`` (whether
you're hand-editing ``.env`` or a future session is widening reach again), and
periodically against the live-configured set to catch a board that quietly went
dead (renamed slug, ATS migration, board taken down).

Network: this makes REAL outbound HTTP calls (the whole point -- an offline fake
can't prove a board is live). Never run it in the hermetic test lane; it is a
standalone operator/CI tool, not part of ``pytest``.

Usage::

    # Validate everything currently configured in Settings/.env:
    uv run python scripts/validate_discovery_boards.py

    # Validate specific ad-hoc candidates before adding them anywhere:
    uv run python scripts/validate_discovery_boards.py \\
        --greenhouse figma mongodb \\
        --lever spotify \\
        --ashby openai \\
        --smartrecruiters visa \\
        --workday "wf.wd1.myworkdayjobs.com|wf|WellsFargoJobs|Wells Fargo"

Exit code: 0 iff every checked candidate validated as real postings; 1 if any
candidate failed (empty/404/non-posting-shaped) -- wire this into CI or a
pre-deploy checklist to fail loudly on a source that quietly went dead.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from applicant.adapters.discovery.clients import (
    LiveAshbyClient,
    LiveGreenhouseClient,
    LiveLeverClient,
    LiveSmartRecruitersClient,
    LiveWorkdayClient,
)
from applicant.adapters.discovery.validate import validate_provider_rows


@dataclass
class Candidate:
    provider: str
    token: str


def _fetch_rows(client, provider: str, token: str) -> object:
    """Call the right client method for ``provider`` (mirrors
    ``DiscoveryService._FETCH_JOBS_PROVIDERS``)."""
    if provider in ("greenhouse", "ashby", "workday"):
        return client.fetch_jobs(token=token, proxies=None)
    return client.fetch_postings(company=token, proxies=None)


def _clients() -> dict[str, object]:
    return {
        "greenhouse": LiveGreenhouseClient(),
        "lever": LiveLeverClient(),
        "ashby": LiveAshbyClient(),
        "smartrecruiters": LiveSmartRecruitersClient(),
        "workday": LiveWorkdayClient(),
    }


def _from_settings() -> list[Candidate]:
    """Every board currently configured via ``DISCOVERY_*`` (Settings/.env)."""
    from applicant.app.config import Settings

    s = Settings()
    out: list[Candidate] = []
    for token in (t.strip() for t in s.discovery_greenhouse_boards.split(",")):
        if token:
            out.append(Candidate("greenhouse", token))
    for token in (t.strip() for t in s.discovery_lever_companies.split(",")):
        if token:
            out.append(Candidate("lever", token))
    for token in (t.strip() for t in s.discovery_ashby_orgs.split(",")):
        if token:
            out.append(Candidate("ashby", token))
    for token in (t.strip() for t in s.discovery_smartrecruiters_companies.split(",")):
        if token:
            out.append(Candidate("smartrecruiters", token))
    for token in (t.strip() for t in s.discovery_workday_boards.split(",")):
        if token:
            out.append(Candidate("workday", token))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--greenhouse", nargs="*", default=[], metavar="TOKEN")
    parser.add_argument("--lever", nargs="*", default=[], metavar="COMPANY")
    parser.add_argument("--ashby", nargs="*", default=[], metavar="ORG")
    parser.add_argument("--smartrecruiters", nargs="*", default=[], metavar="COMPANY")
    parser.add_argument("--workday", nargs="*", default=[], metavar="HOST|TENANT|SITE[|Name]")
    parser.add_argument(
        "--timeout", type=float, default=15.0, help="per-request timeout in seconds"
    )
    args = parser.parse_args(argv)

    candidates: list[Candidate] = []
    candidates += [Candidate("greenhouse", t) for t in args.greenhouse]
    candidates += [Candidate("lever", t) for t in args.lever]
    candidates += [Candidate("ashby", t) for t in args.ashby]
    candidates += [Candidate("smartrecruiters", t) for t in args.smartrecruiters]
    candidates += [Candidate("workday", t) for t in args.workday]

    if not candidates:
        # No ad-hoc candidates given: validate whatever is currently configured.
        candidates = _from_settings()
        if not candidates:
            print("No candidates given and no DISCOVERY_* boards configured. Nothing to do.")
            return 0
        print(f"Validating {len(candidates)} configured board(s) from Settings/.env...\n")
    else:
        print(f"Validating {len(candidates)} candidate board(s)...\n")

    clients = _clients()
    failures = 0
    for c in candidates:
        client = clients[c.provider]
        try:
            client_typed = client
            if hasattr(client_typed, "_timeout"):
                client_typed._timeout = args.timeout
            rows = _fetch_rows(client, c.provider, c.token)
        except Exception as exc:  # noqa: BLE001 - report, never crash the batch
            print(f"[FAIL] {c.provider}:{c.token}  fetch raised {type(exc).__name__}: {exc}")
            failures += 1
            continue
        result = validate_provider_rows(c.provider, rows)
        if result.ok:
            print(f"[ OK ] {c.provider}:{c.token}  {result.posting_count} real posting(s)")
        else:
            print(f"[FAIL] {c.provider}:{c.token}  {result.reason}")
            failures += 1

    print(
        f"\n{len(candidates) - failures}/{len(candidates)} validated as real postings."
    )
    if failures:
        print(
            f"{failures} candidate(s) FAILED the real-postings gate -- do NOT add/keep "
            "them enabled (Kevin's rule: verified sources only)."
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
