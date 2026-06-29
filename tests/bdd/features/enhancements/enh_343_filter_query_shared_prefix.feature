# Issue #343 — adapters/browser/page_source.py:_filter_query (PlaywrightPageSource)
#   _filter_query types only the first 2 meaningful words; for a long option whose first
#   words are a shared prefix (e.g. "United States" vs "United States Minor Outlying
#   Islands") prefix-filtering can leave the wrong option selectable.
# Requirement: _filter_query MUST type enough of a long, multi-word value (more than the
#   first two words) to disambiguate options that share a leading-word prefix.
# Related existing issue: #225 (dropdown/combobox matching coverage — same matcher area).
# GREEN: today _filter_query returns exactly the first two words (regression guard).
# PENDING: a long shared-prefix value yields a longer, disambiguating filter query.

Feature: The combobox filter query disambiguates shared-prefix options

  Scenario: The filter query uses the first two meaningful words today
    Given a long country-style option value that shares a leading-word prefix
    When the combobox filter query is built for that value
    Then the filter query is exactly the first two words

  @pending
  Scenario: A shared-prefix value yields a longer disambiguating filter query
    Given a long country-style option value that shares a leading-word prefix
    When the combobox filter query is built for that value
    Then the filter query types more than the first two words to disambiguate
