Feature: Scraped research content is escaped and its links scheme-validated before rendering
  # Issue #353 — workspace/static/js/research/panel.js (source rendering, line ~1102-1118)
  # Requirement: The research panel MUST HTML-escape every scraped/LLM-derived string it
  # renders, AND validate source-link hrefs to safe schemes (http/https), so a malicious
  # scraped title or URL cannot inject script into the authenticated page.

  Scenario: Scraped source titles are HTML-escaped before rendering
    Given the research panel renderer
    When it builds the source list for a job
    Then each scraped title and query is run through an HTML-escape helper

  Scenario: A javascript: source link is neutralized before it reaches an href
    Given the research panel source-link builder
    When it is inspected for safe-scheme validation of source URLs
    Then a javascript: scheme href is neutralized rather than entity-escaped only
