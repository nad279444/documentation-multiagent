"""Agent for generating API reference documentation."""

import logging

from retrieval import retriever
from schema import API_DOC_TEMPLATE, ChunkDict, EndpointDict
from agents.common import extract_endpoints, get_llm, BASE_SYSTEM

logger = logging.getLogger(__name__)

API_DOCS_SYSTEM = BASE_SYSTEM + (
    " Focus on API endpoints: HTTP methods, paths, parameters, request/response "
    "schemas, and usage examples. Include code snippets from the source. "
    "Use these exact headings, in this order, as H2 (##) sections:\n"
    + "\n".join(f"- {heading}" for heading in API_DOC_TEMPLATE)
)

# Two compact structural examples. They set the expected shape only — the model
# must never copy their fictional content, which is called out in the prompt.
API_DOCS_EXAMPLES = """\
Structural example 1 (shape only, content is fictional — do NOT copy it):
## Payments API

### Overview
Charge endpoint processes card payments asynchronously; all writes persist to
Postgres [ref:payments:service:charge].

### Authentication
Every request requires `Authorization: Bearer <token>` [ref:auth:middleware].

### Endpoints

#### POST /charges
Creates a charge from a card token [ref:payments:routes:create_charge].
**Body**: `{currency, amount, card_token}`
**Returns**: `201 {id, status: "pending"}`

### Request / Response Schemas
A `Charge` has `id`, `currency`, `amount`, `status` [ref:payments:models:Charge].

### Errors
`402` when the card is declined; `400` for malformed bodies [ref:payments:errors].

### Usage Examples
`POST /charges` with a `card_token` returns the charge id [ref:payments:examples].

Structural example 2 (shape only, content is fictional — do NOT copy it):
## Search API

### Overview
Full-text endpoint over indexed documents [ref:search:index:query].

### Endpoints

#### GET /search?q=&limit=
Returns ranked hits. `limit` defaults to 10, max 100 [ref:search:routes:search].

### Request / Response Schemas
A `Hit` has `id`, `score`, `snippet` [ref:search:models:Hit].

### Errors
`422` for unknown query parameters [ref:search:errors:validation].

### Usage Examples
`/search?q=vault` returns matching docs ordered by score [ref:search:examples].
"""

API_DOCS_PROMPT = """Generate API reference documentation for this codebase,
following the heading contract above.

Use the following code chunks as source material. Cite facts with [ref:NODE_KEY].

{examples}
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
    """
    chunks: list[ChunkDict] = retriever.retrieve(
        repo_id, commit_sha, "API endpoints HTTP routes", top_k=8
    )
    context = retriever.format_context(chunks)

    prompt = API_DOCS_PROMPT.format(examples=API_DOCS_EXAMPLES, context=context)
    if feedback:
        prompt += f"\n\nPrevious feedback to address:\n{feedback}"

    response = get_llm(temperature=0.0).stream([
        {"role": "system", "content": API_DOCS_SYSTEM},
        {"role": "user", "content": prompt},
    ])

    doc = "".join(str(c.content) for c in response if c.content)
    endpoints = extract_endpoints(chunks)
    return doc, endpoints