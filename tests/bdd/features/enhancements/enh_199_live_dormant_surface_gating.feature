Feature: Two-layer feature gating for live dormant surfaces
  # Issue #199 — src/applicant/dormant.py + workspace/src/applicant_features.py
  # Four surfaces are marked live in the engine registry but no front-door section
  # references them via dormant_keys, so the workspace never checks their status. The
  # registry marking those four live is GREEN; the missing front-door gating is the gap.

  Scenario: The engine marks the four operator surfaces as live
    Given the engine dormant-surface registry
    When the debug, tool-toggle, update and remote-takeover surfaces are read
    Then each one reports a live status

  # Implemented in #199: the debug section now references the debug_surface key. GREEN.
  Scenario: The front door gates the live debug surface off its registry key
    Given the workspace Applicant section map
    When the debug surface key is looked up in the section gating
    Then a section depends on the debug surface registry key

  # Implemented in #199: tool_toggle_registry (debug section), update_button (update
  # section) and remote_takeover (takeover section) are now all referenced. GREEN.
  Scenario: The front door gates the live operator surfaces off their registry keys
    Given the workspace Applicant section map
    When the tool-toggle, update and remote-takeover keys are looked up in the section gating
    Then every live surface key is referenced by a front-door section
