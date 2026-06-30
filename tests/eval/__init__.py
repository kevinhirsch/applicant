"""Browser-agent eval harness using AgentLab + BrowserGym.

This package provides a scaffold for running evaluation benchmarks against the
plan-as-data pre-fill planner using AgentLab and BrowserGym.

BrowserGym provides the gym environment for browser interaction; AgentLab provides
the benchmarking framework. The harness:

1. Loads AgentLab tasks (or custom tasks)
2. Drives the applicant engine's pre-fill planner as the agent under test
3. Collects success/failure metrics per task
4. Outputs results for CI comparison
"""
