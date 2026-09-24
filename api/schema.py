"""Shared type definitions for the codebase."""

from typing import NotRequired, TypedDict


class ChunkDict(TypedDict):
    """A retrieved code chunk."""
    node_key: str
    kind: str
    name: str
    file_path: str
    start_line: int | None
    end_line: int | None
    source: str | None
    score: float
    origin: str


class GraphNodeDict(TypedDict):
    """A node from the code graph."""
    node_key: str
    kind: str
    name: str
    file_path: str
    start_line: int | None
    end_line: int | None
    source: str | None


class EndpointDict(TypedDict):
    """An HTTP endpoint extracted from code."""
    method: str
    path: str
    node_key: str
    file_path: str


class EvalCheckDict(TypedDict):
    """Result of a single evaluation check."""
    passed: bool
    detail: str
    score: NotRequired[float]
    meta: NotRequired[dict[str, object]]


class EvalResultDict(TypedDict):
    """Result of document evaluation."""
    passed: bool
    checks: dict[str, EvalCheckDict]
    feedback: str
    metrics: NotRequired[dict[str, float]]


# --- Document template contract -------------------------------------------
# Single source of truth shared by the generator prompts (section list and
# examples must stay consistent with this) and the evaluator
# (_check_schema validates a generated doc against these headings).

API_DOC_TEMPLATE = [
    "Overview",
    "Authentication",
    "Endpoints",
    "Request / Response Schemas",
    "Errors",
    "Usage Examples",
]

ARCHITECTURE_TEMPLATE = [
    "Overview",
    "Components",
    "Data Flow",
    "Dependencies",
    "Design Patterns",
    "Diagrams",
]
