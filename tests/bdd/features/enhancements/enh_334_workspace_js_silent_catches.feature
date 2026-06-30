Feature: Workspace JS no longer fails silently across the board
  # Issue #334 (umbrella) — workspace/static/js/*.js (200+ silent catches, ~60 modules)
  # Sub-issues: #327 chat.js · #328 notes.js · #329 emailInbox.js · #330 assistant.js
  # · #331 document.js · #352 cookbookRunning.js (plus settings.js, emailLibrary.js,
  # admin.js, app.js, gallery.js, tasks.js and ~60 smaller modules).
  # Requirement: Workspace front-end modules MUST NOT swallow errors in empty catch
  # blocks; each audited module MUST replace empty catches with user feedback / logging,
  # driving the repo-wide silent-catch inventory down to zero in the audited modules.

  # GREEN — the systemic problem is real and measurable today (the inventory baseline).
  Scenario: The repo-wide silent-catch inventory is large today
    Given the workspace browser modules
    When the silent catch blocks are counted across every module
    Then many modules contain many silent catch blocks

  Scenario: An audited module has no silent catch blocks left
    Given the workspace browser modules
    When the audited target module is scanned for silent catches
    Then it contains no empty catch block

  @pending
  Scenario: The repo-wide silent-catch inventory is driven to a clean ceiling
    Given the workspace browser modules
    When the silent catch blocks are counted across every module
    Then the total is below the post-cleanup ceiling
