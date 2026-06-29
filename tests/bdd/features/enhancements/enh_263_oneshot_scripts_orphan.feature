# Issue #263 — five workspace/scripts/ one-shot tools have zero cross-references
# scripts/ holds one-shot migration/setup tools. Investigation on this branch finds
# fix_paths.py, index_documents.py, migrate_faiss_to_chroma.py, update_database.py and
# add_hwfit_models.py are never imported, run, or documented anywhere in the project —
# they sat on disk as identifiable cleanup targets. Cleanup shipped.

Feature: One-shot maintenance scripts are documented, integrated, or removed

  @pending
  Scenario: The five one-shot tools are present as identifiable cleanup targets
    Given the workspace scripts directory
    Then the five one-shot tools are present on disk

  @pending
  Scenario: The five one-shot tools have no cross-references in the project
    Given the workspace scripts directory
    When each one-shot tool is scanned for references across the project
    Then none of them are referenced anywhere

  Scenario: The orphaned one-shot tools have been removed
    Given the workspace scripts directory
    Then the orphaned one-shot tools no longer exist
