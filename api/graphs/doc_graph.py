"""The LangGraph state machine: ingest -> generate -> evaluate -> (revise | publish).

State stays deliberately small — structured fields only, no accumulated
message history — so nothing unnecessary is re-sent on every node call.

The retry cap is both a correctness guardrail (no infinite loops) and a
cost guardrail (each revise cycle is a full generation call).
"""

import logging
from typing import Literal, TypedDict

from agents import api_docs, architecture, evaluator
from config import get_settings
from db import get_last_indexed_sha, set_last_indexed_sha, upsert_repo
from ingest import cloner, graph_store, parser
from retrieval import embeddings
from schema import (
    API_DOC_TEMPLATE,
    ARCHITECTURE_TEMPLATE,
    EndpointDict,
    EvalResultDict,
)
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)


class DocState(TypedDict, total=False):
    # inputs
    repo_url: str
    doc_type: str  # "api" | "architecture"
    branch: str | None
    # populated by ingest
    repo_id: int
    commit_sha: str
    chunk_count: int
    skipped_secrets: list[str]
    # generation / evaluation
    draft: str
    endpoints: list[EndpointDict]
    eval_result: EvalResultDict
    feedback: str
    retry_count: int
    status: str


# --- nodes ---------------------------------------------------------------


def _emit_stage(stage: str, **payload) -> None:
    """Broadcast a progress stage to stream_mode='custom' consumers.

    A no-op when the graph runs without stream_mode='custom' (invoke), so
    exposing this never changes normal execution.
    """
    try:
        get_stream_writer()({"type": "stage", "stage": stage, **payload})
    except Exception:
        pass


def ingest_node(state: DocState) -> DocState:
    """STEPS 2-4: clone, parse, store the graph, embed. Incremental when possible."""
    _emit_stage("cloning", repo_url=state.get("repo_url", ""))
    repo = cloner.clone_repo(state.get("repo_url", ""), state.get("branch"))
    try:
        repo_id = upsert_repo(repo.url)
        previous_sha = get_last_indexed_sha(repo_id)

        if previous_sha == repo.commit_sha:
            logger.info(
                "Repo already indexed at %s — skipping re-embed", repo.commit_sha[:8]
            )
            _emit_stage("embedding", indexed=True)
            return {
                **state,
                "repo_id": repo_id,
                "commit_sha": repo.commit_sha,
                "chunk_count": 0,
                "skipped_secrets": repo.skipped_secrets,
                "retry_count": 0,
            }

        # Diff-based incremental indexing: only changed files, plus their neighbours.
        changed = cloner.changed_files(repo, previous_sha)
        parsed = parser.parse_repo(repo, only_files=changed)

        graph_store.store_graph(repo_id, repo.commit_sha, parsed)
        graph_store.prune_stale(
            repo_id, repo.commit_sha, {n.node_key for n in parsed.nodes}
        )
        _emit_stage("embedding", indexed=False)
        count = embeddings.embed_repo(repo_id, repo.commit_sha, parsed)
        embeddings.delete_stale_vectors(repo_id, repo.commit_sha)
        set_last_indexed_sha(repo_id, repo.commit_sha)

        return {
            **state,
            "repo_id": repo_id,
            "commit_sha": repo.commit_sha,
            "chunk_count": count,
            "skipped_secrets": repo.skipped_secrets,
            "retry_count": 0,
        }
    finally:
        repo.cleanup()  # Cloud Run's disk is ephemeral and small


def generate_node(state: DocState) -> DocState:
    """STEP 6 / STEP 8: produce a draft, incorporating evaluator feedback if any."""
    feedback = state.get("feedback") or None
    retry = state.get("retry_count", 0)
    doc_type = state.get("doc_type", "api")
    repo_id = state.get("repo_id", 0)
    commit_sha = state.get("commit_sha", "")

    _emit_stage("generating", doc_type=doc_type, retry=retry + 1 if feedback else 1)

    if doc_type == "architecture":
        draft = architecture.generate_architecture_doc(
            repo_id, commit_sha, feedback=feedback
        )
        endpoints: list[EndpointDict] = []
    else:
        draft, endpoints = api_docs.generate_api_docs(
            repo_id, commit_sha, feedback=feedback
        )

    # Incremented here, not in the evaluator, so feedback carries forward.
    result: DocState = {
        **state,
        "draft": draft,
        "endpoints": endpoints,
        "retry_count": retry + 1 if feedback else retry,
    }
    return result


def evaluate_node(state: DocState) -> DocState:
    """STEP 7: deterministic checks first, LLM judge only if those pass."""
    _emit_stage("evaluating")
    doc_type = state.get("doc_type", "api")
    template = API_DOC_TEMPLATE if doc_type == "api" else ARCHITECTURE_TEMPLATE
    result = evaluator.evaluate(
        doc=state.get("draft", ""),
        repo_id=state.get("repo_id", 0),
        commit_sha=state.get("commit_sha", ""),
        expected_endpoints=state.get("endpoints")
        if doc_type == "api"
        else None,
        template=template,
    )
    evaluator.push_eval_feedback(
        result.get("metrics", {}),
        run_id=_langsmith_run_id(),
        comment=result.get("feedback", ""),
    )
    return {**state, "eval_result": result, "feedback": result.get("feedback", "")}


def _langsmith_run_id() -> str | None:
    """The id of the current traced run, or None when tracing is disabled."""
    try:
        from langsmith.run_helpers import get_current_run_tree

        tree = get_current_run_tree()
        if tree is None:
            return None
        # Attach feedback to the trace root so it surfaces on the whole run.
        return str(tree.trace_id or tree.id)
    except Exception:
        return None


def publish_node(state: DocState) -> DocState:
    _emit_stage("approved")
    return {**state, "status": "passed"}


def human_review_node(state: DocState) -> DocState:
    """Escalation after the retry cap — the doc is kept, flagged, not discarded."""
    logger.warning(
        "Escalating to human review after %d attempts", state.get("retry_count", 0)
    )
    _emit_stage("needs_human_review")
    return {**state, "status": "needs_human_review"}


# --- routing -------------------------------------------------------------


def route_after_eval(state: DocState) -> Literal["publish", "generate", "human_review"]:
    eval_result = state.get("eval_result", {})
    if eval_result.get("passed", False):
        return "publish"
    if state.get("retry_count", 0) >= get_settings().max_eval_retries:
        return "human_review"
    return "generate"


def build_graph(checkpointer=None):
    builder = StateGraph(DocState)
    builder.add_node("ingest", ingest_node)
    builder.add_node("generate", generate_node)
    builder.add_node("evaluate", evaluate_node)
    builder.add_node("publish", publish_node)
    builder.add_node("human_review", human_review_node)

    builder.set_entry_point("ingest")
    builder.add_edge("ingest", "generate")
    builder.add_edge("generate", "evaluate")
    builder.add_conditional_edges(
        "evaluate",
        route_after_eval,
        {
            "publish": "publish",
            "generate": "generate",
            "human_review": "human_review",
        },
    )
    builder.add_edge("publish", END)
    builder.add_edge("human_review", END)

    return builder.compile(checkpointer=checkpointer)
