Feature: Résumé parser preserves parenthesized contact and history fields
  # Issue #170 — résumé parser drops the leading "(" of a parenthesized phone number
  # Engine résumé parser: adapters/resume_parser/resume_parser.py (FR-ONBOARD-3, FR-ATTR-1).
  # The phone regex `(?:\+?\d[\d\s().-]{7,}\d)` matches starting at the first DIGIT,
  # so "(555) 012-3456" parses as "555) 012-3456" — the opening paren is dropped while
  # the closing one is kept. GREEN: a separate parser hardening (parenthesized work-history
  # date ranges) already strips dangling brackets off the company. PENDING: the phone
  # field still loses its leading "(".

  Scenario: A parenthesized work-history company keeps no dangling bracket
    Given a résumé whose experience line parenthesizes the date range
    When the résumé is parsed
    Then the company name carries no leftover opening bracket

  @pending
  Scenario: A parenthesized phone number keeps its opening bracket
    Given a résumé whose contact line shows a parenthesized phone number
    When the résumé is parsed
    Then the parsed phone keeps the leading opening bracket
