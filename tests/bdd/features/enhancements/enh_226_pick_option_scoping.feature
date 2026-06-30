# Issue #226 — _pick_visible_option not scoped to the opened dropdown (adapters/browser/page_source.py) — FR-PREFILL-3
# _pick_visible_option polls ALL [role=option] elements page-wide, with no scoping to the
# opened listbox via aria-owns/aria-controls. A stale, still-in-DOM option from a
# different dropdown can match. PENDING — the scoping helper does not exist.

Feature: Option picking is scoped to the dropdown that was just opened

  Scenario: Only options belonging to the opened listbox are considered
    Given an opened dropdown whose listbox is identified by an aria-controls relationship
    When the picker selects an option for that dropdown
    Then it considers only options owned by that listbox
