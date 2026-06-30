# Issue #357 — workspace/static/js/editor/ (AI image-editor JS audit, TRACKING)
# Requirement: The editor JS surface MUST be individually audited — at minimum the
# four dirtiest files (layer-panel.js, ai-models.js, keyboard-shortcuts.js,
# ai-tool-runner.js) get a per-file sweep recorded as cleared in this tracker.
Feature: Editor JS audit tracker

  # GREEN — the inventory the tracker is keyed to: the editor JS surface still exists
  # at the sweep-inventoried size, and the dirtiest file still carries its raw markup.
  Scenario: The editor JS surface still has the inventoried number of top-level files
    Given the editor JS directory
    When the top-level scripts are counted
    Then there are at least thirty top-level editor scripts

  Scenario: The dirtiest editor file still carries unaudited raw-markup writes
    Given the editor JS directory
    When the dirtiest editor file is scanned
    Then the layer panel still writes raw markup more than ten times

  # PENDING — the audit work this tracker is opened to drive.
  Scenario: The layer panel has been audited and its raw-markup writes cleared
    Given the editor JS directory
    When the layer-panel audit ledger is consulted
    Then the layer panel is recorded as audited and its raw-markup writes resolved
