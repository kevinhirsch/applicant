Feature: README front-door surface claims match the section wiring
  # Issue #201 — README.md vs workspace/src/applicant_features.py
  # The README lists nine surfaces as reachable through proxy -> JS -> nav/section, but
  # the section map has eight entries and several README surfaces are not gated through it.
  # The eight real sections are GREEN; the nine-reachable README claim is the gap.

  Scenario: The Applicant section map enumerates its eight wired sections
    Given the workspace Applicant section map
    When the section entries are counted
    Then exactly eight sections are wired into the gating map

  # Implemented in #201: update/takeover/vault README surfaces now have real section
  # defs, so the section count (12) is >= the README's reachable-surface count. GREEN.
  Scenario: Every README front-door surface maps to a gated section
    Given the README front-door surface list and the section map
    When the listed surfaces are matched to gated sections
    Then no listed surface is reachable outside the proxy-JS-nav section pipeline
