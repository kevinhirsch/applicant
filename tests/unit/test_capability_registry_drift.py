"""Drift tests for the capability registry (FR-HARVEST-CAPREG).

These tests enforce the structural invariants declared in
:mod:`applicant.application.capability_registry` so that a careless edit to the
registry is caught immediately by CI rather than silently violating the safety
model at runtime.

Invariants checked:

1. **Non-empty names** — every registered capability has a non-empty ``name``.
2. **Frozen** — the registry cannot be mutated at runtime (``frozenset`` rejects
   ``add``/``discard``/``remove``).
3. **Exemption rationale** — every key in ``REVIEW_EXEMPTIONS`` has a non-empty
   rationale string.
4. **Exemption coherence** — every name in ``REVIEW_EXEMPTIONS`` actually appears
   in the registry (no phantom exemptions for non-existent capabilities).
5. **Mutation → review invariant** — a capability with ``mutates_application=True``
   MUST also have ``needs_human_review=True`` UNLESS it is listed in
   ``REVIEW_EXEMPTIONS``.  This is the core safety invariant: the engine cannot
   autonomously mutate an application without human oversight.
6. **Exemption necessity** — an entry in ``REVIEW_EXEMPTIONS`` must correspond to
   a capability that actually has ``needs_human_review=False`` (no stale/incorrect
   exemptions for capabilities that already require review).
7. **No duplicate names** — the registry names are unique (``frozenset`` of
   ``NamedTuple`` guarantees hash-uniqueness, but we verify name strings too).
"""

from __future__ import annotations

import pytest

