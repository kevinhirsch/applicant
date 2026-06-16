"""Load-bearing domain rules (master spec §6).

These invariants live in the pure core so that **no adapter can bypass them**:

1. truthfulness (FR-RESUME-2, NFR-TRUTH-1)
2. pre-fill-stop boundary (FR-PREFILL-4)
3. sensitive-field policy (FR-ATTR-6)
4. confirmation-on-integral-change (FR-FB-3)
5. mandatory review-before-submission (FR-RESUME-8, FR-ANSWER-1)
"""
