# Issue #355 — docker/Dockerfile (python:3.11-slim) vs workspace/Dockerfile (python:3.12-slim)
# Requirement: The engine and workspace container images MUST build on the same Python
# major.minor (or the deliberate split must be documented), so the two services in one
# stack do not silently diverge. (Paired with #348: one Python-version decision.)
Feature: Engine and workspace images agree on the Python version

  # GREEN — what ships today: each Dockerfile pins a python:3.1x-slim base.
  Scenario: Both images pin a slim Python base image
    Given the engine and workspace Dockerfiles
    When their base images are inspected
    Then each pins a slim Python base image

  # PENDING — the residual gap: the two pins differ (3.11 vs 3.12).
  Scenario: The two images pin the same Python minor version
    Given the engine and workspace Dockerfiles
    When their Python minor versions are compared
    Then the engine and workspace pin the same Python minor version
