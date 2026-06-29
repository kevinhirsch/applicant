Feature: Throughput is capped per campaign but not per job board
  # Issue #195 — capacity_service.py / discovery: no per-job-board rate limiting
# The engine caps campaign-level throughput and (optionally) LLM calls, but nothing
# paces requests per specific job-board domain. Discovering 10 LinkedIn jobs in one run
# could trip anti-bot detection. GREEN: the campaign-level throughput hard cap is real
# and clamps requests. PENDING: there is no per-source request pacing (e.g. max N/hour
# to linkedin.com) seam at all.

  Scenario: Campaign-level throughput is clamped to a hard cap
    Given a campaign throughput far above the allowed ceiling
    When the throughput is clamped
    Then the applied value never exceeds the campaign hard cap

  @pending
  Scenario: Requests to a single job board are paced below a per-domain ceiling
    Given several postings discovered from the same job-board domain in one run
    When the engine schedules requests against that domain
    Then a per-source pacing policy holds them under a configurable per-domain interval
