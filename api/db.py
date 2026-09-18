"""STEP 1 — Neon Postgres + LangGraph checkpointing.

One Neon instance serves two purposes:
  1. Application data: repos, doc runs, and the deterministic call graph.
  2. LangGraph checkpoints, via PostgresSaver.

Using one database for both is deliberate — it avoids standing up a second
service purely for checkpoint state.
"""

import logging
from contextlib import contextmanager

from config import get_settings
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
_checkpointer: PostgresSaver | None = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    id            BIGSERIAL PRIMARY KEY,
    url           TEXT NOT NULL UNIQUE,
    default_branch TEXT,
    last_indexed_sha TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS doc_runs (
    id          BIGSERIAL PRIMARY KEY,
    repo_id     BIGINT REFERENCES repos(id) ON DELETE CASCADE,
    thread_id   TEXT NOT NULL,
    doc_type    TEXT NOT NULL,
    commit_sha  TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    output      TEXT,
    eval_report JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Deterministic call graph (STEP 3). Nodes are functions/classes/modules.
CREATE TABLE IF NOT EXISTS graph_nodes (
    id          BIGSERIAL PRIMARY KEY,
    repo_id     BIGINT REFERENCES repos(id) ON DELETE CASCADE,
    commit_sha  TEXT NOT NULL,
    node_key    TEXT NOT NULL,          -- e.g. "app/main.py::generate"
    kind        TEXT NOT NULL,          -- function | class | module
    name        TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    start_line  INT,
    end_line    INT,
    source      TEXT,
    UNIQUE (repo_id, commit_sha, node_key)
);

CREATE TABLE IF NOT EXISTS graph_edges (
    id          BIGSERIAL PRIMARY KEY,
    repo_id     BIGINT REFERENCES repos(id) ON DELETE CASCADE,
    commit_sha  TEXT NOT NULL,
    src_key     TEXT NOT NULL,
    dst_key     TEXT NOT NULL,
    edge_type   TEXT NOT NULL DEFAULT 'calls',   -- calls | imports | contains
    UNIQUE (repo_id, commit_sha, src_key, dst_key, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_nodes_repo_sha ON graph_nodes (repo_id, commit_sha);
CREATE INDEX IF NOT EXISTS idx_edges_src ON graph_edges (repo_id, commit_sha, src_key);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON graph_edges (repo_id, commit_sha, dst_key);
"""


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not set")
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=5,
            kwargs={"autocommit": True, "connect_timeout": 10},
            check=ConnectionPool.check_connection,
            reconnect_timeout=5,
            open=True,
        )
    return _pool


@contextmanager
def get_conn():
    with get_pool().connection() as conn:
        yield conn


def init_db() -> None:
    """Create application tables and LangGraph's checkpoint tables."""
    with get_conn() as conn:
        conn.execute(SCHEMA)
    get_checkpointer().setup()  # creates LangGraph's own checkpoint tables
    logger.info("Database schema initialised")


def get_checkpointer() -> PostgresSaver:
    """LangGraph checkpointer backed by the same Neon instance.

    This is what lets a run survive a Cloud Run instance restart and what
    makes the human-review pause in the evaluator loop actually work —
    InMemorySaver would lose that state the moment the instance recycles.
    """
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = PostgresSaver(conn=get_pool())  # pyright: ignore[reportArgumentType]
    return _checkpointer


# --- small helpers used by the rest of the app ---------------------------


def upsert_repo(url: str, default_branch: str | None = None) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO repos (url, default_branch)
            VALUES (%s, %s)
            ON CONFLICT (url) DO UPDATE SET default_branch = COALESCE(EXCLUDED.default_branch, repos.default_branch)
            RETURNING id
            """,
            (url, default_branch),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to upsert repo")
        return row[0]


def set_last_indexed_sha(repo_id: int, sha: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE repos SET last_indexed_sha = %s WHERE id = %s", (sha, repo_id)
        )


def get_last_indexed_sha(repo_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_indexed_sha FROM repos WHERE id = %s", (repo_id,)
        ).fetchone()
        return row[0] if row else None


def record_run(repo_id: int, thread_id: str, doc_type: str, commit_sha: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO doc_runs (repo_id, thread_id, doc_type, commit_sha)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (repo_id, thread_id, doc_type, commit_sha),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to record run")
        return row[0]


def complete_run(
    run_id: int, status: str, output: str | None, eval_report: dict[str, object] | None
) -> None:
    import json

    with get_conn() as conn:
        conn.execute(
            "UPDATE doc_runs SET status = %s, output = %s, eval_report = %s WHERE id = %s",
            (status, output, json.dumps(eval_report) if eval_report else None, run_id),
        )


def get_cached_run(repo_id: int, doc_type: str) -> dict | None:
    """Return the most recent completed run for this repo + doc_type, or None."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, thread_id, status FROM doc_runs
            WHERE repo_id = %s AND doc_type = %s AND status IN ('approved', 'needs_human_review')
            ORDER BY id DESC LIMIT 1
            """,
            (repo_id, doc_type),
        ).fetchone()
    if not row:
        return None
    return {"run_id": row[0], "thread_id": row[1], "status": row[2]}
