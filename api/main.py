"""FastAPI entrypoint.

Doc generation takes minutes, which is far too long for a synchronous HTTP
request, so /generate enqueues work and returns a run id immediately. In
production this hands off to Cloud Tasks; here BackgroundTasks keeps the
same shape without the extra infrastructure.
"""

import json
import logging
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager

from auth import get_current_user
from config import get_settings
from db import (
    append_chat_message,
    clear_chat_messages,
    complete_run,
    create_session,
    get_cached_run,
    get_chat_messages,
    get_conn,
    get_recent_runs,
    get_user_sessions,
    init_db,
    record_run,
    set_run_commit_sha,
    upsert_repo,
)
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from graphs.doc_graph import build_graph
from ingest.cloner import IngestError, get_remote_head_sha, validate_repo_url
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

_graph = None

# In-memory chat reply cache: (run_id, message, document) -> (timestamp, response).
# Repeated identical questions skip the retrieval + LLM round trip entirely.
_chat_cache: dict[tuple[int, str, str], tuple[float, "ChatResponseModel"]] = {}
_CHAT_CACHE_MAX = 128
_CHAT_CACHE_TTL_SECONDS = 600

# Per-run SSE event buffers. The background pipeline writes stage/token/done
# events here and GET /runs/{id}/stream reads them, so the frontend sees
# progress live instead of waiting for the run to finish.
_HB = object()  # heartbeat sentinel
_EOS = object()  # end-of-stream sentinel


class RunEventBuffer:
    """Thread-safe event channel feeding one or more SSE clients."""

    def __init__(self) -> None:
        self._items: deque[dict] = deque()
        self._cond = threading.Condition()
        self._finished = False

    def push(self, item: dict) -> None:
        with self._cond:
            if self._finished:
                return
            self._items.append(item)
            self._cond.notify_all()

    def close(self) -> None:
        with self._cond:
            self._finished = True
            self._cond.notify_all()

    def _pop(self) -> object:
        with self._cond:
            if self._items:
                return self._items.popleft()
            if self._finished:
                return _EOS
            self._cond.wait(timeout=15.0)
            if self._items:
                return self._items.popleft()
            return _HB

    def events(self):
        while True:
            item = self._pop()
            if item is _HB:
                yield ": ping\n\n"
                continue
            if item is _EOS:
                return
            yield f"data: {json.dumps(item)}\n\n"


_buffers: dict[int, RunEventBuffer] = {}
_buffers_lock = threading.Lock()


def _buffer_for(run_id: int) -> RunEventBuffer:
    with _buffers_lock:
        buf = _buffers.get(run_id)
        if buf is None:
            buf = RunEventBuffer()
            _buffers[run_id] = buf
        return buf


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    try:
        init_db()
        from db import get_checkpointer

        _graph = build_graph(checkpointer=get_checkpointer())
        logger.info("Graph compiled with Postgres checkpointing")
    except Exception as exc:
        # Still serve /health so Cloud Run doesn't flap while config is fixed.
        logger.error("Startup incomplete: %s", exc)
        _graph = build_graph(checkpointer=None)
    yield


app = FastAPI(title="Documentation Agent", lifespan=lifespan)

# CORS: the frontend runs on a separate origin in dev (Vite) and production.
origins = [
    "http://localhost:5173",  # local dev (Vite)
    "http://localhost:3000",  # alternative dev
    "https://documentation-multiagent-qnzpfn7mea-uc.a.run.app/",  # production — replace with your domain
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    repo_url: str = Field(..., examples=["https://github.com/tiangolo/fastapi"])
    doc_type: str = Field("api", pattern="^(api|architecture)$")
    branch: str | None = None


class GenerateResponse(BaseModel):
    run_id: int
    thread_id: str
    status: str
    cached: bool = False


class AuthResponse(BaseModel):
    user_id: int
    email: str
    name: str
    picture: str
    sessions: list[dict]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/verify", response_model=AuthResponse)
async def verify_auth(user: dict = Depends(get_current_user)):
    """Verify token and return user info + sessions."""
    sessions = get_user_sessions(user["id"], limit=20)
    return AuthResponse(
        user_id=user["id"],
        email=user["email"],
        name=user["name"],
        picture=user["picture"],
        sessions=sessions,
    )


@app.post("/generate", response_model=GenerateResponse)
def generate(
    req: GenerateRequest,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),  # Require auth
):
    # Input guardrail: reject bad URLs before any work is queued.
    try:
        clean_url = validate_repo_url(req.repo_url)
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    repo_id = upsert_repo(clean_url, req.branch)

    cached = get_cached_run(repo_id, user["id"], req.doc_type)
    if cached:
        current_sha = None
        if cached.get("commit_sha"):
            try:
                current_sha = get_remote_head_sha(clean_url, req.branch)
            except IngestError as exc:
                logger.warning(
                    "Remote commit check failed for %s; treating cache as stale: %s",
                    clean_url,
                    exc,
                )
        if current_sha and current_sha == cached.get("commit_sha"):
            logger.info(
                "Cache hit: returning existing run %s for %s [%s @ %s]",
                cached["run_id"],
                clean_url,
                req.doc_type,
                current_sha[:8],
            )
            return GenerateResponse(
                run_id=cached["run_id"],
                thread_id=cached["thread_id"],
                status=cached["status"],
                cached=True,
            )
        logger.info(
            "Cache miss for %s [%s]: remote=%s cached=%s",
            clean_url,
            req.doc_type,
            current_sha[:8] if current_sha else "unknown",
            (cached.get("commit_sha") or "unknown")[:8],
        )

    thread_id = str(uuid.uuid4())

    # Create session for this conversation
    create_session(
        user["id"],
        thread_id,
        title=f"{req.doc_type.title()} - {clean_url.split('/')[-1]}",
    )

    run_id = record_run(repo_id, user["id"], thread_id, req.doc_type, commit_sha="")

    background.add_task(_run_pipeline, run_id, thread_id, req)
    return GenerateResponse(run_id=run_id, thread_id=thread_id, status="queued")


