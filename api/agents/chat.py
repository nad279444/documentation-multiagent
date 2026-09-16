"""Chat agent for document revision with tool calling.

Uses LangChain tool calling to edit the document based on user feedback.
Input guardrails ensure the conversation stays on-topic (document-related).
"""

import logging
import re
from typing import Annotated, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agents.common import get_llm

logger = logging.getLogger(__name__)

CHAT_SYSTEM = (
    "You are a documentation editor. The user will ask you to revise a generated document. "
    "You have tools to edit sections, rewrite content, and answer questions about the document. "
    "ALWAYS use the edit_document tool when making changes — never just describe what to change. "
    "Keep the document's structure and formatting intact. "
    "If the user asks something unrelated to this document, politely refuse and remind them "
    "you can only help with this specific document. "
    "Output the full updated document after every edit."
)

GUARDRAIL_SYSTEM = (
    "You are a content classifier. The user is chatting about a software documentation document that was just generated. "
    "Determine if the user message is related to understanding, editing, or asking questions about that document or the software it describes. "
    "Reply with ONLY 'on_topic' or 'off_topic'.\n\n"
    "ON-TOPIC (reply 'on_topic'):\n"
    "- Questions about the document content (e.g. 'what does this endpoint do', 'what technologies are used')\n"
    "- Questions about the software (e.g. 'what message queue does this use', 'how does authentication work')\n"
    "- Edit requests (e.g. 'rewrite section 2', 'make it clearer', 'fix the formatting')\n"
    "- Follow-up questions about previous answers\n\n"
    "OFF-TOPIC (reply 'off_topic'):\n"
    "- Unrelated topics (e.g. 'what's the weather', 'write me a poem', 'help with homework')\n"
    "- Requests to generate new documents for other repos\n"
    "- Meta questions about the chatbot itself (e.g. 'what model are you')"
)


class EditDocumentInput(BaseModel):
    instruction: str = Field(description="What to change (e.g. 'Rewrite the introduction to be clearer')")
    section: str | None = Field(
        default=None,
        description="Optional: exact heading or section to target. If null, edits the full document.",
    )


class ChatResponse(BaseModel):
    reply: str
    document: str
    edited: bool


def _check_on_topic(user_message: str, document: str) -> bool:
    """Input guardrail: verify the message is document-related."""
    llm = get_llm(temperature=0.0)
    # Include a meaningful snippet of the document so the classifier has context
    doc_snippet = document[:3000] if len(document) > 3000 else document
    guardrail_prompt = (
        f"DOCUMENT CONTEXT:\n{doc_snippet}\n\n"
        f"USER MESSAGE: {user_message}\n\n"
        "Is this message related to the document above or the software it describes? Reply 'on_topic' or 'off_topic'."
    )
    result = llm.invoke([SystemMessage(content=GUARDRAIL_SYSTEM), HumanMessage(content=guardrail_prompt)])
    answer = result.content.strip().lower()
    logger.info("Guardrail check: message='%s' -> %s", user_message[:80], answer)
    return "on_topic" in answer


def _apply_edit(document: str, instruction: str, section: str | None) -> str:
    """Use the LLM to apply an edit to the document."""
    llm = get_llm(temperature=0.2)

    if section:
        prompt = (
            f"Here is the current document:\n\n{document}\n\n"
            f'The user wants to edit the section titled "{section}". '
            f"Instruction: {instruction}\n\n"
            "Return the FULL updated document with the change applied. "
            "Keep all other sections exactly the same."
        )
    else:
        prompt = (
            f"Here is the current document:\n\n{document}\n\n"
            f"Instruction: {instruction}\n\n"
            "Return the FULL updated document with the change applied. "
            "Keep all other sections exactly the same."
        )

    result = llm.invoke([SystemMessage(content=CHAT_SYSTEM), HumanMessage(content=prompt)])
    edited = result.content.strip()
    # Strip markdown code fences if the LLM wrapped the output
    if edited.startswith("```"):
        lines = edited.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        edited = "\n".join(lines)
    return edited


def _answer_question(question: str, document: str) -> str:
    """Answer a question about the document without modifying it."""
    llm = get_llm(temperature=0.0)
    prompt = (
        f"Here is the document:\n\n{document}\n\n"
        f"Answer the user's question based ONLY on the content of this document.\n"
        f"Question: {question}"
    )
    result = llm.invoke([SystemMessage(content=CHAT_SYSTEM), HumanMessage(content=prompt)])
    return result.content.strip()


def chat(user_message: str, document: str, history: list[dict[str, str]] | None = None) -> ChatResponse:
    """Main entry point for the chat agent.

    1. Guardrail check — reject off-topic messages.
    2. Route to edit or answer depending on intent.
    3. Return updated document + reply.
    """
    # --- Input guardrail ---
    if not _check_on_topic(user_message, document):
        return ChatResponse(
            reply="I can only help with editing or answering questions about the generated document. "
            "Please ask something related to the document content.",
            document=document,
            edited=False,
        )

    # --- Intent detection ---
    lower_msg = user_message.lower()
    edit_keywords = [
        "edit", "rewrite", "change", "update", "fix", "revise", "modify",
        "make it", "rephrase", "simplify", "expand", "shorten", "add", "remove",
        "replace", "clarify", "improve", "reorganize", "restructure",
    ]
    wants_edit = any(kw in lower_msg for kw in edit_keywords)

    # Try to extract a section target
    section_match = re.search(
        r'(?:section|heading|chapter|part)\s+["\']?(.+?)["\']?\s*$'
        r'|^["\'](.+?)["\']$'
        r'^(?:in|about|for)\s+["\'](.+?)["\']',
        user_message,
        re.I,
    )
    target_section = None
    if section_match:
        target_section = next(g for g in section_match.groups() if g)

    if wants_edit:
        edited_doc = _apply_edit(document, user_message, target_section)
        return ChatResponse(
            reply="Done. The document has been updated.",
            document=edited_doc,
            edited=True,
        )

    # Default: answer question
    answer = _answer_question(user_message, document)
    return ChatResponse(reply=answer, document=document, edited=False)
