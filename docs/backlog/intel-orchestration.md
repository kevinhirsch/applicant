# Orchestration Doctrine (FR-INTEL-5)

## Doctrine Table

| Work | Profile | Tier | Locality |
|------|---------|------|----------|
| Real coding/edits/running commands & builds | coder | local-fast | local |
| Reading/searching code | explorer | local-fast | local |
| Writing & running tests | test-engineer | local-fast | local |
| Independent verification of an important change | reviewer | cloud-flash | remote |
| Security-sensitive review | security-auditor | cloud-flash | remote |
| Hard debugging / deep judgment | debugger | cloud-pro | remote |

## Remote-Only Scenario Catalog (R1–R9)

| ID | Scenario | Why | Tier |
|----|----------|-----|------|
| R1 | Planning/decomposition/architecture/ambiguity resolution | strongest reasoning, sets everything downstream | overseer (cloud-flash) |
| R2 | Reviewing/synthesising worker output; final answer to user | must not trust a local worker's self-assessment | overseer (cloud-flash) |
| R3 | Independent verification of an important change | a second, stronger, independent judge | reviewer (cloud-flash) |
| R4 | Security review | higher stakes; catch subtle issues | security-auditor (cloud-flash) |
| R5 | Hard debugging after local escalation exhausted | max intelligence | debugger (cloud-pro) |
| R6 | Any step > ctx_cap (~96000) | physically exceeds the local window | *-cloud (cloud-flash, 1M ctx) |
| R7 | Repeated local failure (>=2 struggles) | local model can't converge (INTEL-4) | DeepSeek-Pro (cloud-pro) |
| R8 | Parallelism beyond concurrency(2) local slots | GPU can't run more heavy streams | overflow -> *-cloud (cloud-flash) |
| R9 | Vision / image reasoning | local model is text-only | vision-capable cloud |

## Fan-Out Policy

- **max_local**: 2 concurrent local subordinates
- **overflow**: cloud (excess tasks route to *-cloud profiles)

## Runtime Application

The LIVE application of this doctrine is the agent0 overseer prompt (§9.4) which encodes this contract verbatim. The overseer (cloud agent0) delegates work according to the delegation table and remote-only catalog.

## Acceptance Criteria (ACK)

- **AC1**: Plan/decompose -> overseer (cloud)
- **AC2**: 3 tasks -> <=2 local + rest cloud (per fan-out max_local=2)
- **AC3**: Important change -> needs reviewer
- **AC4**: Security/Safety -> security-auditor
- **AC5**: 130K never local + vision never local

## Enforcement

This contract is enforced by:
- `tests/unit/test_intel_orchestration.py` — hermetic YAML-based unit tests
- Sibling config files `config/intel_tiers.yaml`, `config/hardware_profiles.yaml`, and `config/intel_escalation.yaml` for cross-referencing
