"""FastAPI entrypoint.

Doc generation takes minutes, which is far too long for a synchronous HTTP
request, so /generate enqueues work and returns a run id immediately. In
production this hands off to Cloud Tasks; here BackgroundTasks keeps the
same shape without the extra infrastructure.
"""

import logging
import uuid
from contextlib import asynccontextmanager

from app.config import get_settings
from app.db import complete_run, get_conn, init_db, record_run, upsert_repo
from app.graphs.doc_graph import build_graph
from app.ingest.cloner import IngestError, validate_repo_url
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

_graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    try:
        init_db()
        from api.db import get_checkpointer

        _graph = build_graph(checkpointer=get_checkpointer())
        logger.info("Graph compiled with Postgres checkpointing")
    except Exception as exc:
        # Still serve /health so Cloud Run doesn't flap while config is fixed.
        logger.error("Startup incomplete: %s", exc)
        _graph = build_graph(checkpointer=None)
    yield


app = FastAPI(title="Documentation Agent", lifespan=lifespan)


class GenerateRequest(BaseModel):
    repo_url: str = Field(..., examples=["https://github.com/tiangolo/fastapi"])
    doc_type: str = Field("api", pattern="^(api|architecture)$")
    branch: str | None = None


class GenerateResponse(BaseModel):
    run_id: int
    thread_id: str
    status: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest, background: BackgroundTasks):
    # Input guardrail: reject bad URLs before any work is queued.
    try:
        clean_url = validate_repo_url(req.repo_url)
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    repo_id = upsert_repo(clean_url, req.branch)
    thread_id = str(uuid.uuid4())
    run_id = record_run(repo_id, thread_id, req.doc_type, commit_sha="")

    background.add_task(_run_pipeline, run_id, thread_id, req)
    return GenerateResponse(run_id=run_id, thread_id=thread_id, status="queued")


def _run_pipeline(run_id: int, thread_id: str, req: GenerateRequest) -> None:
    try:
        result = _graph.invoke(
            {
                "repo_url": req.repo_url,
                "doc_type": req.doc_type,
                "branch": req.branch,
                "retry_count": 0,
            },
            config={"configurable": {"thread_id": thread_id}},
        )
        complete_run(
            run_id,
            status=result.get("status", "unknown"),
            output=result.get("draft"),
            eval_report=result.get("eval_result"),
        )
        logger.info("Run %s finished: %s", run_id, result.get("status"))
    except Exception as exc:
        logger.exception("Run %s failed", run_id)
        complete_run(
            run_id, status="error", output=None, eval_report={"error": str(exc)}
        )


@app.get("/runs/{run_id}")
def get_run(run_id: int):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT r.id, r.status, r.doc_type, r.commit_sha, r.output, r.eval_report, repos.url
            FROM doc_runs r JOIN repos ON repos.id = r.repo_id WHERE r.id = %s
            """,
            (run_id,),
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
