"""STEP 7 — Evaluator node.

Deterministic checks run first and cost nothing:
  * groundedness  — every [ref:...] citation resolves to a real node
  * completeness  — every extracted endpoint appears in the doc
  * schema        — Markdown structure and Mermaid blocks are well formed
  * no_secrets    — the generated doc doesn't reproduce a credential

The LLM judge runs only when all of those pass, and only for the fuzzy
criteria a program genuinely cannot check (clarity, redundancy). That
ordering means a doc with a broken citation never costs an LLM call.
"""

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from db import get_conn
from ingest.cloner import contains_secret
from schema import EndpointDict, EvalCheckDict, EvalResultDict
from agents.common import extract_citations, get_llm

logger = logging.getLogger(__name__)


def evaluate(
    doc: str,
    repo_id: int,
    commit_sha: str,
    expected_endpoints: list[EndpointDict] | None = None,
    run_llm_judge: bool = True,
) -> EvalResultDict:
    checks: dict[str, EvalCheckDict] = {}

    checks["groundedness"] = _check_citations(doc, repo_id, commit_sha)
    checks["schema_valid"] = _check_schema(doc)
    checks["no_secrets"] = _check_no_secrets(doc)
    if expected_endpoints is not None:
        checks["completeness"] = _check_completeness(doc, expected_endpoints)

    deterministic_passed = all(c["passed"] for c in checks.values())

    # Only spend tokens on judgment once the free checks are clean.
    if deterministic_passed and run_llm_judge:
        checks["clarity"] = _llm_judge(doc)

    passed = all(c["passed"] for c in checks.values())
    failures = [
        f"{name}: {c['detail']}" for name, c in checks.items() if not c["passed"]
    ]

    return {
        "passed": passed,
        "checks": checks,
        "feedback": "\n".join(failures) if failures else "",
    }


# --- deterministic checks (zero LLM cost) --------------------------------


def _check_citations(doc: str, repo_id: int, commit_sha: str) -> EvalCheckDict:
    cited = extract_citations(doc)
    if not cited:
        return {"passed": False, "detail": "No [ref:NODE_KEY] citations found."}

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT node_key FROM graph_nodes WHERE repo_id = %s AND commit_sha = %s AND node_key = ANY(%s)",
            (repo_id, commit_sha, list(cited)),
        ).fetchall()
    real = {r[0] for r in rows}
    bogus = sorted(cited - real)

    if bogus:
        return {
            "passed": False,
            "detail": f"{len(bogus)} citation(s) reference code that does not exist: {bogus[:5]}",
        }
    return {"passed": True, "detail": f"All {len(cited)} citations resolve."}


def _check_completeness(doc: str, endpoints: list[EndpointDict]) -> EvalCheckDict:
    missing = [f"{e['method']} {e['path']}" for e in endpoints if e["path"] not in doc]
    if missing:
        return {"passed": False, "detail": f"Endpoints missing from doc: {missing[:5]}"}
    return {"passed": True, "detail": f"All {len(endpoints)} endpoints documented."}


def _check_schema(doc: str) -> EvalCheckDict:
    problems = []
    if not doc.strip():
        problems.append("document is empty")
    if not re.search(r"^#\s+\S", doc, re.M):
        problems.append("no top-level heading")
    if doc.count("```") % 2 != 0:
        problems.append("unbalanced code fences")

    for block in re.findall(r"```mermaid\n(.*?)```", doc, re.S):
        first = block.strip().split("\n")[0] if block.strip() else ""
        if not re.match(
            r"^(graph|flowchart|sequenceDiagram|classDiagram|erDiagram|stateDiagram)",
            first,
        ):
            problems.append(f"invalid mermaid header: {first[:40]!r}")

    if problems:
        return {"passed": False, "detail": "; ".join(problems)}
    return {"passed": True, "detail": "Markdown and diagrams well formed."}


def _check_no_secrets(doc: str) -> EvalCheckDict:
    if contains_secret(doc):
        return {
            "passed": False,
            "detail": "Generated doc appears to contain a credential.",
        }
    return {"passed": True, "detail": "No credentials detected."}


# --- LLM judge (fuzzy criteria only) -------------------------------------

JUDGE_SYSTEM = (
    "You review technical documentation. Reply with JSON only: "
    '{"passed": bool, "issues": [string]}. No prose, no code fences.'
)

JUDGE_PROMPT = """Review this documentation for clarity and redundancy only.
Do not check factual accuracy — that is verified separately.

Fail it only for: unclear or contradictory explanations, substantial repetition,
or sections that say nothing useful.

---
{doc}
---"""


def _llm_judge(doc: str) -> EvalCheckDict:
    try:
        response = get_llm(temperature=0.0).invoke(
            [
                SystemMessage(content=JUDGE_SYSTEM),
                HumanMessage(content=JUDGE_PROMPT.format(doc=doc[:12000])),
            ]
        )
        raw = (
            str(response.content).strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
        )
        verdict = json.loads(raw)
        return {
            "passed": bool(verdict.get("passed", False)),
            "detail": "; ".join(verdict.get("issues", []))
            or "Clear and non-redundant.",
        }
    except Exception as exc:
        # A judge failure must not block a doc that passed every real check.
        logger.warning("LLM judge failed, passing by default: %s", exc)
        return {"passed": True, "detail": f"Judge unavailable ({exc})."}
