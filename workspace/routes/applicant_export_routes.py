# routes/applicant_export_routes.py
"""Owner data export — "Download my data" (P1-7, issue #659).

Settings -> Account gets a "Download my data" button that produces ONE zip
containing everything an irreplaceable job search would need to survive this
self-hosted instance disappearing: the owner's applications (CSV + JSON), the
generated documents library (metadata + the compiled résumé PDFs where the
engine has rendered one), the profile (attribute cloud), and the recent
activity feed.

This is a thin, auth-protected, OWNER-scoped proxy over
:class:`src.applicant_engine.ApplicantEngineClient` — it adds no engine logic,
just aggregates several existing reads into one downloadable artifact. Reuses
CLAUDE.md principle #1 (lift-and-shift): the applications section is built from
the EXACT SAME owner fan-out ``applicant_tracker_routes._owner_tracker_rows``
already uses for the Tracker board, rather than a second re-derivation of "which
applications belong to this owner".

Cross-account isolation (DISC-15): gated by ``src.auth_helpers.
require_engine_owner`` (not the plain auth-only ``require_user``) — the engine
is single-tenant (CLAUDE.md), so a second, unrelated workspace account must not
be able to download the real owner's data.

Honesty (H-series): every section degrades soft and SAYS SO rather than
silently rendering an empty export as a complete one — ``manifest.json`` in the
zip records ``engine_available`` and, for a per-campaign/per-application read
that failed, exactly which id and why, so an incomplete export is never
indistinguishable from a complete one.

Endpoint:

* ``GET /api/applicant/export/data.zip`` — the full data export as a zip.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request, Response

from routes.applicant_tracker_routes import _owner_tracker_rows
from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_engine_owner

logger = logging.getLogger(__name__)

#: applications.csv column order (keys of each tracker row this export knows
#: how to render as a flat column; anything else on the row still lands in
#: applications.json, just not as its own CSV column).
_CSV_COLUMNS = (
    "application_id",
    "campaign_id",
    "campaign_name",
    "role_name",
    "job_title",
    "status",
    "signals",
    "submitted_at",
    "created_at",
)


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _campaign_label(campaign: dict) -> str:
    return str(campaign.get("name") or campaign.get("id") or "")


async def _owner_campaigns(engine: ApplicantEngineClient, manifest: dict) -> list[dict]:
    """The owner's own campaigns, or ``[]`` with the failure recorded in
    ``manifest`` (never raises — every caller here must degrade soft so a
    down/gated engine still produces an honest, if empty, export)."""
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        manifest["engine_available"] = False
        manifest["errors"].append(f"campaigns: {exc}")
        return []
    if not isinstance(campaigns, list):
        return []
    return [c for c in campaigns if isinstance(c, dict) and c.get("id")]


def _csv_bytes(rows: list[dict]) -> bytes:
    """applications.csv — a UTF-8 BOM prefix so Excel (esp. Windows Excel,
    which otherwise mis-detects encoding) opens it correctly, per the DoD's
    "opens in Excel and a text editor" requirement."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(_CSV_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        flat = dict(row)
        signals = flat.get("signals")
        if isinstance(signals, list):
            flat["signals"] = "; ".join(str(s) for s in signals)
        writer.writerow(flat)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def setup_applicant_export_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/export", tags=["applicant-export"])

    @router.get("/data.zip")
    async def export_data(request: Request) -> Response:
        """The owner's full data export: applications (CSV + JSON), documents
        (metadata + compiled résumé PDFs where rendered), profile (attribute
        cloud), and recent activity — bundled into one downloadable zip.
        """
        require_engine_owner(request)

        manifest: dict = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "engine_available": True,
            "errors": [],
        }

        applications: list[dict] = []
        profile: dict[str, Any] = {}
        activity: dict[str, Any] = {}
        documents_by_application: list[dict] = []
        variants_by_campaign: list[dict] = []
        variant_pdfs: dict[str, bytes] = {}

        async with ApplicantEngineClient() as engine:
            campaigns = await _owner_campaigns(engine, manifest)

            # -- applications: reuse the EXACT tracker-board fan-out (lift-and-
            # shift, CLAUDE.md principle #1) rather than re-deriving "which
            # applications belong to this owner".
            rows = await _owner_tracker_rows(engine)
            if isinstance(rows, list):
                applications = rows
            else:
                manifest["engine_available"] = manifest["engine_available"] and bool(
                    rows.get("engine_available", False)
                )
                if rows.get("message"):
                    manifest["errors"].append(f"applications: {rows['message']}")

            # -- profile + activity + variant library, per owned campaign.
            for campaign in campaigns:
                cid = str(campaign["id"])
                cname = _campaign_label(campaign)

                try:
                    attrs = await engine.list_attributes(cid)
                except EngineError as exc:
                    manifest["errors"].append(f"profile[{cid}]: {exc}")
                    attrs = {}
                profile[cid] = {"campaign_name": cname, **_as_dict(attrs)}

                try:
                    runs = await engine.agent_runs_list(cid)
                except EngineError as exc:
                    manifest["errors"].append(f"activity[{cid}]: {exc}")
                    runs = {}
                if isinstance(runs, dict):
                    items = _as_list(runs.get("items"))
                elif isinstance(runs, list):
                    items = runs
                else:
                    items = []
                activity[cid] = {"campaign_name": cname, "items": items}

                try:
                    variants = await engine.list_variants(cid)
                except EngineError as exc:
                    manifest["errors"].append(f"documents/variants[{cid}]: {exc}")
                    variants = {}
                variant_list = _as_list(_as_dict(variants).get("variants"))
                variants_by_campaign.append(
                    {"campaign_id": cid, "campaign_name": cname, "variants": variant_list}
                )
                # Best-effort: fetch each variant's compiled PDF. A variant with
                # no rendered artifact yet (stub mode, compile failure) is
                # skipped silently — its metadata above already says so.
                for variant in variant_list:
                    vid = variant.get("variant_id") if isinstance(variant, dict) else None
                    if not vid or vid in variant_pdfs:
                        continue
                    try:
                        resp = await engine.download_variant_pdf(str(vid))
                        content = getattr(resp, "content", None)
                        if content:
                            variant_pdfs[str(vid)] = content
                    except EngineError:
                        pass  # no rendered artifact for this variant — fine, not fatal.

            # -- documents metadata, per owned application (from the SAME
            # applications fan-out above -- never a caller-supplied id).
            for row in applications:
                app_id = row.get("application_id")
                if not app_id:
                    continue
                try:
                    docs = await engine.documents_for_application(str(app_id))
                except EngineError as exc:
                    manifest["errors"].append(f"documents[{app_id}]: {exc}")
                    docs = {}
                documents_by_application.append(
                    {"application_id": str(app_id), **_as_dict(docs)}
                )

        manifest["counts"] = {
            "applications": len(applications),
            "campaigns": len(campaigns),
            "documents_pdfs": len(variant_pdfs),
        }

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            zf.writestr("applications.json", json.dumps(applications, indent=2, ensure_ascii=False))
            zf.writestr("applications.csv", _csv_bytes(applications))
            zf.writestr("profile.json", json.dumps(profile, indent=2, ensure_ascii=False))
            zf.writestr("activity.json", json.dumps(activity, indent=2, ensure_ascii=False))
            zf.writestr(
                "documents/documents.json",
                json.dumps(
                    {
                        "applications": documents_by_application,
                        "variants": variants_by_campaign,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            )
            for vid, content in variant_pdfs.items():
                zf.writestr(f"documents/resume-{vid}.pdf", content)

        filename = f"applicant-data-export-{datetime.now(timezone.utc).strftime('%Y%m%d')}.zip"
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    return router
