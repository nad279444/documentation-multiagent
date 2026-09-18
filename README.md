# Doc Agent Starter

Minimal FastAPI + LangGraph app for generating documentation from a GitHub repo.

## Start the API

The API is a FastAPI app in `api/main.py`. Use an isolated Python environment, then run Uvicorn from inside `api`:

```bash
cd api
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

If you see `No module named uvicorn`, your shell is using a Python environment where the API dependencies have not been installed yet. Activate the virtual environment or run `python -m pip install -r requirements.txt` in the environment you are using.

The API loads local settings from `api/.env`. At minimum, real generation needs:

```text
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://...
```

Optional services such as Pinecone and Cohere are also read from `api/.env` when configured.

## Start with Docker

From the repo root:

```bash
docker build -t doc-agent-api ./api
docker run --env-file api/.env -p 8000:8080 doc-agent-api
```

The container listens on `$PORT`, defaulting to `8080`.

## Test the API

Health check:

```bash
curl http://localhost:8000/health
```

Submit a documentation run:

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/tiangolo/fastapi","doc_type":"api"}'
```

## Frontend

In a second terminal:

```bash
cd client
npm install
npm run dev
```

The Vite app runs on `http://localhost:3000` and proxies `/api` requests to the FastAPI server on port 8000.

## Required GitHub secrets for deploy

Set these under Settings -> Secrets and variables -> Actions:

- `WIF_PROVIDER` - full resource name of your Workload Identity Provider, for example `projects/123456789/locations/global/workloadIdentityPools/github-pool/providers/github-provider`
- `GCP_SA_EMAIL` - the service account email the workflow impersonates
- `GCP_PROJECT_ID` - your GCP project ID

## Required GCP Secret Manager secret

The deploy step injects `OPENAI_API_KEY` into Cloud Run from Secret Manager rather than as a plain env var. Create it once:

```bash
echo -n "sk-your-key" | gcloud secrets create OPENAI_API_KEY --data-file=-
```

Grant your Cloud Run service account access to read it:

```bash
gcloud secrets add-iam-policy-binding OPENAI_API_KEY \
  --member="serviceAccount:YOUR_RUNTIME_SA@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```
