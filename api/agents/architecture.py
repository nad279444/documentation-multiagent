"""Agent for generating architecture documentation."""

import logging

from retrieval import retriever
from agents.common import get_llm, BASE_SYSTEM

logger = logging.getLogger(__name__)

ARCHITECTURE_SYSTEM = BASE_SYSTEM + (
    " Focus on system architecture: components, data flow, dependencies, "
    "and design patterns. Include Mermaid diagrams where helpful."
)

ARCHITECTURE_PROMPT = """Generate architecture documentation for this codebase.

Use the following code chunks as source material. Cite facts with [ref:NODE_KEY].

---
{context}
---"""


def generate_architecture_doc(
    repo_id: int,
    commit_sha: str,
    feedback: str | None = None,
) -> str:
    """Generate architecture documentation using retrieval-augmented generation.

    TODO: Implement full RAG pipeline. Returns a stub for now.
    """
    chunks = retriever.retrieve(
        repo_id, commit_sha, "architecture overview system design", top_k=8
    )
    context = retriever.format_context(chunks)

    prompt = ARCHITECTURE_PROMPT.format(context=context)
    if feedback:
        prompt += f"\n\nPrevious feedback to address:\n{feedback}"

    response = get_llm(temperature=0.0).invoke([
        {"role": "system", "content": ARCHITECTURE_SYSTEM},
        {"role": "user", "content": prompt},
    ])
    return str(response.content)
