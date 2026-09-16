"""Central configuration, loaded from environment variables.

Every external credential is read here so the rest of the code never
touches os.environ directly. On Cloud Run these come from Secret Manager
via --set-secrets; locally they come from a .env file.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # --- LLM / embeddings -------------------------------------------------
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    # Budget-tier model: keeps the $5 development budget covering dozens of runs.
    llm_model: str = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    embedding_model: str = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    embedding_dimensions: int = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))

    # --- Postgres (Neon) --------------------------------------------------
    # Used for BOTH application data and LangGraph checkpoints.
    database_url: str = os.environ.get("DATABASE_URL", "")

    # --- Pinecone ---------------------------------------------------------
    pinecone_api_key: str = os.environ.get("PINECONE_API_KEY", "")
    pinecone_index: str = os.environ.get("PINECONE_INDEX", "doc-agent")
    pinecone_cloud: str = os.environ.get("PINECONE_CLOUD", "aws")
    pinecone_region: str = os.environ.get("PINECONE_REGION", "us-east-1")

    # --- Ingestion limits (input guardrails) ------------------------------
    max_repo_mb: int = int(os.environ.get("MAX_REPO_MB", "200"))
    max_files: int = int(os.environ.get("MAX_FILES", "2000"))
    max_file_bytes: int = int(os.environ.get("MAX_FILE_BYTES", "400000"))
    clone_dir: str = os.environ.get("CLONE_DIR", "/tmp/repos")

    # --- Generation / evaluator -------------------------------------------
    max_eval_retries: int = int(os.environ.get("MAX_EVAL_RETRIES", "2"))
    retrieval_top_k: int = int(os.environ.get("RETRIEVAL_TOP_K", "8"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
