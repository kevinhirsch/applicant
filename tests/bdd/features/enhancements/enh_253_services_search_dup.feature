# Issue #253 — workspace/services/search/ is a dead duplicate of workspace/src/search/
# The actively-used search package is workspace/src/search/ (imported by chat_processor,
# deep_research, tool_execution, app_initializer, research_handler). Four files —
# cache.py, query.py, ranking.py, analytics.py — are byte-identical between the two
# packages; the services/ copies are dead weight. The GREEN scenarios pin the canonical
# package and prove the duplication exists today; the @pending scenario is the cleanup
# acceptance criterion: the duplicate files have been removed.

Feature: Search code lives in one canonical package, not two

  Scenario: The actively-used search package is the one under src
    Given the workspace search packages
    Then the canonical search package under src is importable by the app modules
    And the duplicate package is only reached from the search route

  Scenario: Four search files are byte-identical across the two packages today
    Given the workspace search packages
    When the shared search files are compared between the two packages
    Then the cache, query, ranking and analytics files are duplicated verbatim

  @pending
  Scenario: The duplicate search files have been removed
    Given the workspace search packages
    Then the duplicated cache, query, ranking and analytics files no longer exist under services
