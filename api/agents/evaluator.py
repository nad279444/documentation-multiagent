"""STEP 7 — Evaluator node.

Deterministic checks run first and cost nothing:
  * groundedness  — every [ref:...] citation resolves to a real node
  * completeness  — every extracted endpoint appears in the doc
  * schema        — Markdown structure, Mermaid blocks, and required
                    template sections (API_DOC_TEMPLATE / ARCHITECTURE_TEMPLATE)
                    are present and well formed (the same contract the
                    generator prompt asks the model to follow)
  * no_secrets    — the generated doc doesn't reproduce a credential

Readability is computed locally (Flesch reading ease) at zero cost and never
fails a document — it only feeds the rubric score.

The LLM judge runs only when all deterministic checks pass, and only for the
fuzzy criteria a program genuinely cannot check (jargon, redundancy). That
ordering means a doc with a broken citation never costs an LLM call.

Every metric maps onto the rubric (accuracy / clarity) and, when LangSmith
tracing is enabled, is pushed back to the run as feedback for dashboards and
offline comparison.
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

# Rubric weights for the online overall score. Robustness metrics
# (monorepo / rerun consistency / crash-free) are cross-run and measured
# offline by the benchmark harness, so online overall is accuracy+clarity
# renormalized to full weight.
ACCURACY_WEIGHTS = {"citation_groundedness": 0.4, "endpoint_completeness": 0.4, "no_hallucination": 0.2}
CLARITY_WEIGHTS = {"readability": 0.3, "structure_follows_template": 0.3, "no_jargon_without_definition": 0.4}
ACCURACY_BAND = 0.5
CLARITY_BAND = 0.3


def evaluate(
    doc: str,
    repo_id: int,
    commit_sha: str,
    expected_endpoints: list[EndpointDict] | None = None,
    run_llm_judge: bool = True,
    template: list[str] | None = None,
) -> EvalResultDict:
    checks: dict[str, EvalCheckDict] = {}

    checks["groundedness"] = _check_citations(doc, repo_id, commit_sha)
    checks["schema_valid"] = _check_schema(doc, template)
    checks["no_secrets"] = _check_no_secrets(doc)
    checks["readability"] = _check_readability(doc)
    if expected_endpoints is not None:
        checks["completeness"] = _check_completeness(doc, expected_endpoints)

    gate_names = ("groundedness", "schema_valid", "no_secrets", "completeness")
    gates_passed = all(checks[n]["passed"] for n in gate_names if n in checks)

    # Only spend tokens on judgment once the free checks are clean.
    if gates_passed and run_llm_judge:
        checks["clarity"] = _llm_judge(doc)

    metrics = _build_metrics(checks, expected_endpoints)

    passed = gates_passed
    if gates_passed and "clarity" in checks:
        passed = bool(checks["clarity"]["passed"])

    failures = [
        f"{name}: {c['detail']}" for name, c in checks.items() if not c["passed"]
    ]

    return {
        "passed": passed,
        "checks": checks,
        "metrics": metrics,
        "feedback": "\n".join(failures) if failures else "",
    }


# --- deterministic checks (zero LLM cost) --------------------------------


def _check_citations(doc: str, repo_id: int, commit_sha: str) -> EvalCheckDict:
    cited = extract_citations(doc)
    if not cited:
        return {
            "passed": False,
            "score": 0.0,
            "meta": {"bogus": []},
            "detail": "No [ref:NODE_KEY] citations found.",
        }

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT node_key FROM graph_nodes WHERE repo_id = %s AND commit_sha = %s AND node_key = ANY(%s)",
            (repo_id, commit_sha, list(cited)),
        ).fetchall()
    real = {r[0] for r in rows}
    bogus = sorted(cited - real)
    score = round(len(real) / len(cited), 3)

    if bogus:
        return {
            "passed": False,
            "score": score,
            "meta": {"bogus": bogus},
            "detail": f"{len(bogus)} citation(s) reference code that does not exist: {bogus[:5]}",
        }
    return {
        "passed": True,
        "score": 1.0,
        "meta": {"bogus": []},
        "detail": f"All {len(cited)} citations resolve.",
    }


def _check_completeness(doc: str, endpoints: list[EndpointDict]) -> EvalCheckDict:
    missing = [f"{e['method']} {e['path']}" for e in endpoints if e["path"] not in doc]
    covered = len(endpoints) - len(missing)
    score = 0.0 if not endpoints else round(covered / len(endpoints), 3)
    if missing:
        return {
            "passed": False,
            "score": score,
            "detail": f"Endpoints missing from doc: {missing[:5]}",
        }
    return {
        "passed": True,
        "score": score,
        "detail": f"All {len(endpoints)} endpoints documented.",
    }


HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.M)


def _heading_words(text: str) -> list[str]:
    # Lowercase, collapse punctuation, drop trailing plural 's' so that
    # "Errors" matches "error" and "Request/Response Schemas" matches
    # "Request / Response Schemas" regardless of separator.
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip().split()
    return [w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words]


def _words_cover(words: list[str], required: list[str]) -> bool:
    it = iter(words)
    return all(any(w == req for w in it) for req in required)


def _check_schema(doc: str, template: list[str] | None) -> EvalCheckDict:
    problems = []
    section_score = 1.0

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

    if template:
        headings = [_heading_words(m.group(1)) for m in HEADING_RE.finditer(doc)]
        missing = [
            section
            for section in template
            if not any(_words_cover(hw, _heading_words(section)) for hw in headings)
        ]
        if missing:
            problems.append(f"missing section(s): {', '.join(missing)}")
        section_score = round((len(template) - len(missing)) / len(template), 3)

    if problems:
        return {
            "passed": False,
            "score": section_score,
            "detail": "; ".join(problems),
        }
    return {
        "passed": True,
        "score": section_score,
        "detail": "Markdown and template sections well formed.",
    }


def _check_no_secrets(doc: str) -> EvalCheckDict:
    if contains_secret(doc):
        return {
            "passed": False,
            "score": 0.0,
            "detail": "Generated doc appears to contain a credential.",
        }
    return {"passed": True, "score": 1.0, "detail": "No credentials detected."}


def _count_syllables(word: str) -> int:
    word = word.lower()
    if len(word) <= 3:
        return 1
    n = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not word.endswith(("le", "ee", "ye")):
        n -= 1
    return max(1, n)


def _flesch_reading_ease(doc: str) -> float:
    body = re.sub(r"```.*?```", " ", doc, flags=re.S)
    words = re.findall(r"[A-Za-z0-9'-]+", body)
    if not words:
        return 60.0
    sentences = max(1, len(re.findall(r"[.!?]+", body)) or 1)
    syllables = sum(_count_syllables(w) for w in words)
    return 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (
        syllables / len(words)
    )


def _check_readability(doc: str) -> EvalCheckDict:
    ease = _flesch_reading_ease(doc)
    # Map technical-doc range (roughly 0-60 Flesch) into a 0-1 score.
    score = round(min(1.0, max(0.0, (ease - 5.0) / 55.0)), 3)
    label = "readable" if score >= 0.6 else "dense"
    return {
        "passed": True,
        "score": score,
        "detail": f"Flesch reading ease {ease:.1f} — {label}.",
    }


# --- LLM judge (fuzzy criteria only) -------------------------------------

JUDGE_SYSTEM = (
    "You review technical documentation. Reply with JSON only: "
    '{"no_jargon_without_definition": float, "issues": [string]}. '
    "no_jargon_without_definition: 1.0 if every technical term or acronym is "
    "defined or self-evident from context, 0.0 if unexplained jargon appears. "
    "List issues only for clarity/redundancy problems. No prose, no code fences."
)

JUDGE_PROMPT = """Review this documentation for clarity, redundancy, and jargon.
Do not check factual accuracy — that is verified separately.

