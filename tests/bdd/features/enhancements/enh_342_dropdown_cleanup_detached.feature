# Issue #342 — adapters/browser/page_source.py:_choose_listbox_option (PlaywrightPageSource)
#   After a dropdown option that navigates on selection, the Escape + fill("") cleanup
#   operates on a now-detached element (swallowed by except Exception: pass).
# Requirement: The dropdown filter cleanup MUST check whether the page navigated after
#   option selection and skip the Escape/clear on a detached element rather than
#   attempting and swallowing the failure.
# Related existing issue: #226 (visible-option scoping in _pick_visible_option — same
#   dropdown-selection robustness area).
# PENDING: a navigation/attachment check guards the post-selection cleanup.

Feature: Dropdown cleanup skips a detached element after navigation

  Scenario: Cleanup is skipped when option selection navigated the page
    Given a page driver selecting a dropdown option that navigates on selection
    When the dropdown filter cleanup runs after the navigation
    Then it checks the element is still attached before clearing it
