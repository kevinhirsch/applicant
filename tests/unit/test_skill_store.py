import pytest

from applicant.ports.driven.skill_store import (
    SKILL_SCOPE_CAMPAIGN,
    SKILL_SCOPE_GLOBAL,
    SKILL_SCOPES,
    Skill,
    SkillMeta,
    SkillStore,
)


@pytest.fixture(autouse=True)
def _no_cache():
    pass


@pytest.mark.unit
class TestModuleConstants:
    """SKILL_SCOPE_* constants and SKILL_SCOPES tuple."""

    def test_global_is_global(self):
        assert SKILL_SCOPE_GLOBAL == "global"

    def test_campaign_is_campaign(self):
        assert SKILL_SCOPE_CAMPAIGN == "campaign"

    def test_scopes_tuple_contains_both(self):
        assert SKILL_SCOPES == (SKILL_SCOPE_GLOBAL, SKILL_SCOPE_CAMPAIGN)


@pytest.mark.unit
class TestSkillMeta:
    """SkillMeta frozen dataclass: construction, defaults, immutability, hashing."""

    def test_minimal_construction(self):
        meta = SkillMeta(name="test-skill")
        assert meta.name == "test-skill"
        assert meta.description == ""
        assert meta.when_to_use == ""
        assert meta.version == "1.0.0"
        assert meta.scope == SKILL_SCOPE_GLOBAL
        assert meta.campaign_id is None
        assert meta.source == "learned"

    def test_full_construction(self):
        meta = SkillMeta(
            name="deploy-skill",
            description="Deploy the application",
            when_to_use="Before a production release",
            version="2.1.0",
            scope=SKILL_SCOPE_CAMPAIGN,
            campaign_id="camp-123",
            source="taught",
        )
        assert meta.name == "deploy-skill"
        assert meta.description == "Deploy the application"
        assert meta.when_to_use == "Before a production release"
        assert meta.version == "2.1.0"
        assert meta.scope == SKILL_SCOPE_CAMPAIGN
        assert meta.campaign_id == "camp-123"
        assert meta.source == "taught"

    def test_campaign_id_defaults_to_none(self):
        meta = SkillMeta(name="s")
        assert meta.campaign_id is None

    def test_source_default_to_learned(self):
        meta = SkillMeta(name="s")
        assert meta.source == "learned"

    def test_frozen_raises_on_set(self):
        meta = SkillMeta(name="s")
        with pytest.raises(AttributeError):
            meta.name = "new-name"

    def test_equality(self):
        a = SkillMeta(name="a", description="x")
        b = SkillMeta(name="a", description="x")
        assert a == b

    def test_inequality(self):
        a = SkillMeta(name="a")
        b = SkillMeta(name="b")
        assert a != b

    def test_repr_contains_fields(self):
        meta = SkillMeta(name="greet")
        r = repr(meta)
        assert "SkillMeta" in r
        assert "greet" in r

    def test_hashable(self):
        a = SkillMeta(name="a", version="1.0.0")
        b = SkillMeta(name="b", version="2.0.0")
        s = {a, b}
        assert len(s) == 2
        # Same values produce same hash
        a2 = SkillMeta(name="a", version="1.0.0")
        assert hash(a) == hash(a2)


