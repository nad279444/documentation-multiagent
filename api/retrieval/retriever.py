"""STEP 5 — Graph-augmented retrieval.

Vector search finds semantically similar code; graph expansion then pulls
in the callers and callees of those hits, which embeddings alone routinely
miss (a caller can be worded nothing like the function it calls).

Expansion is a *structural* move, so it drags in some irrelevant neighbours.
Reranking narrows the combined pool back down before anything reaches the
generator — which improves quality and cuts input tokens at the same time.
"""

import logging
import os

from config import get_settings
from db import get_conn
from ingest.graph_store import get_neighbours
from schema import ChunkDict
from retrieval import embeddings

logger = logging.getLogger(__name__)


def _fetch_sources(repo_id: int, commit_sha: str, node_keys: list[str]) -> dict[str, str]:
    """Fetch source code from Postgres for nodes that came from vector search."""
    if not node_keys:
        return {}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT node_key, source FROM graph_nodes WHERE repo_id = %s AND commit_sha = %s AND node_key = ANY(%s)",
            (repo_id, commit_sha, node_keys),
        ).fetchall()
    return {r[0]: r[1] for r in rows if r[1]}


def retrieve(
    repo_id: int,
    commit_sha: str,
    query_text: str,
    top_k: int | None = None,
    vector_k: int = 20,
    hops: int = 1,
) -> list[ChunkDict]:
    """Retrieve broad (vector + graph), rerank narrow, return the top chunks."""
    settings = get_settings()
    top_k = top_k or settings.retrieval_top_k

    # 1. Vector search — semantic seeds
    seeds = embeddings.query(repo_id, commit_sha, query_text, top_k=vector_k)
    seed_keys = [s["node_key"] for s in seeds]

    # 1b. Fetch source code from Postgres for vector search results
    sources = _fetch_sources(repo_id, commit_sha, seed_keys)
    for seed in seeds:
        if seed["node_key"] in sources:
            seed["source"] = sources[seed["node_key"]]

    # 2. Graph expansion — structural neighbours of those seeds
    neighbours = get_neighbours(repo_id, commit_sha, seed_keys, hops=hops)

    # 3. Merge, de-duplicated, seeds keep their similarity score
    pool: dict[str, ChunkDict] = {}
    for item in seeds:
        pool[item["node_key"]] = {**item, "origin": "vector"}
    for item in neighbours:
        pool.setdefault(item["node_key"], {**item, "score": 0.0, "origin": "graph"})

    candidates = list(pool.values())
    if not candidates:
        return []

    # 4. Rerank the combined pool, then keep only the top slice
    ranked = rerank(query_text, candidates, top_k=top_k)
    logger.info(
        "Retrieved %d candidates (%d vector, %d graph) -> %d after rerank",
        len(candidates),
        len(seeds),
        len(neighbours),
        len(ranked),
    )
    return ranked


def rerank(query_text: str, candidates: list[ChunkDict], top_k: int) -> list[ChunkDict]:
    """Rerank with a cheap dedicated model, never the main LLM.

    Falls back to vector score ordering when no reranker key is configured,
    so the pipeline works before you add a reranking provider.
    """
    api_key = os.environ.get("COHERE_API_KEY")
    if not api_key:
        return sorted(candidates, key=lambda c: c.get("score", 0.0), reverse=True)[
            :top_k
        ]

    try:
        import cohere

        client = cohere.Client(api_key)
        docs = [
            f"{c['file_path']} :: {c['name']}\n{(c.get('source') or '')[:2000]}"
            for c in candidates
        ]
        response = client.rerank(
            model="rerank-english-v3.0",
            query=query_text,
            documents=docs,
            top_n=min(top_k, len(docs)),
        )
        return [
            {**candidates[r.index], "score": r.relevance_score, "origin": "reranked"}
            for r in response.results
        ]
    except Exception as exc:
        logger.warning("Rerank failed (%s); falling back to vector order", exc)
        return sorted(candidates, key=lambda c: c.get("score", 0.0), reverse=True)[
            :top_k
        ]


def format_context(chunks: list[ChunkDict]) -> str:
    """Render chunks for a prompt, tagged so citations can be verified later.

    Repo content is untrusted data, never instructions — the delimiters and
    the system prompt together are what enforce that.
    """
    parts: list[str] = []
    for chunk in chunks:
        start = chunk.get("start_line")
        end = chunk.get("end_line")
        source = (chunk.get("source") or "")[:4000]
        parts.append(
            f'<chunk node_key="{chunk["node_key"]}" file="{chunk["file_path"]}" '
            f'lines="{start}-{end}">\n{source}\n</chunk>'
        )
    return "\n\n".join(parts)
