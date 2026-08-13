"""E3: demote postings confirmed DEAD by the liveness sweep so they drop off
Kevin's queue. App ORM only. Reads dead posting ids (one per line) from a file;
for each, stashes the prior score in rationale and floors viability_score so it
can't top the queue, tagging it DEAD with today's date (re-checkable later).
"""
import sys
import dataclasses
from datetime import date

from applicant.app.container import build_container
from applicant.core.ids import JobPostingId

ids_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dead_ids.txt"
with open(ids_path) as f:
    dead_ids = [ln.strip() for ln in f if ln.strip()]

c = build_container()
storage = c.storage
demoted = 0
for pid in dead_ids:
    p = storage.postings.get(JobPostingId(pid))
    if p is None:
        continue
    prior = getattr(p, "viability_score", None)
    rat = dict(getattr(p, "rationale", None) or {}) if isinstance(getattr(p, "rationale", None), dict) else {}
    rat["dead"] = True
    rat["dead_checked"] = str(date(2026, 8, 13))
    rat["score_before_dead"] = prior
    rat["text"] = (f"Posting is no longer open (liveness check {date(2026,8,13)}); demoted so it "
                   f"can't top the queue. Prior score was {round((prior or 0)*100)}.")
    try:
        storage.postings.add(dataclasses.replace(p, viability_score=0.02, rationale=rat))
        demoted += 1
    except Exception as e:
        print(f"  {pid[:8]}: FAILED {e}")
storage.commit()
print(f"demoted {demoted}/{len(dead_ids)} dead postings (score->0.02, tagged DEAD)")
