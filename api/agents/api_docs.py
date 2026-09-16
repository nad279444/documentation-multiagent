"""Agent for generating API reference documentation."""

import logging

from retrieval import retriever
from schema import ChunkDict, EndpointDict
from agents.common import extract_endpoints, get_llm, BASE_SYSTEM

logger = logging.getLogger(__name__)

API_DOCS_SYSTEM = BASE_SYSTEM + (
    " Focus on API endpoints: HTTP methods, paths, parameters, request/response "
    "schemas, and usage examples. Include code snippets from the source."
)

API_DOCS_PROMPT = """Generate API reference documentation for this codebase.

Use the following code chunks as source material. Cite facts with [ref:NODE_KEY].

---
{context}
---"""


def generate_api_docs(
    repo_id: int,
    commit_sha: str,
    feedback: str | None = None,
) -> tuple[str, list[EndpointDict]]:
    """Generate API documentation using retrieval-augmented generation.

    Returns (document_text, extracted_endpoints).
    TODO: Implement full RAG pipeline. Returns stubs for now.
    """
    chunks: list[ChunkDict] = retriever.retrieve(
        repo_id, commit_sha, "API endpoints HTTP routes", top_k=8
    )
    context = retriever.format_context(chunks)

    prompt = API_DOCS_PROMPT.format(context=context)
    if feedback:
        prompt += f"\n\nPrevious feedback to address:\n{feedback}"

    response = get_llm(temperature=0.0).invoke([
        {"role": "system", "content": API_DOCS_SYSTEM},
        {"role": "user", "content": prompt},
    ])

    doc = str(response.content)
    endpoints = extract_endpoints(chunks)
    return doc, endpoints
