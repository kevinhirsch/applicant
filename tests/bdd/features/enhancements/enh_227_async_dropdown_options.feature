# Issue #227 — No handling of paginated/async dropdown options (adapters/browser/page_source.py) — FR-PREFILL-3
# _pick_visible_option assumes every option is already in the DOM; a virtual/infinite-
# scroll list whose target is on a later page never matches, and the ValueError falsely
# implies the option does not exist. PENDING — async option fetching does not exist.

Feature: Asynchronously loaded dropdown options are fetched before giving up

  @pending
  Scenario: A target option not yet in the DOM is fetched by typing the filter
    Given a combobox whose target option loads asynchronously after filtering
    When the picker looks for the target option
    Then it types the filter and waits for the option to appear before failing