def _run_pipeline(run_id: int, thread_id: str, req: GenerateRequest) -> None:
    buffer = _buffer_for(run_id)
    if _graph is None:
        complete_run(
            run_id,
            status="error",
            output=None,
            eval_report={"error": "Graph not initialized"},
        )
        buffer.push({"type": "error", "error": "Graph not initialized"})
        buffer.close()
        return

    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "run_name": f"doc-generate-{req.doc_type}",
        "tags": ["doc-agent", f"type:{req.doc_type}"],
        "metadata": {
            "repo_url": req.repo_url,
            "llm_model": get_settings().llm_model,
        },
    }

    final_state: dict = {}
    try:
        # stream_mode="custom" carries the node stage events, "messages" the
        # generated-token chunks, and "updates" lets us assemble the final
        # state without a second get_state round-trip.
        stream = _graph.stream(
            {
                "repo_url": req.repo_url,
                "doc_type": req.doc_type,
                "branch": req.branch,
                "retry_count": 0,
            },
            config=config,
            stream_mode=["custom", "messages", "updates"],
        )

        for mode, payload in stream:
            if mode == "custom":
                if isinstance(payload, dict) and payload.get("type") == "stage":
                    buffer.push(payload)
            elif mode == "updates":
                payload_dict: dict[str, object] = (
                    payload if isinstance(payload, dict) else {}
                )
                for update in payload_dict.values():
                    if isinstance(update, dict):
                        final_state.update(update)
            elif mode == "messages":
                token = _extract_generate_token(payload)
                if token:
                    buffer.push({"type": "token", "text": token})

        # Prefer the checkpointed state (authoritative) over merged updates.
        try:
            checkpoint = _graph.get_state(config).values
            if checkpoint:
                final_state = checkpoint
        except Exception:
            pass

        set_run_commit_sha(run_id, str(final_state.get("commit_sha") or ""))
        complete_run(
            run_id,
            status=final_state.get("status", "unknown"),
            output=final_state.get("draft"),
            eval_report=final_state.get("eval_result"),
        )
        buffer.push(
            {
                "type": "done",
                "status": final_state.get("status", "unknown"),
                "has_doc": bool(final_state.get("draft")),
            }
        )
        logger.info("Run %s finished: %s", run_id, final_state.get("status"))
    except Exception as exc:
        logger.exception("Run %s failed", run_id)
        complete_run(
            run_id, status="error", output=None, eval_report={"error": str(exc)}
        )
        buffer.push({"type": "error", "error": str(exc)})
    finally:
        buffer.close()


def _extract_generate_token(payload) -> str | None:
    """Token text from a (chunk, metadata) messages payload, only for generation.

    The evaluator still uses invoke(), so every streamed token that reaches the
    client is real document prose, not judge chatter.
    """
    try:
        chunk, metadata = payload
    except (TypeError, ValueError):
        return None
    if (metadata or {}).get("langgraph_node") != "generate":
        return None
    content = getattr(chunk, "content", None)
    if not content:
        return None
    return content if isinstance(content, str) else str(content)


_TERMINAL_STATUSES = (
    "passed",
    "approved",
    "needs_revision",
    "needs_human_review",
    "error",
)


def _terminal_done(status: str):
    yield f"data: {json.dumps({'type': 'done', 'status': status, 'has_doc': True})}\n\n"


