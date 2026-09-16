"""STEP 4 — Embed code chunks into Pinecone for vector search."""

import logging

from config import get_settings
from ingest.parser import ParsedRepo
from schema import ChunkDict

logger = logging.getLogger(__name__)

_pc = None
_index = None


def _get_index():
    """Lazy-init Pinecone index."""
    global _pc, _index
    if _index is not None:
        return _index

    from pinecone import Pinecone, ServerlessSpec

    settings = get_settings()
    if not settings.pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY is not set")

    _pc = Pinecone(api_key=settings.pinecone_api_key)
    index_name = settings.pinecone_index

    existing = [idx.name for idx in _pc.list_indexes()]
    if index_name not in existing:
        _pc.create_index(
            name=index_name,
            dimension=settings.embedding_dimensions,
            metric="cosine",
            spec=ServerlessSpec(
                cloud=settings.pinecone_cloud,
                region=settings.pinecone_region,
            ),
        )
        logger.info("Created Pinecone index '%s'", index_name)

    _index = _pc.Index(index_name)
    return _index


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using OpenAI embeddings."""
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    response = client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
        dimensions=settings.embedding_dimensions,
    )
    return [item.embedding for item in response.data]


def embed_repo(repo_id: int, commit_sha: str, parsed: ParsedRepo, batch_size: int = 100) -> int:
    """Embed parsed nodes into Pinecone. Returns the number of vectors upserted."""
    if not parsed.nodes:
        return 0

    index = _get_index()
    settings = get_settings()
    total = 0

    for i in range(0, len(parsed.nodes), batch_size):
        batch = parsed.nodes[i : i + batch_size]
        texts = []
        for node in batch:
            source = (node.source or "")[:4000]
            texts.append(f"{node.file_path} :: {node.name}\n{source}")

        embeddings = _embed_texts(texts)

        vectors = []
        for node, embedding in zip(batch, embeddings):
            vectors.append(
                {
                    "id": f"{repo_id}_{commit_sha}_{node.node_key}",
                    "values": embedding,
                    "metadata": {
                        "repo_id": repo_id,
                        "commit_sha": commit_sha,
                        "node_key": node.node_key,
                        "kind": node.kind,
                        "name": node.name,
                        "file_path": node.file_path,
                    },
                }
            )

        index.upsert(vectors=vectors)
        total += len(vectors)
        logger.info("Upserted batch %d-%d (%d vectors)", i, i + len(batch), total)

    logger.info("Embedded %d nodes for repo %s @ %s", total, repo_id, commit_sha[:8])
    return total


def delete_stale_vectors(repo_id: int, commit_sha: str) -> None:
    """Remove vectors for files that no longer exist at this commit."""
    index = _get_index()
    index.delete(
        filter={
            "repo_id": {"$eq": repo_id},
            "commit_sha": {"$ne": commit_sha},
        }
    )
    logger.info("Deleted stale vectors for repo %s (kept @ %s)", repo_id, commit_sha[:8])


def query(repo_id: int, commit_sha: str, query_text: str, top_k: int = 20) -> list[ChunkDict]:
    """Vector search for semantically similar code chunks."""
    index = _get_index()
    settings = get_settings()

    query_embedding = _embed_texts([query_text])[0]

    results = index.query(
        vector=query_embedding,
        top_k=top_k,
        filter={
            "repo_id": {"$eq": repo_id},
            "commit_sha": {"$eq": commit_sha},
        },
        include_metadata=True,
    )

    chunks: list[ChunkDict] = []
    for match in results.matches:
        meta = match.metadata
        chunks.append(
            {
                "node_key": meta["node_key"],
                "file_path": meta["file_path"],
                "name": meta["name"],
                "kind": meta["kind"],
                "start_line": None,
                "end_line": None,
                "source": None,
                "score": match.score,
                "origin": "vector",
            }
        )

    return chunks
