"""Agent for generating architecture documentation."""

import logging

from retrieval import retriever
from schema import ARCHITECTURE_TEMPLATE
from agents.common import get_llm, BASE_SYSTEM

logger = logging.getLogger(__name__)

ARCHITECTURE_SYSTEM = BASE_SYSTEM + (
    " Focus on system architecture: components, data flow, dependencies, "
    "and design patterns. Include Mermaid diagrams where helpful. "
    "Use these exact headings, in this order, as H2 (##) sections:\n"
    + "\n".join(f"- {heading}" for heading in ARCHITECTURE_TEMPLATE)
)

# Two compact structural examples. They set the expected shape only — the model
# must never copy their fictional content, which is called out in the prompt.
ARCHITECTURE_EXAMPLES = """\
Structural example 1 (shape only, content is fictional — do NOT copy it):
## Invoice Service

### Overview
Service that renders and stores invoices; the renderer is the only writer to
object storage [ref:invoice:service:main].

### Components
`api` (HTTP), `renderer` (PDF), `store` (object storage) [ref:invoice:components].

### Data Flow
1. `api` receives an invoice request
2. `renderer` produces the PDF
3. `store` persists it [ref:invoice:flow:render]

### Dependencies
`api -> renderer -> store` [ref:invoice:graph:deps]

### Design Patterns
Renderer is behind an interface so the PDF engine can be swapped [ref:invoice:patterns].

### Diagrams
```mermaid
flowchart LR
  api --> renderer --> store
```

Structural example 2 (shape only, content is fictional — do NOT copy it):
## Metrics Pipeline

### Overview
Streams events through an aggregator into a time-series store [ref:metric:main].

### Components
`collector`, `aggregator`, `tsdb` [ref:metric:components].

### Data Flow
`collector -> aggregator -> tsdb` [ref:metric:flow].

### Dependencies
Aggregator depends only on the collector interface [ref:metric:deps].

### Design Patterns
Fan-in aggregation keeps per-tenant state isolated [ref:metric:patterns].

### Diagrams
```mermaid
flowchart LR
  collector --> aggregator --> tsdb
```
"""

ARCHITECTURE_PROMPT = """Generate architecture documentation for this codebase,
following the heading contract above.

Use the following code chunks as source material. Cite facts with [ref:NODE_KEY].

{examples}
---
{context}
---"""


def generate_architecture_doc(
    repo_id: int,
    commit_sha: str,
    feedback: str | None = None,
) -> str:
    """Generate architecture documentation using retrieval-augmented generation."""
    chunks = retriever.retrieve(
        repo_id, commit_sha, "architecture overview system design", top_k=8
    )
    context = retriever.format_context(chunks)

    prompt = ARCHITECTURE_PROMPT.format(examples=ARCHITECTURE_EXAMPLES, context=context)
    if feedback:
        prompt += f"\n\nPrevious feedback to address:\n{feedback}"

    response = get_llm(temperature=0.0).stream([
        {"role": "system", "content": ARCHITECTURE_SYSTEM},
        {"role": "user", "content": prompt},
    ])
    return "".join(str(c.content) for c in response if c.content)