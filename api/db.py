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
CREATE TABLE IF NOT EXISTS users (
    id              BIGSERIAL PRIMARY KEY,
    google_id       TEXT NOT NULL UNIQUE,
    email           TEXT NOT NULL UNIQUE,
    name            TEXT,
    picture         TEXT,
    last_login      TIMESTAMPTZ DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id       TEXT NOT NULL UNIQUE,
    title           TEXT,
    last_activity   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id, last_activity DESC);

CREATE TABLE IF NOT EXISTS repos (
    id            BIGSERIAL PRIMARY KEY,
    url           TEXT NOT NULL UNIQUE,
    default_branch TEXT,
    last_indexed_sha TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS doc_runs (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT REFERENCES users(id) ON DELETE CASCADE,
    repo_id     BIGINT REFERENCES repos(id) ON DELETE CASCADE,
    thread_id   TEXT NOT NULL,
    doc_type    TEXT NOT NULL,
    commit_sha  TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    output      TEXT,
    eval_report JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotent migration for databases created before user_id was added.
ALTER TABLE doc_runs ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE CASCADE;

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

-- Persisted chat history shared across all runs of a repo (user + repo), so
-- switching between the API Reference and Architecture tabs shows the same
-- conversation and clearing deletes the entire thread.
--
-- Migration: an earlier local-only draft keyed messages per-run; drop it if
-- present so the workspace-keyed shape below is created instead.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'run_id'
    ) THEN
        DROP TABLE chat_messages;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS chat_messages (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    repo_id     BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,          -- user | assistant
    content     TEXT NOT NULL,
    edited      BOOLEAN NOT NULL DEFAULT FALSE,  -- assistant reply updated the doc
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_workspace ON chat_messages(user_id, repo_id, id);
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


def record_run(
    repo_id: int, user_id: int, thread_id: str, doc_type: str, commit_sha: str
) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO doc_runs (repo_id, user_id, thread_id, doc_type, commit_sha)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
            """,
            (repo_id, user_id, thread_id, doc_type, commit_sha),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to record run")
        return row[0]


def _json_report_default(obj: object) -> object:
    """Make any stray eval payload JSON-safe instead of failing the run.

    Sets/tuples (e.g. a bogus-citation set leaking out of a check) become
    lists; anything else falls back to its string form so complete_run can
    never blow up on an unserializable object.
    """
    if isinstance(obj, (set, tuple, frozenset)):
        return list(obj)
    try:
        return str(obj)
    except Exception:
        return f"<{type(obj).__name__}>"


def complete_run(
    run_id: int, status: str, output: str | None, eval_report: dict[str, object] | None
) -> None:
    import json

    with get_conn() as conn:
        conn.execute(
            "UPDATE doc_runs SET status = %s, output = %s, eval_report = %s WHERE id = %s",
            (
                status,
                output,
                json.dumps(eval_report, default=_json_report_default)
                if eval_report
                else None,
                run_id,
            ),
        )


def set_run_commit_sha(run_id: int, commit_sha: str) -> None:
    if not commit_sha:
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE doc_runs SET commit_sha = %s WHERE id = %s",
            (commit_sha, run_id),
        )


def get_cached_run(repo_id: int, user_id: int, doc_type: str) -> dict | None:
    """Return the most recent completed run and its source commit."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, thread_id, status, commit_sha FROM doc_runs
            WHERE repo_id = %s AND user_id = %s AND doc_type = %s AND status IN ('approved', 'needs_human_review')
            ORDER BY id DESC LIMIT 1
            """,
            (repo_id, user_id, doc_type),
        ).fetchone()
    if not row:
        return None
    return {
        "run_id": row[0],
        "thread_id": row[1],
        "status": row[2],
        "commit_sha": row[3],
    }


def get_or_create_user(google_id: str, email: str, name: str = "", picture: str = "") -> int:
    """Upsert a user from Google OAuth."""
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO users (google_id, email, name, picture)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (google_id) DO UPDATE
                SET last_login = now(),
                    email = EXCLUDED.email,
                    name = COALESCE(EXCLUDED.name, users.name),
                    picture = COALESCE(EXCLUDED.picture, users.picture)
            RETURNING id
            """,
            (google_id, email, name, picture),
        ).fetchone()
        return row[0]


def get_user_by_id(user_id: int) -> dict | None:
    """Get user info by ID."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, name, picture, created_at FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
    if row:
        return {
            "id": row[0],
            "email": row[1],
            "name": row[2],
            "picture": row[3],
            "created_at": row[4],
        }
    return None


def create_session(user_id: int, thread_id: str, title: str = "") -> int:
    """Create a conversation session for a user."""
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO user_sessions (user_id, thread_id, title)
            VALUES (%s, %s, %s) RETURNING id
            """,
            (user_id, thread_id, title or "Untitled"),
        ).fetchone()
        return row[0]


def get_user_sessions(user_id: int, limit: int = 20) -> list[dict]:
    """Get user's recent sessions."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, thread_id, title, last_activity, created_at
            FROM user_sessions WHERE user_id = %s
            ORDER BY last_activity DESC LIMIT %s
            """,
            (user_id, limit),
        ).fetchall()
    return [
        {
            "id": r[0],
            "thread_id": r[1],
            "title": r[2],
            "last_activity": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]


def update_session_activity(user_id: int, thread_id: str) -> None:
    """Update last_activity for a session."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE user_sessions SET last_activity = now() WHERE user_id = %s AND thread_id = %s",
            (user_id, thread_id),
        )


def get_recent_runs(user_id: int) -> list[dict]:
    """Latest completed run per doc_type, with the generated document.

    What the UI restores after a logout/login so the user lands back on their
    last document instead of a fresh submission form.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT ON (r.doc_type) r.id, r.doc_type, r.status, r.output, repos.url
            FROM doc_runs r JOIN repos ON repos.id = r.repo_id
            WHERE r.user_id = %s AND r.output IS NOT NULL AND r.status <> 'error'
            ORDER BY r.doc_type, r.id DESC
            """,
            (user_id,),
        ).fetchall()
    return [
        {
            "run_id": r[0],
            "doc_type": r[1],
            "status": r[2],
            "output": r[3],
            "repo_url": r[4],
        }
        for r in rows
    ]


def append_chat_message(
    user_id: int, repo_id: int, role: str, content: str, edited: bool = False
) -> None:
    """Persist one chat message for a user's repo workspace."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_messages (user_id, repo_id, role, content, edited) VALUES (%s, %s, %s, %s, %s)",
            (user_id, repo_id, role, content, edited),
        )


def get_chat_messages(user_id: int, repo_id: int) -> list[dict]:
    """Full persisted conversation for a workspace, oldest first."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content, edited FROM chat_messages WHERE user_id = %s AND repo_id = %s ORDER BY id",
            (user_id, repo_id),
        ).fetchall()
    return [
        {"role": r[0], "content": r[1], "edited": r[2]} for r in rows
    ]


def clear_chat_messages(user_id: int, repo_id: int) -> None:
    """Delete the entire conversation thread for a workspace."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM chat_messages WHERE user_id = %s AND repo_id = %s",
            (user_id, repo_id),
        )
