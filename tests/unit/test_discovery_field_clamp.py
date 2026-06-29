"""Scraped job fields are clamped to their DB column widths at ingest (real-DB guard).

`job_postings` columns are bounded VARCHARs — title/company/location String(512),
salary String(128), work_mode String(64) — but board/metasearch rows are external
and routinely exceed them (e.g. a >512-char LinkedIn title). The in-memory test
store has no length limit, so without an ingest clamp the overflow only surfaces on
a real Postgres as StringDataRightTruncation (and again when copied into
applications). These pin the clamp so the class can't regress.
"""

from applicant.adapters.discovery.jobspy_searxng import normalize_row
from applicant.core.ids import CampaignId, new_id


def test_normalize_row_clamps_overlong_fields_to_column_widths():
    cid = CampaignId(new_id())
    raw = {
        "title": "T" * 900,
        "company": "C" * 900,
        "location": "L" * 900,
        "salary": "$" * 300,
        "work_mode": "Z" * 200,  # no remote/hybrid/onsite keyword -> raw fallback
        "source_url": "https://example.test/jobs/1",
        "description": "D" * 5000,  # TEXT column — must NOT be clamped
    }
    p = normalize_row(raw, cid, "searxng")
    assert p is not None
    assert len(p.title) == 512
    assert len(p.company) == 512
    assert len(p.location) == 512
    assert len(p.salary) == 128
    assert len(p.work_mode) == 64
    assert len(p.description) == 5000  # unbounded TEXT preserved


def test_normalize_row_preserves_normal_values():
    cid = CampaignId(new_id())
    raw = {
        "title": "Staff Engineer",
        "company": "Acme",
        "source_url": "https://x.test/1",
        "location": "Remote",
        "salary": "$200k",
        "work_mode": "remote",
    }
    p = normalize_row(raw, cid, "searxng")
    assert p.title == "Staff Engineer"
    assert p.company == "Acme"
    assert p.work_mode == "remote"
    assert p.salary == "$200k"
