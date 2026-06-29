# Issue #348 — pyproject.toml (requires-python = ">=3.11,<3.12")
# Requirement: The project MUST either widen requires-python to admit Python 3.12
# (>=3.11,<3.13) or document in pyproject.toml WHY 3.12+ is excluded — the hard
# upper pin of <3.12 must not stand silent. (Paired with #355: one Python decision.)
Feature: Python version constraint is widened or justified

  # GREEN — what ships today: the constraint floors at 3.11.
  Scenario: The project floors the interpreter at Python 3.11
    Given the project manifest
    When its python requirement is inspected
    Then it requires at least Python 3.11

  # PENDING — the residual gap: 3.12 is excluded with no recorded reason.
  @pending
  Scenario: Python 3.12 is admitted or the exclusion is justified
    Given the project manifest
    When its python upper bound is inspected
    Then either Python 3.12 is admitted or the exclusion is documented