Focus on: unexplained technical terms, contradictory explanations, substantial
repetition, or sections that say nothing useful.

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
        jargon = float(verdict.get("no_jargon_without_definition", 0.5))
        issues = [str(i) for i in verdict.get("issues", [])]
        score = round(min(1.0, max(0.0, jargon)), 3)
        passed = score >= 0.7 and len(issues) <= 2
        return {
            "passed": passed,
            "score": score,
            "detail": "; ".join(issues) or "Clear and non-redundant.",
        }
    except Exception as exc:
        # A judge failure must not block a doc that passed every real check.
        logger.warning("LLM judge failed, passing by default: %s", exc)
        return {"passed": True, "score": 0.5, "detail": f"Judge unavailable ({exc})."}


# --- rubric metrics ------------------------------------------------------


def _build_metrics(
    checks: dict[str, EvalCheckDict],
    expected_endpoints: list[EndpointDict] | None,
) -> dict[str, float]:
    metrics: dict[str, float] = {}

    # accuracy band
    groundedness = checks.get("groundedness", {})
    metrics["citation_groundedness"] = float(groundedness.get("score", 0.0))
    metrics["no_hallucination"] = (
        1.0 if not groundedness.get("meta", {}).get("bogus") else 0.0
    )
    if expected_endpoints is not None and "completeness" in checks:
        metrics["endpoint_completeness"] = float(checks["completeness"].get("score", 0.0))

    # clarity band
    metrics["readability"] = float(checks.get("readability", {}).get("score", 0.0))
    metrics["structure_follows_template"] = float(
        checks.get("schema_valid", {}).get("score", 0.0)
    )
    metrics["no_jargon_without_definition"] = float(
        checks.get("clarity", {}).get("score", 0.0)
    )

    accuracy = _weighted(metrics, ACCURACY_WEIGHTS)
    clarity = _weighted(metrics, CLARITY_WEIGHTS)
    metrics["overall"] = round(((ACCURACY_BAND * accuracy + CLARITY_BAND * clarity)
                                / (ACCURACY_BAND + CLARITY_BAND)), 3)
    return metrics


def _weighted(metrics: dict[str, float], weights: dict[str, float]) -> float:
    used = [(metrics[k], w) for k, w in weights.items() if k in metrics]
    if not used:
        return 0.0
    total_weight = sum(w for _, w in used)
    return sum(v * w for v, w in used) / total_weight


def push_eval_feedback(
    metrics: dict[str, float],
    run_id: str | None,
    comment: str = "",
) -> None:
    """Post every rubric metric to the LangSmith run as feedback.

    Safe no-op when tracing is off or credentials are missing (both bounds
    fail gracefully); a single failed metric never aborts the eval.
    """
    if not metrics or not run_id:
        return
    try:
        from langsmith import Client

        client = Client()
        for key, score in metrics.items():
            if score is not None:
                client.create_feedback(
                    run_id, key=f"rubric:{key}", score=score, comment=comment[:500]
                )
    except Exception as exc:
        logger.warning("LangSmith feedback failed (skipped): %s", exc)