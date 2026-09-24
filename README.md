# DocAgent

DocAgent is a multi-agent documentation generator. Paste a public GitHub
repository URL, and a LangGraph pipeline clones the repo, parses it into a
code graph, indexes it for retrieval, generates API or architecture
documentation with an LLM, and automatically evaluates the result — revising
it until it passes or escalating it for human review.

## Recent improvements

- **Live streaming progress** — generation streams stage updates and
  generated tokens over SSE (`GET /runs/{id}/stream`); the UI reveals the
  draft at a readable typing pace instead of a long wait then a sudden dump.
  Chat replies type out too. Note: event buffers are in-process, so a
  single instance is currently assumed per run.
- **Observability & rubric scoring** — LangGraph runs are traced to LangSmith,
  and the evaluator computes a numeric rubric (citation groundedness, endpoint
  completeness, readability, structure, jargon) with an accuracy × clarity
  "overall" score pushed back to the run as LangSmith feedback. The generators
  and evaluator share one heading contract (`api/schema.py`) enforced by the
  schema check.
- **Conversations that persist** — chat history is stored per repo workspace
  (`chat_messages`, keyed by user + repo) rather than per run, so the same
  thread carries across the API Reference / Architecture tabs, survives
  logout/login, and "Clear" deletes the whole thread (`GET|DELETE
  /runs/{id}/chat/history`). The chat endpoint is owner-validated.
- **Session restore** — `GET /runs` returns the latest completed document per
  type, so returning users land back on their last document and conversation.
- **Reliable PDF export** — export renders via `html-to-image` (browser
  engine, so Tailwind v4 `oklch` colors survive), captures the full scroll
  height, and slices across A4 pages with a `window.print()` fallback.
- **Responsive UI** — the app is laid out for phones and tablets across the
  login, submit, processing, and document-view phases (scrollable stacked view,
  bounded chat height, wrapping toolbars, safe-area viewport).
- **Eval robustness** — eval reports are JSON-serialized defensively so a
  non-serializable check payload can never fail a run.

## Repo layout

```
api/                  FastAPI backend
  main.py             HTTP entrypoint (auth, generate, runs, chat)
  auth.py             Google OAuth ID-token verification
  config.py           All settings from API/.env / Cloud Run secrets
  db.py               Postgres (Neon): app data + LangGraph checkpoints
  agents/             LLM agents: api_docs, architecture, evaluator, chat
  graphs/             doc_graph.py — the LangGraph state machine
  ingest/             cloner (guardrails), parser, graph_store (call graph)
  retrieval/          embeddings (OpenAI -> Pinecone), retriever (rerank)
client/               React 19 + Vite + Tailwind 4 frontend
  src/components/     GoogleSignIn, SubmitForm, DocumentViewer, ChatPanel
  src/lib/            api.ts (fetch helpers), auth.ts (token handling)
.github/workflows/    Cloud Run deploy via Workload Identity Federation
```

## How it works

The `POST /generate` endpoint enqueues a run and returns a `run_id`
immediately; generation runs in the background through a LangGraph state
machine (`api/graphs/doc_graph.py`):

```
ingest -> generate -> evaluate -> [publish | generate (revise) | human_review]
```

1. **Ingest** — shallow-clones a public GitHub repo with guardrails applied at
   the door: only `github.com` URLs, size/file caps, and files matching
   credential patterns are excluded from indexing entirely. Changed files are
   re-indexed incrementally rather than re-cloning everything.
2. **Parse & graph** — code is parsed into function/class/module nodes and a
   deterministic call graph persisted in Postgres (`graph_nodes` /
   `graph_edges`).
3. **Embed** — chunks are embedded with OpenAI and upserted to Pinecone for
   vector search.
4. **Retrieve** — graph-augmented retrieval: vector search finds semantic
   seeds, the call graph expands to their callers/callees, and a Cohere
   reranker narrows the pool. Falls back to vector ordering without a Cohere
   key.
5. **Generate** — an LLM writes API reference or architecture docs (Mermaid
   diagrams included) grounded in the retrieved chunks, citing every claim as
   `[ref:NODE_KEY]`.
6. **Evaluate** — deterministic checks run first (citations resolve, all
   endpoints covered, schema well-formed, no secrets leaked); an LLM judge
   only runs once those pass, and only for fuzzy criteria (clarity,
   redundancy). Every metric maps to an accuracy/clarity rubric and the
   overall score is pushed to the LangSmith run as feedback when tracing is
   enabled. Failed docs are regenerated with feedback, up to
   `MAX_EVAL_RETRIES`; beyond that they're kept and flagged
   `needs_human_review`, never discarded.