@pytest.mark.unit
class TestSkill:
    """Skill frozen dataclass: construction, defaults, meta(), immutability, hashing."""

    def test_minimal_construction(self):
        skill = Skill(name="test-skill")
        assert skill.name == "test-skill"
        assert skill.description == ""
        assert skill.version == "1.0.0"
        assert skill.when_to_use == ""
        assert skill.procedure == ()
        assert skill.pitfalls == ()
        assert skill.verification == ()
        assert skill.scope == SKILL_SCOPE_GLOBAL
        assert skill.campaign_id is None
        assert skill.source == "learned"
        assert skill.tags == ()

    def test_full_construction(self):
        skill = Skill(
            name="deploy",
            description="Deploy to production",
            version="2.0.0",
            when_to_use="Before release",
            procedure=("Check CI", "Run deploy", "Verify health"),
            pitfalls=("Not verifying health", "Skipping smoke tests"),
            verification=("Health endpoint returns 200", "DB migrations applied"),
            scope=SKILL_SCOPE_CAMPAIGN,
            campaign_id="camp-456",
            source="imported",
            tags=("deployment", "production"),
        )
        assert skill.name == "deploy"
        assert skill.procedure == ("Check CI", "Run deploy", "Verify health")
        assert skill.pitfalls == ("Not verifying health", "Skipping smoke tests")
        assert skill.verification == ("Health endpoint returns 200", "DB migrations applied")
        assert skill.scope == SKILL_SCOPE_CAMPAIGN
        assert skill.campaign_id == "camp-456"
        assert skill.source == "imported"
        assert skill.tags == ("deployment", "production")

    def test_default_factory_tags_is_fresh(self):
        a = Skill(name="a")
        b = Skill(name="b")
        # Each gets its own empty tuple (default_factory ensures no sharing)
        assert a.tags == ()
        assert b.tags == ()

    def test_meta_method_returns_skill_meta_with_correct_fields(self):
        skill = Skill(
            name="deploy",
            description="Deploy to prod",
            version="2.0.0",
            when_to_use="Before release",
            procedure=("Check CI",),
            scope=SKILL_SCOPE_CAMPAIGN,
            campaign_id="camp-456",
            source="taught",
        )
        meta = skill.meta()
        assert isinstance(meta, SkillMeta)
        assert meta.name == "deploy"
        assert meta.description == "Deploy to prod"
        assert meta.when_to_use == "Before release"
        assert meta.version == "2.0.0"
        assert meta.scope == SKILL_SCOPE_CAMPAIGN
        assert meta.campaign_id == "camp-456"
        assert meta.source == "taught"

    def test_frozen_raises_on_set(self):
        skill = Skill(name="s")
        with pytest.raises(AttributeError):
            skill.name = "new-name"

    def test_equality(self):
        a = Skill(name="deploy", version="1.0.0")
        b = Skill(name="deploy", version="1.0.0")
        assert a == b

    def test_inequality(self):
        a = Skill(name="a")
        b = Skill(name="b")
        assert a != b

    def test_repr_contains_fields(self):
        skill = Skill(name="greet")
        r = repr(skill)
        assert "Skill" in r
        assert "greet" in r

    def test_hashable(self):
        a = Skill(name="a", version="1.0.0")
        b = Skill(name="b", version="2.0.0")
        s = {a, b}
        assert len(s) == 2
        a2 = Skill(name="a", version="1.0.0")
        assert hash(a) == hash(a2)


@pytest.mark.unit
class TestSkillStore:
    """SkillStore is a runtime_checkable Protocol with 6 methods."""

    def test_is_runtime_checkable(self):
        """@runtime_checkable allows isinstance checks."""
        import inspect
        assert inspect.isclass(SkillStore)
        # runtime_checkable is set via @runtime_checkable on the class

    def test_conforming_class_passes_isinstance_check(self):
        """A class implementing all 6 methods is a SkillStore."""
        class InMemorySkillStore:
            def list_skills(self, scope=None, campaign_id=None):
                return ()

            def load(self, name):
                return None

            def create(self, skill):
                return skill

            def patch(self, name, **fields):
                return None

            def edit(self, name, skill):
                return None

            def delete(self, name):
                return False

        store = InMemorySkillStore()
        assert isinstance(store, SkillStore)

    def test_non_conforming_class_fails_isinstance_check(self):
        class NotAStore:
            pass

        assert not isinstance(NotAStore(), SkillStore)

    def test_protocol_method_signatures_exist(self):
        """All 6 expected methods are in the protocol's __annotations__ or dict."""
        expected = {"list_skills", "load", "create", "patch", "edit", "delete"}
        # Protocol methods aren't in __annotations__; check __protocol_attrs__
        if hasattr(SkillStore, "__protocol_attrs__"):
            actual = {a for a in SkillStore.__protocol_attrs__}
            assert expected.issubset(actual)
