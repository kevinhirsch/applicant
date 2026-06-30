"""Plan-as-Data typed DSL entities (pure core, no I/O).

A **Plan** is an ordered list of typed **Op** values the model emits in one shot.
Each Op is data, validated against a schema before anything executes. The op set is
small and closed (no escape hatch into arbitrary code).

Key safety property: ``fill``/``select``/``upload`` reference the **attribute cloud /
document library by id**, not by literal value. The model decides *which fact goes in
which field*; it cannot inject a *fabricated value* — the executor resolves the id to
the user's real, stored, fabrication-guarded fact (NFR-TRUTH-1 by construction).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class OpKind(str, Enum):
    """Every operation the typed DSL supports — a closed set."""

    GOTO = "goto"
    FIND = "find"
    FILL = "fill"
    SELECT = "select"
    CLICK = "click"
    UPLOAD = "upload"
    EXTRACT = "extract"
    ASSERT = "assert"
    WAIT = "wait"
    STOP = "stop"


@dataclass(frozen=True)
class GotoOp:
    kind: Literal[OpKind.GOTO] = OpKind.GOTO
    url: str = ""


@dataclass(frozen=True)
class FindOp:
    kind: Literal[OpKind.FIND] = OpKind.FIND
    ref: str = ""
    role: str = ""
    name: str | None = None
    near: str | None = None


@dataclass(frozen=True)
class FillOp:
    kind: Literal[OpKind.FILL] = OpKind.FILL
    ref: str = ""
    attribute_id: str = ""


@dataclass(frozen=True)
class SelectOp:
    kind: Literal[OpKind.SELECT] = OpKind.SELECT
    ref: str = ""
    attribute_id: str = ""


@dataclass(frozen=True)
class ClickOp:
    kind: Literal[OpKind.CLICK] = OpKind.CLICK
    ref: str = ""


@dataclass(frozen=True)
class UploadOp:
    kind: Literal[OpKind.UPLOAD] = OpKind.UPLOAD
    ref: str = ""
    document_id: str = ""


@dataclass(frozen=True)
class ExtractOp:
    kind: Literal[OpKind.EXTRACT] = OpKind.EXTRACT
    ref: str | None = None
    shape: str = ""


@dataclass(frozen=True)
class AssertOp:
    kind: Literal[OpKind.ASSERT] = OpKind.ASSERT
    ref: str = ""
    predicate: str = ""


@dataclass(frozen=True)
class WaitOp:
    kind: Literal[OpKind.WAIT] = OpKind.WAIT
    for_: str = "visible"
    timeout: float = 10.0


@dataclass(frozen=True)
class StopOp:
    kind: Literal[OpKind.STOP] = OpKind.STOP
    reason: str = ""


# Union of all ops for type narrowing.
Op = GotoOp | FindOp | FillOp | SelectOp | ClickOp | UploadOp | ExtractOp | AssertOp | WaitOp | StopOp


@dataclass(frozen=True)
class Plan:
    """An ordered list of typed Ops emitted by the planner."""

    ops: tuple[Op, ...] = ()

    def __len__(self) -> int:
        return len(self.ops)

    def __iter__(self):
        return iter(self.ops)

    def __getitem__(self, index):
        return self.ops[index]