@app.get("/runs/{run_id}/stream")
def stream_run(run_id: int, user: dict = Depends(get_current_user)):
    """Server-Sent Events: stage + token progress for one run (owner only)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM doc_runs WHERE id = %s AND user_id = %s",
            (run_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")

    if row[0] in _TERMINAL_STATUSES:
        # Already finished: emit a single done event so the client can stop.
        return StreamingResponse(
            _terminal_done(row[0]),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    return StreamingResponse(
        _buffer_for(run_id).events(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@app.get("/runs")
def recent_runs(user: dict = Depends(get_current_user)):
    """Latest completed document per doc_type — used to restore a session."""
    return {"runs": get_recent_runs(user["id"])}


@app.get("/runs/{run_id}")
def get_run(run_id: int, user: dict = Depends(get_current_user)):
    """Get run (only accessible by owner)."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT r.id, r.status, r.doc_type, r.commit_sha, r.output, r.eval_report, repos.url
            FROM doc_runs r JOIN repos ON repos.id = r.repo_id
            WHERE r.id = %s AND r.user_id = %s
            """,
            (run_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "run_id": row[0],
        "status": row[1],
        "doc_type": row[2],
        "commit_sha": row[3],
        "output": row[4],
        "eval_report": row[5],
        "repo_url": row[6],
    }


@app.get("/sessions")
def list_sessions(user: dict = Depends(get_current_user)):
    """List user's sessions."""
    sessions = get_user_sessions(user["id"], limit=50)
    return {"sessions": sessions}


@app.get("/runs/{run_id}/document", response_model=None)
def get_document(run_id: int):
    from fastapi.responses import PlainTextResponse

    with get_conn() as conn:
        row = conn.execute(
            "SELECT output FROM doc_runs WHERE id = %s", (run_id,)
        ).fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="No document available yet")
    return PlainTextResponse(row[0], media_type="text/markdown")


# --- Chat endpoint -------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class ChatResponseModel(BaseModel):
    reply: str
    document: str
    edited: bool


@app.post("/runs/{run_id}/chat", response_model=ChatResponseModel)
def chat_with_document(
    run_id: int, req: ChatRequest, user: dict = Depends(get_current_user)
):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT r.output, r.repo_id, r.user_id, repos.last_indexed_sha
            FROM doc_runs r JOIN repos ON repos.id = r.repo_id
            WHERE r.id = %s
            """,
            (run_id,),
        ).fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="No document available yet")
    if row[2] != user["id"]:
        raise HTTPException(status_code=404, detail="Run not found")

    document, repo_id, _, commit_sha = row

    # Cache hit: exact same question on the same document version.
    now = time.time()
    cache_key = (run_id, req.message, document)
    cached = _chat_cache.get(cache_key)
    if cached and now - cached[0] < _CHAT_CACHE_TTL_SECONDS:
        logger.info("Chat cache hit for run %s: '%s'", run_id, req.message[:80])
        return cached[1]

    # Wire the chat into the retrieval pipeline: vector search -> graph
    # expansion -> rerank. Gives the agent the same grounded source context
    # the generator uses, so answers can cite [ref:NODE_KEY] chunks.
    source_context = ""
    if repo_id and commit_sha:
        try:
            from retrieval import retriever

            chunks = retriever.retrieve(repo_id, commit_sha, req.message, top_k=4)
            source_context = retriever.format_context(chunks)
        except Exception as exc:
            logger.warning(
                "Chat retrieval unavailable (%s); falling back to document only", exc
            )

    from agents.chat import chat as agent_chat

    result = agent_chat(
        user_message=req.message, document=document, source_context=source_context
    )

    # Persist the conversation in the workspace thread (user + repo), shared
    # by both document tabs, so it survives logout/login and tab switches.
    append_chat_message(user["id"], repo_id, "user", req.message)
    append_chat_message(
        user["id"], repo_id, "assistant", result.reply, edited=result.edited
    )

    response = ChatResponseModel(
        reply=result.reply, document=result.document, edited=result.edited
    )

    if result.edited:
        with get_conn() as conn:
            conn.execute(
                "UPDATE doc_runs SET output = %s WHERE id = %s",
                (result.document, run_id),
            )

    # Only cache non-edit replies — an edit changes the document, so the cache
    # key already covers staleness and the edited doc is persisted above.
    if not result.edited:
        _chat_cache[cache_key] = (now, response)
        if len(_chat_cache) > _CHAT_CACHE_MAX:
            oldest = min(_chat_cache, key=lambda k: _chat_cache[k][0])
            del _chat_cache[oldest]

    return response


def _run_workspace(run_id: int, user: dict) -> int:
    """404 unless the run exists and belongs to the user; returns its repo_id."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT repo_id FROM doc_runs WHERE id = %s AND user_id = %s",
            (run_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return row[0]


@app.get("/runs/{run_id}/chat/history")
def chat_history(run_id: int, user: dict = Depends(get_current_user)):
    """Persisted conversation for the run's workspace (owner only)."""
    repo_id = _run_workspace(run_id, user)
    return {"messages": get_chat_messages(user["id"], repo_id)}


@app.delete("/runs/{run_id}/chat")
def delete_chat_history(run_id: int, user: dict = Depends(get_current_user)):
    """Clear the entire conversation thread for the run's workspace (owner only)."""
    repo_id = _run_workspace(run_id, user)
    clear_chat_messages(user["id"], repo_id)
    return {"ok": True}
