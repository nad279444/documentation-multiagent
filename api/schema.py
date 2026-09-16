"""Shared type definitions for the codebase."""

from typing import TypedDict


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


class EvalResultDict(TypedDict):
    """Result of document evaluation."""
    passed: bool
    checks: dict[str, EvalCheckDict]
    feedback: str
