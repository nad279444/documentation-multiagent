import os
from typing import TypedDict

from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, SecretStr

# --- LangChain chat model -----------------------------------------------
api_key = os.environ.get("OPENAI_API_KEY")
llm = ChatOpenAI(model="gpt-4o-mini", api_key=SecretStr(api_key)) if api_key else None
# Swapping providers later is a one-line change, e.g.:
# from langchain_anthropic import ChatAnthropic
# llm = ChatAnthropic(model="claude-...", api_key=...)


# --- LangGraph state -----------------------------------------------------
class GraphState(TypedDict):
    input: str
    output: str


def call_llm_node(state: GraphState) -> GraphState:
    if llm is None:
        raise RuntimeError("OPENAI_API_KEY is not set")

    response = llm.invoke(
        [
            SystemMessage(content="You are a concise, helpful assistant."),
            HumanMessage(content=state["input"]),
        ]
    )
    return {"input": state["input"], "output": str(response.content)}


graph_builder = StateGraph(GraphState)
graph_builder.add_node("call_llm", call_llm_node)
graph_builder.set_entry_point("call_llm")
graph_builder.add_edge("call_llm", END)
graph = graph_builder.compile()

# --- FastAPI app -----------------------------------------------------
app = FastAPI(title="Doc Agent Starter")


class GenerateRequest(BaseModel):
    prompt: str


class GenerateResponse(BaseModel):
    result: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    try:
        result = graph.invoke({"input": req.prompt, "output": ""})
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return GenerateResponse(result=result["output"])
