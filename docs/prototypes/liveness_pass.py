"""E3 recurring liveness pass: recheck candidate postings and demote the ones
that have gone DEAD, so dead links auto-prune continuously (not a one-off sweep).

Runs inside the engine container (app ORM + the committed liveness rule). Fetch
is a browser-UA GET (follow redirects); classification is the pure
core.rules.liveness.classify_liveness — only CONFIRMED-dead demotes; anti-bot /
transient results are left untouched. Intended to be invoked periodically (cron
or the scheduler tick).

Usage:  python liveness_pass.py [min_score] [limit]
"""
import sys
import dataclasses
import urllib.request
import urllib.error
from datetime import date

from applicant.app.container import build_container
from applicant.core.ids import JobPostingId
from applicant.core.rules.liveness import classify_liveness

MIN_SCORE = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 80
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=18) as r:
            return r.status, r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, (getattr(e, "url", None) or url)
    except Exception:
        return 0, url


def main():
    c = build_container()
    storage = c.storage
    # Candidate postings: worth-showing, http URL, not already tagged dead.
    session = getattr(storage, "_session", None)
    if session is None:
        print("no SQL session; abort")
        return
    from applicant.adapters.storage.models import JobPostingModel
    q = (session.query(JobPostingModel)
         .filter(JobPostingModel.viability_score >= MIN_SCORE)
         .filter(JobPostingModel.source_url.like("http%"))
         .order_by(JobPostingModel.viability_score.desc())
         .limit(LIMIT))
    candidates = [(m.id, m.source_url) for m in q
                  if not (isinstance(m.rationale, dict) and m.rationale.get("dead"))]
    live = dead = unknown = 0
    for pid, url in candidates:
        status, final = fetch(url)
        v = classify_liveness(status, final, url)
        if v.status == "dead":
            dead += 1
            p = storage.postings.get(JobPostingId(pid))
            rat = dict(p.rationale) if isinstance(getattr(p, "rationale", None), dict) else {}
            rat.update(dead=True, dead_checked=str(date(2026, 8, 13)),
                       dead_reason=v.reason, score_before_dead=p.viability_score)
            rat["text"] = f"Posting no longer open ({v.reason}); demoted by liveness pass."
            storage.postings.add(dataclasses.replace(p, viability_score=0.02, rationale=rat))
        elif v.status == "live":
            live += 1
        else:
            unknown += 1
    storage.commit()
    print(f"liveness pass: checked {len(candidates)} (score>={MIN_SCORE}); "
          f"live={live} dead(demoted)={dead} unknown(left)={unknown}")


if __name__ == "__main__":
    main()
