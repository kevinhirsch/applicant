Feature: Discovery dedups within a run but not across runs
  # Issue #196 — discovery_service.py: embedding dedup only within a single run
# DiscoveryService._dedup() compares new postings only against those kept in the current
# run (cosine >= 0.97). It does not persist embeddings across runs, so the same job in
# two daily runs is only caught by identical-source_url dedup. GREEN: within-run
# near-duplicate collapse is real. PENDING: there is no rolling cross-run embedding
# window to deduplicate the same posting across separate discovery runs.

  Scenario: Near-duplicate postings within one run are collapsed
    Given a discovery run that returns two near-identical postings
    When the run deduplicates its results
    Then only one of the near-identical postings survives

  Scenario: The same posting surfaced in a later run is deduplicated against the earlier one
    Given a posting was kept in an earlier discovery run
    When a later run surfaces the same role with a different URL
    Then a persisted rolling embedding window suppresses the cross-run duplicate
