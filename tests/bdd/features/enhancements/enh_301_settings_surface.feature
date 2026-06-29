# Issue #301 — Unified settings surface — workspace/static/js/settings.js
# Settings already hosts the relocated OOBE cards (notifications, fonts, automation
# sandbox, update) reusing the wizard renderers, plus the LLM escalation-ladder editor
# (GREEN). The feature wants Settings extended to full campaign management (create/rename/
# archive/clone, inline criteria editor, discovery-source toggles) and engine config
# (quiet hours, throughput, browser engine). Those campaign-management controls are not in
# the settings surface, so they are @pending probes.

Feature: Unified campaign + engine configuration in settings

  Scenario: The relocated setup cards reuse the wizard renderers in settings
    Given the front-door settings module
    When the settings module is inspected for relocated cards
    Then it hosts the notifications, fonts and sandbox cards

  Scenario: The LLM escalation-ladder editor is mounted in settings
    Given the front-door settings module
    When the settings module is inspected for the model ladder
    Then it mounts the model escalation-ladder editor

  @pending
  Scenario: Campaign management is available from the settings surface
    Given the front-door settings module
    When the settings module is inspected for campaign management
    Then it offers create, rename, archive and clone campaign controls
