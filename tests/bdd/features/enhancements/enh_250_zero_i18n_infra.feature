Feature: Localization infrastructure for the front-door UI
  # Issue #250 — workspace/static/
  # Every user-facing string is hardcoded English with no i18n framework, no translation
  # keys, and no locale files. The absence of any localization path is the gap (@pending).

  Scenario: The front-door page carries translatable string keys
    Given the front-door page markup
    When the page is checked for translation-key annotations
    Then user-facing strings are tagged with translation keys rather than hardcoded

  Scenario: The workspace ships locale resources
    Given the workspace static tree
    When the tree is checked for locale or translation resource files
    Then at least one locale resource exists so the UI can be localized