from applicant.application.capability_registry import (
    CAPABILITY_REGISTRY,
    REVIEW_EXEMPTIONS,
    Capability,
    all_capabilities,
    lookup,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all() -> frozenset[Capability]:
    return CAPABILITY_REGISTRY


def _names() -> list[str]:
    return [c.name for c in _all()]


# ---------------------------------------------------------------------------
# 1. Non-empty names
# ---------------------------------------------------------------------------

class TestNonEmptyNames:
    def test_all_capabilities_have_non_empty_names(self):
        """Every registered capability must have a non-empty name string."""
        bad = [c for c in _all() if not c.name or not c.name.strip()]
        assert not bad, f"Capabilities with empty names: {bad}"


# ---------------------------------------------------------------------------
# 2. Registry is frozen (immutable)
# ---------------------------------------------------------------------------

class TestRegistryIsFrozen:
    def test_registry_is_a_frozenset(self):
        assert isinstance(CAPABILITY_REGISTRY, frozenset)

    def test_registry_cannot_be_mutated_via_add(self):
        with pytest.raises(AttributeError):
            CAPABILITY_REGISTRY.add(  # type: ignore[attr-defined]
                Capability("injected", True, True, False)
            )

    def test_registry_cannot_be_mutated_via_discard(self):
        with pytest.raises(AttributeError):
            CAPABILITY_REGISTRY.discard(next(iter(CAPABILITY_REGISTRY)))  # type: ignore[attr-defined]

    def test_all_capabilities_returns_same_frozenset(self):
        """all_capabilities() must return the same frozen object, not a copy."""
        assert all_capabilities() is CAPABILITY_REGISTRY

    def test_capability_tuple_is_immutable(self):
        cap = next(iter(_all()))
        with pytest.raises(AttributeError):
            cap.name = "hacked"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3. Exemption rationales are non-empty
# ---------------------------------------------------------------------------

class TestExemptionRationales:
    def test_all_exemptions_have_non_empty_rationale(self):
        bad = [k for k, v in REVIEW_EXEMPTIONS.items() if not v or not v.strip()]
        assert not bad, (
            f"REVIEW_EXEMPTIONS entries with blank/empty rationale: {bad}\n"
            "Every exemption must carry explicit reasoning."
        )


# ---------------------------------------------------------------------------
# 4. Exemption coherence — no phantom exemptions
# ---------------------------------------------------------------------------

class TestExemptionCoherence:
    def test_all_exemption_names_exist_in_registry(self):
        names = set(_names())
        phantom = [k for k in REVIEW_EXEMPTIONS if k not in names]
        assert not phantom, (
            f"REVIEW_EXEMPTIONS references names not in CAPABILITY_REGISTRY: {phantom}\n"
            "Remove stale exemptions or add the missing capability entries."
        )


# ---------------------------------------------------------------------------
# 5. Mutation → review invariant (the core safety check)
# ---------------------------------------------------------------------------

class TestMutationReviewInvariant:
    def test_mutates_application_implies_needs_human_review_or_is_exempted(self):
        """mutates_application=True must imply needs_human_review=True (unless exempted).

        This is the safety invariant that prevents the engine from autonomously
        mutating a job application without human oversight.  If a capability must
        be exempted, it MUST appear in REVIEW_EXEMPTIONS with explicit reasoning.
        """
        violations = [
            c
            for c in _all()
            if c.mutates_application
            and not c.needs_human_review
            and c.name not in REVIEW_EXEMPTIONS
        ]
        if violations:
            lines = "\n  ".join(
                f"{c.name!r}  (mutates=True, needs_review=False, NOT in REVIEW_EXEMPTIONS)"
                for c in sorted(violations, key=lambda x: x.name)
            )
            pytest.fail(
                "The following capabilities violate the mutation→review invariant:\n"
                f"  {lines}\n\n"
                "Fix: either set needs_human_review=True or add the name to "
                "REVIEW_EXEMPTIONS with explicit reasoning."
            )


# ---------------------------------------------------------------------------
# 6. Exemption necessity — no stale exemptions for already-reviewed ops
# ---------------------------------------------------------------------------

class TestExemptionNecessity:
    def test_exemptions_only_for_no_review_capabilities(self):
        """An exemption is only necessary when the capability has needs_human_review=False.

        An exemption entry for a capability that already has needs_human_review=True
        is at best misleading and at worst masks a logic error.
        """
        unnecessary = []
        for name in REVIEW_EXEMPTIONS:
            cap = lookup(name)
            if cap is not None and cap.needs_human_review:
                unnecessary.append(name)
        assert not unnecessary, (
            f"REVIEW_EXEMPTIONS has entries for capabilities that already have "
            f"needs_human_review=True (exemption not needed): {unnecessary}\n"
            "Remove these entries from REVIEW_EXEMPTIONS."
        )


# ---------------------------------------------------------------------------
# 7. No duplicate names
# ---------------------------------------------------------------------------

class TestNoDuplicateNames:
    def test_all_names_are_unique(self):
        names = _names()
        seen: set[str] = set()
        duplicates: list[str] = []
        for n in names:
            if n in seen:
                duplicates.append(n)
            seen.add(n)
        assert not duplicates, (
            f"Duplicate capability names in registry: {duplicates}\n"
            "Each capability must have a unique name."
        )


# ---------------------------------------------------------------------------
# Lookup helper
# ---------------------------------------------------------------------------

class TestLookup:
    def test_lookup_known_capability(self):
        cap = lookup("remote.submit_self")
        assert cap is not None
        assert cap.name == "remote.submit_self"
        assert cap.mutates_application is True
        assert cap.needs_human_review is True

    def test_lookup_unknown_capability(self):
        assert lookup("does.not.exist") is None

    def test_lookup_exempted_capability(self):
        cap = lookup("prefill.resume_account_step")
        assert cap is not None
        assert cap.mutates_application is True
        assert cap.needs_human_review is False
        assert cap.name in REVIEW_EXEMPTIONS


# ---------------------------------------------------------------------------
# Smoke: the public surface matches the private constant
# ---------------------------------------------------------------------------

class TestPublicSurface:
    def test_capability_registry_is_not_empty(self):
        assert len(CAPABILITY_REGISTRY) > 0

    def test_registry_contains_core_operations(self):
        """Spot-check that the principal operation categories are represented."""
        names = set(_names())
        expected_prefixes = {
            "remote.",
            "prefill.",
            "documents.",
            "digest.",
            "discovery.",
            "research.",
            "pending_actions.",
            "credentials.",
            "attributes.",
            "criteria.",
            "feedback.",
            "chat.",
            "campaigns.",
            "setup.",
            "onboarding.",
            "outcomes.",
            "admin.",
            "agent_runs.",
            "notifications.",
        }
        missing_prefixes = {
            pfx
            for pfx in expected_prefixes
            if not any(n.startswith(pfx) for n in names)
        }
        assert not missing_prefixes, (
            f"No capabilities registered for these expected groups: {missing_prefixes}\n"
            "Add at least one entry for each group in CAPABILITY_REGISTRY."
        )
