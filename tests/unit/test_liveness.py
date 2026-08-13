"""Posting-liveness rule (E3) — pure classifier tests (no network).

Pins the semantics validated empirically against lever + greenhouse: live = 200
still at the posting URL; dead = 4xx/410 or a 200 that redirected off the posting
to a board root / error page; unknown (never demoted) = anti-bot/transient.
"""

import pytest

from applicant.core.rules.liveness import classify_liveness


@pytest.mark.unit
class TestClassifyLiveness:
    def test_404_is_dead(self):
        v = classify_liveness(404, "https://jobs.lever.co/x/uuid", "https://jobs.lever.co/x/uuid")
        assert v.status == "dead" and v.is_dead

    def test_410_is_dead(self):
        v = classify_liveness(410, "https://job-boards.greenhouse.io/x/jobs/1", "https://job-boards.greenhouse.io/x/jobs/1")
        assert v.status == "dead"

    def test_200_same_posting_url_is_live(self):
        url = "https://jobs.lever.co/compassx/c99a4d42-7d0c-45a2-a7f4-0362f86534d3"
        assert classify_liveness(200, url, url).status == "live"

    def test_200_greenhouse_posting_is_live(self):
        url = "https://job-boards.greenhouse.io/lts/jobs/4286870009"
        assert classify_liveness(200, url, url).status == "live"

    def test_200_redirected_to_board_root_is_dead(self):
        # greenhouse posting removed -> redirects to the board root (loses /jobs/<id>)
        v = classify_liveness(200, "https://job-boards.greenhouse.io/capitalrx", "https://job-boards.greenhouse.io/capitalrx/jobs/5200511008")
        assert v.status == "dead"

    def test_200_error_param_is_dead(self):
        v = classify_liveness(200, "https://job-boards.greenhouse.io/capitalrx?error=true", "https://job-boards.greenhouse.io/capitalrx/jobs/5200511008")
        assert v.status == "dead"

    def test_403_is_unknown_not_dead(self):
        # anti-bot block must NEVER demote a possibly-live role
        v = classify_liveness(403, "", "https://jobs.lever.co/x/uuid")
        assert v.status == "unknown" and not v.is_dead

    def test_429_and_5xx_are_unknown(self):
        for code in (429, 500, 502, 503, 504):
            assert classify_liveness(code, "", "https://x/y").status == "unknown"

    def test_network_failure_zero_is_unknown(self):
        assert classify_liveness(0, "", "https://x/y").status == "unknown"

    def test_301_redirect_landing_on_posting_is_live(self):
        # a 200 after a same-posting redirect (trailing slash etc.) stays live
        url = "https://jobs.lever.co/x/uuid-123"
        assert classify_liveness(200, url + "/apply", url).status == "live"
