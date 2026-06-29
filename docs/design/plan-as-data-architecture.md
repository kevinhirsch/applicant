# Plan-as-Data Architecture

**Status:** Implementation scaffold (Phase 1 of 6 — DSL + pure validator + planner port + adapter).  
**Spec reference:** `docs/design/plan-as-data.md` (full design spec).  
**Issue:** #305

## Overview

Plan-as-Data replaces per-step LLM reasoning with a single **typed-DSL plan** emitted
by the planner over a semantic DOM snapshot. The plan is validated in the pure core
before execution, cutting model round-trips from O(N) to O(1) per page while keeping
all safety guarantees intact.

## Hexagonal fit

```
core/
  entities/plan.py      -- Plan/Op dataclasses (pure)
  rules/plan.py         -- Validator + guard predicates (pure)
ports/
  driving/planner.py    -- PlannerPort (inbound)
adapters/
  planner/llm_planner.py -- Default LLM-backed adapter
  planner/__init__.py
```

### Core entities (`core/entities/plan.py`)

| Entity | Description |
|---|---|
| `OpKind` | Enum of all supported operations (closed set: goto, find, fill, select, click, upload, extract, assert, wait, stop) |
| `GotoOp`, `FindOp`, ..., `StopOp` | Frozen dataclass per op kind |
| `Op` | Union type of all ops |
| `Plan` | Ordered tuple of `Op` values |

**Key safety property:** `fill`/`select`/`upload` reference **attribute/document IDs**,
never literal values — the model decides *which fact goes in which field* but cannot
inject a *fabricated value* (NFR-TRUTH-1 by construction).

### Core validator (`core/rules/plan.py`)

- `validate_plan(plan, known_attribute_ids)` — schema-validates, bounds op count (max 40),
  rejects unknown attribute references.
- `validate_op_sequence(plan)` — checks sequencing rules (stop must be last).
- `STOP_REASONS` — the closed set of stop-boundary reasons (`account_create`, `captcha`,
  `final_submit`, `email_verify`, `sms_verify`, `two_factor`, `oauth`).

### Planner port (`ports/driving/planner.py`)

- `PlannerPort.plan(input_)` — emit a Plan from goal + observation + facts + constraints.
- `PlannerPort.plan_many(goal, pages, facts)` — multi-page flow planning.
- `PlannerInput`, `PlannerObservation` — typed input dataclasses.

### LLM Planner adapter (`adapters/planner/llm_planner.py`)

- Default adapter uses L1 (cheap) model for planning via structured JSON output.
- Prompt = role + DSL schema + semantic DOM snapshot + attribute manifest + constraints.
- `PlanParseError` raised on unparseable output → empty plan → caller escalates.

## Rollout phases (from design spec)

| Phase | What | When |
|---|---|---|
| 1 | DSL + pure validator + planner port + L1 adapter | **Now** (this commit) |
| 2 | Pre-fill via plan-as-data behind `PREFILL_PLANNER` flag | Next |
| 3 | Self-correction loop + verification | Next |
| 4 | Discovery read-only JS lane | Later |
| 5 | Whole-application flow planner | Later |
| 6 | System-wide PlannerPort across loop | Later |
