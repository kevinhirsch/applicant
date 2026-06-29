Feature: Cookbook remote-execution failures and injected labels are made safe
  # Issue #352 — workspace/static/js/cookbookRunning.js (shell exec + powershell/SSH + innerHTML)
  # Requirement: The Cookbook running view drives remote command execution
  # (/api/shell/exec, powershell -Command over SSH); it MUST NOT swallow shell/task/model
  # failures in empty catch blocks, and it MUST escape user-controlled task labels and env
  # paths before interpolating them into innerHTML.

  # GREEN — the module does route remote commands through the shell-exec endpoint today.
  Scenario: The running view drives remote commands through the shell-exec endpoint
    Given the cookbook running browser module
    When the remote-execution calls are inspected
    Then it sends commands to the shell-exec endpoint

  @pending
  Scenario: No shell, task or model failure is swallowed silently
    Given the cookbook running browser module
    When the module is scanned for empty catch handlers
    Then no empty arrow catch or empty bare catch block remains

  @pending
  Scenario: Remote SSH commands shell-quote their user-controlled task fields
    Given the cookbook running browser module
    When the remote SSH command builders are inspected
    Then the host and session id are shell-quoted rather than interpolated raw
