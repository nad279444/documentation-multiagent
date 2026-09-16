"""STEP 3 (cont.) — Persist the call graph to Postgres and traverse it.

The graph lives in the same Neon instance as everything else: two tables,
nodes and edges. No separate graph database — the queries needed here
(neighbours, topological order) are simple enough for SQL.
"""

import logging
from collections import defaultdict, deque

from db import get_conn
from schema import GraphNodeDict
from ingest.parser import ParsedRepo

logger = logging.getLogger(__name__)


def store_graph(repo_id: int, commit_sha: str, parsed: ParsedRepo) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO graph_nodes
                (repo_id, commit_sha, node_key, kind, name, file_path, start_line, end_line, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (repo_id, commit_sha, node_key) DO UPDATE
                SET source = EXCLUDED.source,
                    start_line = EXCLUDED.start_line,
                    end_line = EXCLUDED.end_line
            """,
            [
                (
                    repo_id,
                    commit_sha,
                    n.node_key,
                    n.kind,
                    n.name,
                    n.file_path,
                    n.start_line,
                    n.end_line,
                    n.source,
                )
                for n in parsed.nodes
            ],
        )
        cur.executemany(
            """
            INSERT INTO graph_edges (repo_id, commit_sha, src_key, dst_key, edge_type)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            [(repo_id, commit_sha, s, d, t) for s, d, t in parsed.edges],
        )
    logger.info(
        "Stored %d nodes / %d edges for repo %s @ %s",
        len(parsed.nodes),
        len(parsed.edges),
        repo_id,
        commit_sha[:8],
    )


def prune_stale(repo_id: int, commit_sha: str, keep_keys: set[str]) -> None:
    """Delete nodes/edges for files that no longer exist at this commit.

    Orphaned entries are a quiet source of hallucinated references to code
    that has since been deleted, so this runs on every incremental update.
    """
    if not keep_keys:
        return
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM graph_nodes WHERE repo_id = %s AND commit_sha = %s AND NOT (node_key = ANY(%s))",
            (repo_id, commit_sha, list(keep_keys)),
        )
        conn.execute(
            """
            DELETE FROM graph_edges WHERE repo_id = %s AND commit_sha = %s
              AND (NOT (src_key = ANY(%s)) OR NOT (dst_key = ANY(%s)))
            """,
            (repo_id, commit_sha, list(keep_keys), list(keep_keys)),
        )


def get_neighbours(
    repo_id: int, commit_sha: str, node_keys: list[str], hops: int = 1
) -> list[GraphNodeDict]:
    """Graph expansion: callers + callees of the given nodes, up to N hops."""
    if not node_keys:
        return []
    frontier = set(node_keys)
    collected: set[str] = set()

    with get_conn() as conn:
        for _ in range(hops):
            rows = conn.execute(
                """
                SELECT src_key, dst_key FROM graph_edges
                WHERE repo_id = %s AND commit_sha = %s
                  AND (src_key = ANY(%s) OR dst_key = ANY(%s))
                """,
                (repo_id, commit_sha, list(frontier), list(frontier)),
            ).fetchall()
            next_frontier = {k for row in rows for k in row} - frontier - collected
            collected |= next_frontier
            frontier = next_frontier
            if not frontier:
                break

        if not collected:
            return []
        rows = conn.execute(
            """
            SELECT node_key, kind, name, file_path, start_line, end_line, source
            FROM graph_nodes
            WHERE repo_id = %s AND commit_sha = %s AND node_key = ANY(%s)
            """,
            (repo_id, commit_sha, list(collected)),
        ).fetchall()

    return [
        {
            "node_key": r[0],
            "kind": r[1],
            "name": r[2],
            "file_path": r[3],
            "start_line": r[4],
            "end_line": r[5],
            "source": r[6],
        }
        for r in rows
    ]


def get_nodes(
    repo_id: int, commit_sha: str, kinds: tuple[str, ...] = ("module",)
) -> list[GraphNodeDict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT node_key, kind, name, file_path, source FROM graph_nodes
            WHERE repo_id = %s AND commit_sha = %s AND kind = ANY(%s)
            ORDER BY file_path
            """,
            (repo_id, commit_sha, list(kinds)),
        ).fetchall()
    result: list[GraphNodeDict] = [
        {
            "node_key": str(r[0]),
            "kind": str(r[1]),
            "name": str(r[2]),
            "file_path": str(r[3]),
            "source": str(r[4]) if r[4] is not None else None,
            "start_line": None,
            "end_line": None,
        }
        for r in rows
    ]
    return result


def topological_file_order(repo_id: int, commit_sha: str) -> list[str]:
    """Order files leaf-first for STEP 8's least-to-most decomposition.

    Files that depend on nothing else come first; files that depend on many
    others come last, so each generation step can reuse the already-written
    descriptions of its dependencies as context.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT n1.file_path AS src_file, n2.file_path AS dst_file
            FROM graph_edges e
            JOIN graph_nodes n1 ON n1.node_key = e.src_key
                 AND n1.repo_id = e.repo_id AND n1.commit_sha = e.commit_sha
            JOIN graph_nodes n2 ON n2.node_key = e.dst_key
                 AND n2.repo_id = e.repo_id AND n2.commit_sha = e.commit_sha
            WHERE e.repo_id = %s AND e.commit_sha = %s AND e.edge_type = 'calls'
              AND n1.file_path <> n2.file_path
            """,
            (repo_id, commit_sha),
        ).fetchall()
        files = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT file_path FROM graph_nodes WHERE repo_id = %s AND commit_sha = %s",
                (repo_id, commit_sha),
            ).fetchall()
        ]

    # Edge src -> dst means "src depends on dst", so dst must be documented first.
    dependents: dict[str, set[str]] = defaultdict(set)
    indegree: dict[str, int] = {f: 0 for f in files}
    for src, dst in rows:
        if src in indegree and dst in indegree and src not in dependents[dst]:
            dependents[dst].add(src)
            indegree[src] += 1

    queue = deque(sorted(f for f, d in indegree.items() if d == 0))
    ordered: list[str] = []
    while queue:
        current = queue.popleft()
        ordered.append(current)
        for dependent in sorted(dependents[current]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)

    # Cycles (circular imports) leave nodes unvisited — append them at the end.
    ordered.extend(sorted(f for f in files if f not in ordered))
    return ordered
