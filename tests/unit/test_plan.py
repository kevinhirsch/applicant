import pytest

from applicant.core.entities.plan import (
    OpKind,
    GotoOp,
    FindOp,
    FillOp,
    SelectOp,
    ClickOp,
    UploadOp,
    ExtractOp,
    AssertOp,
    WaitOp,
    StopOp,
    Op,
    Plan,
)


@pytest.fixture(autouse=True)
def _no_cache():
    """xdist parallel-safety: no caches in this module, but convention requires the fixture."""
    yield


class TestOpKind:
    """OpKind enum members and their str values."""

    def test_members(self):
        assert OpKind.GOTO.value == "goto"
        assert OpKind.FIND.value == "find"
        assert OpKind.FILL.value == "fill"
        assert OpKind.SELECT.value == "select"
        assert OpKind.CLICK.value == "click"
        assert OpKind.UPLOAD.value == "upload"
        assert OpKind.EXTRACT.value == "extract"
        assert OpKind.ASSERT.value == "assert"
        assert OpKind.WAIT.value == "wait"
        assert OpKind.STOP.value == "stop"

    def test_is_str_enum(self):
        assert issubclass(OpKind, str)


class TestGotoOp:
    """GotoOp frozen dataclass with Literal[OpKind.GOTO] kind."""

    def test_defaults(self):
        op = GotoOp()
        assert op.kind == OpKind.GOTO
        assert op.url == ""

    def test_explicit_url(self):
        op = GotoOp(url="https://example.com")
        assert op.kind == OpKind.GOTO
        assert op.url == "https://example.com"

    def test_frozen(self):
        op = GotoOp()
        with pytest.raises(AttributeError):
            op.url = "changed"


class TestFindOp:
    """FindOp frozen dataclass."""

    def test_defaults(self):
        op = FindOp()
        assert op.kind == OpKind.FIND
        assert op.ref == ""
        assert op.role == ""
        assert op.name is None
        assert op.near is None

    def test_explicit(self):
        op = FindOp(ref="#btn", role="button", name="Submit", near=".form")
        assert op.ref == "#btn"
        assert op.role == "button"
        assert op.name == "Submit"
        assert op.near == ".form"

    def test_frozen(self):
        op = FindOp()
        with pytest.raises(AttributeError):
            op.role = "changed"


class TestFillOp:
    """FillOp frozen dataclass."""

    def test_defaults(self):
        op = FillOp()
        assert op.kind == OpKind.FILL
        assert op.ref == ""
        assert op.attribute_id == ""

    def test_explicit(self):
        op = FillOp(ref="#name", attribute_id="attr-001")
        assert op.ref == "#name"
        assert op.attribute_id == "attr-001"


class TestSelectOp:
    """SelectOp frozen dataclass."""

    def test_defaults(self):
        op = SelectOp()
        assert op.kind == OpKind.SELECT
        assert op.ref == ""
        assert op.attribute_id == ""

    def test_explicit(self):
        op = SelectOp(ref="#country", attribute_id="attr-002")
        assert op.ref == "#country"
        assert op.attribute_id == "attr-002"


class TestClickOp:
    """ClickOp frozen dataclass."""

    def test_defaults(self):
        op = ClickOp()
        assert op.kind == OpKind.CLICK
        assert op.ref == ""

    def test_explicit(self):
        op = ClickOp(ref="#submit")
        assert op.ref == "#submit"


class TestUploadOp:
    """UploadOp frozen dataclass."""

    def test_defaults(self):
        op = UploadOp()
        assert op.kind == OpKind.UPLOAD
        assert op.ref == ""
        assert op.document_id == ""

    def test_explicit(self):
        op = UploadOp(ref="#file", document_id="doc-001")
        assert op.ref == "#file"
        assert op.document_id == "doc-001"


class TestExtractOp:
    """ExtractOp frozen dataclass."""

    def test_defaults(self):
        op = ExtractOp()
        assert op.kind == OpKind.EXTRACT
        assert op.ref is None
        assert op.shape == ""

    def test_explicit(self):
        op = ExtractOp(ref="#table", shape="table")
        assert op.ref == "#table"
        assert op.shape == "table"


class TestAssertOp:
    """AssertOp frozen dataclass."""

    def test_defaults(self):
        op = AssertOp()
        assert op.kind == OpKind.ASSERT
        assert op.ref == ""
        assert op.predicate == ""

    def test_explicit(self):
        op = AssertOp(ref="#msg", predicate="visible")
        assert op.ref == "#msg"
        assert op.predicate == "visible"


class TestWaitOp:
    """WaitOp frozen dataclass with for_ default."""

    def test_defaults(self):
        op = WaitOp()
        assert op.kind == OpKind.WAIT
        assert op.for_ == "visible"
        assert op.timeout == 10.0

    def test_explicit(self):
        op = WaitOp(for_="enabled", timeout=5.0)
        assert op.for_ == "enabled"
        assert op.timeout == 5.0


class TestStopOp:
    """StopOp frozen dataclass."""

    def test_defaults(self):
        op = StopOp()
        assert op.kind == OpKind.STOP
        assert op.reason == ""

    def test_explicit(self):
        op = StopOp(reason="completed")
        assert op.reason == "completed"


class TestOpTypeAlias:
    """Op is a union type alias of all op types."""

    def test_goto_is_op(self):
        assert isinstance(GotoOp(), Op)

    def test_find_is_op(self):
        assert isinstance(FindOp(), Op)

    def test_fill_is_op(self):
        assert isinstance(FillOp(), Op)

    def test_select_is_op(self):
        assert isinstance(SelectOp(), Op)

    def test_click_is_op(self):
        assert isinstance(ClickOp(), Op)

    def test_upload_is_op(self):
        assert isinstance(UploadOp(), Op)

    def test_extract_is_op(self):
        assert isinstance(ExtractOp(), Op)

    def test_assert_is_op(self):
        assert isinstance(AssertOp(), Op)

    def test_wait_is_op(self):
        assert isinstance(WaitOp(), Op)

    def test_stop_is_op(self):
        assert isinstance(StopOp(), Op)


class TestPlan:
    """Plan frozen dataclass with ordered ops."""

    def test_default_empty(self):
        plan = Plan()
        assert plan.ops == ()
        assert len(plan) == 0

    def test_with_ops(self):
        goto = GotoOp(url="https://example.com")
        fill = FillOp(ref="#name", attribute_id="attr-1")
        plan = Plan(ops=(goto, fill))
        assert len(plan) == 2
        assert plan.ops[0] is goto
        assert plan.ops[1] is fill

    def test_iteration(self):
        ops = (GotoOp(), FindOp())
        plan = Plan(ops=ops)
        assert list(plan) == list(ops)

    def test_getitem(self):
        goto = GotoOp(url="https://x.com")
        fill = FillOp(ref="#f", attribute_id="a")
        plan = Plan(ops=(goto, fill))
        assert plan[0] is goto
        assert plan[1] is fill
        assert plan[-1] is fill

    def test_frozen(self):
        plan = Plan()
        with pytest.raises(AttributeError):
            plan.ops = (GotoOp(),)


class TestGotoOpKindType:
    """GotoOp kind is Literal[OpKind.GOTO] and matches the enum value."""

    def test_kind_matches_enum(self):
        op = GotoOp()
        assert op.kind is OpKind.GOTO

    def test_type_narrowing(self):
        op: Op = GotoOp()
        if op.kind == OpKind.GOTO:
            assert isinstance(op, GotoOp)
            assert op.url == ""
        else:
            pytest.fail("kind should be GOTO for GotoOp")
