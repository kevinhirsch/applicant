# ADR-0001: Hexagonal architecture with BDD and TDD

**Status:** Accepted (mandated by master spec §2, §6, NFR-ARCH-1, §13).

## Context

The system integrates many swappable external concerns (LLM providers cloud or local, multiple discovery sources, ATS adapters, browser automation, sandbox/remote-view, resume renderers, credential stores, notification channels, durable orchestration) and must enforce non-negotiable domain rules (truthfulness, pre-fill-stop boundary, sensitive-field policy, confirmation-on-integral-change, review-before-submission). It must stay extensible (NFR-EXT-1) and locally testable without live external services. The engineering mandate requires every sub-agent spec to cite requirement IDs and every behavior to map to a requirement.

## Decision

Adopt **hexagonal (ports-and-adapters) architecture** with a **pure core domain** (no I/O), **driving ports** (use-case facing) and **driven ports** (infrastructure facing), with concrete **adapters** injected at the edge. Drive implementation with **BDD** (Gherkin features mapped to requirement IDs, §10 anchors) and **TDD** (failing test first). The dependency rule: **core depends only on port interfaces; each adapter has a contract test** (§6). Domain rules live in the core so no adapter can bypass them.

## Consequences

- **Positive:** Adapters are swappable behind contract tests (Neko↔noVNC, OpenRouter↔Ollama, LaTeX↔docx-XML) without core changes; the core is fast to test with mocked ports (Phase 0 exit requires domain >90% covered with ports mocked); requirement traceability is structural (§13 matrix); extensibility is the default (NFR-EXT-1).
- **Negative / cost:** More upfront indirection (ports + adapters + contract tests) than a monolith; discipline required to keep I/O out of the core and to author a BDD feature per requirement (many requirements currently lack §10 anchors and need features written — tracked in [traceability.md](../traceability.md)).
- **Enforced rules in core:** truthfulness (FR-RESUME-2/NFR-TRUTH-1), pre-fill-stop (FR-PREFILL-4), sensitive-field policy (FR-ATTR-6), confirmation-on-integral-change (FR-FB-3), review-before-submission (FR-RESUME-8). See [architecture.md](../architecture.md).