7. **Chat** — for an existing run you can ask questions or request edits. A
   tool-calling agent edits the document (updates persisted) with guardrails
   keeping the conversation on-topic, an in-memory cache dedupes repeated
   questions, and every message is persisted to the repo's workspace thread so
   the same conversation is shared by both document tabs and survives
   logout/login.

## Prerequisites

- Python 3.11+ and `git`
- Node.js 18+ (for the frontend)
- Accounts/keys: OpenAI, Neon Postgres, Pinecone, Google OAuth; optionally
  Cohere for reranking

## Start the API

The API is a FastAPI app in `api/main.py`. Use an isolated Python environment,
then run Uvicorn from inside `api`:

```bash
cd api
python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS/Linux:           source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> If you see `No module named uvicorn`, your shell is using a Python
> environment where the API dependencies are not installed. Activate the
> virtual environment (or call its interpreter directly, e.g.
> `./.venv/Scripts/python.exe -m uvicorn ...` on Windows) and reinstall.

The API loads local settings from `api/.env`:

```dotenv
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://...        # Neon Postgres (app data + checkpoints)
PINECONE_API_KEY=...                 # vector store
PINECONE_INDEX=doc-agent
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
COHERE_API_KEY=...                   # optional reranker (skipped if unset)
LANGSMITH_API_KEY=lsv2_...           # optional tracing + eval feedback
LANGSMITH_PROJECT=doc-agent
```

Optional tunables: `LLM_MODEL` (default `gpt-4o-mini`), `EMBEDDING_MODEL`
(default `text-embedding-3-small`), `MAX_REPO_MB` (200), `MAX_FILES` (2000),
`MAX_EVAL_RETRIES` (2), `RETRIEVAL_TOP_K` (8).

## Start with Docker

From the repo root:

```bash
docker build -t doc-agent-api ./api
docker run --env-file api/.env -p 8000:8080 doc-agent-api
```

The container listens on `$PORT`, defaulting to `8080`.

## Frontend

In a second terminal:

```bash
cd client
npm install
cp .env.example .env 2>/dev/null # VITE_API_URL + VITE_GOOGLE_CLIENT_ID
npm run dev
```

The Vite app runs on `http://localhost:3000` and proxies `/api` requests to
the FastAPI server on port 8000. Signing in requires the OAuth client's
**Authorized JavaScript origin** to include `http://localhost:3000`.

## API endpoints

| Method | Path                       | Description                                  |
| ------ | -------------------------- | -------------------------------------------- |
| GET    | `/health`                  | Health check                                 |
| POST   | `/auth/verify`             | Verify Google ID token, return user + sessions |
| POST   | `/generate`                | Start a documentation run (`repo_url`, `doc_type`, `branch?`) |
| GET    | `/runs`                    | Latest completed run per doc type (session restore) |
| GET    | `/runs/{run_id}`           | Run status + output (owner-only)             |
| GET    | `/runs/{run_id}/document`  | Plain-text markdown of the generated doc     |
| GET    | `/runs/{run_id}/stream`    | SSE live progress: stages, tokens, done (owner-only) |
| POST   | `/runs/{run_id}/chat`      | Ask about / request edits to a document      |
| GET    | `/runs/{run_id}/chat/history` | Persisted conversation for the repo workspace |
| DELETE | `/runs/{run_id}/chat`      | Clear the entire conversation thread         |
| GET    | `/sessions`                | List the user's recent sessions              |

Most endpoints require `Authorization: Bearer <google_id_token>`.

## Test the API

```bash
curl http://localhost:8000/health
```

## Deploy to Cloud Run

Pushing to `main` triggers `.github/workflows/deploy.yml`, which builds the
API from source and deploys to Cloud Run using Workload Identity Federation.

Required repo secrets (Settings → Secrets and variables → Actions):

- `WIF_PROVIDER` — Workload Identity Provider resource name, e.g.
  `projects/123456789/locations/global/workloadIdentityPools/github-pool/providers/github-provider`
- `GCP_SA_EMAIL` — the service account the workflow impersonates
- `GCP_PROJECT_ID` — your GCP project ID

Secrets are injected at runtime from Secret Manager rather than plain env
vars. Create each once (`` `echo -n "value" | gcloud secrets create NAME --data-file=-` ``)
and grant the runtime service account `roles/secretmanager.secretAccessor`:

- `OPENAI_API_KEY`, `DATABASE_URL`, `PINECONE_API_KEY`, `COHERE_API_KEY`,
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`