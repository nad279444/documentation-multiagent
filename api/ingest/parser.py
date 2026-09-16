"""STEP 2 (cont.) — Parse repo files into a structured graph representation."""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class GraphNode:
    node_key: str
    kind: str  # function | class | module
    name: str
    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    source: str | None = None


@dataclass
class ParsedRepo:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[tuple[str, str, str]] = field(default_factory=list)  # (src_key, dst_key, edge_type)


def parse_repo(repo, only_files: set[str] | None = None) -> ParsedRepo:
    """Parse repo files into a graph of nodes and edges.

    TODO: Implement tree-sitter based parsing for real code graph extraction.
    For now, returns a minimal stub so the pipeline can be tested end-to-end.
    """
    parsed = ParsedRepo()
    files_to_parse = repo.files if only_files is None else [
        f for f in repo.files if f.path in only_files
    ]

    for file in files_to_parse:
        node_key = f"{file.path}::module"
        parsed.nodes.append(
            GraphNode(
                node_key=node_key,
                kind="module",
                name=file.path,
                file_path=file.path,
                source=file.text[:4000] if file.text else None,
            )
        )

    logger.info("Parsed %d files into %d nodes", len(files_to_parse), len(parsed.nodes))
    return parsed
