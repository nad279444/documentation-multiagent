# Doc Agent Starter

Minimal FastAPI + LangGraph app that calls OpenAI via a single-node graph.
This is the seed for the larger multi-agent documentation pipeline —
just enough to prove the FastAPI → LangGraph → OpenAI → Cloud Run → GitHub
Actions loop works end to end before adding retrieval, the graph agent,
and the evaluator loop.

## Run locally

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
uvicorn main:app --reload
```

Test it:

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Say hello in one sentence."}'
```

## Required GitHub secrets (for the deploy workflow)

Set these under Settings -> Secrets and variables -> Actions:

- `WIF_PROVIDER` — full resource name of your Workload Identity Provider
  (e.g. `projects/123456789/locations/global/workloadIdentityPools/github-pool/providers/github-provider`)
- `GCP_SA_EMAIL` — the service account email the workflow impersonates
- `GCP_PROJECT_ID` — your GCP project ID

## Required GCP Secret Manager secret

The deploy step injects `OPENAI_API_KEY` into Cloud Run from Secret Manager
rather than as a plain env var. Create it once:

```bash
echo -n "sk-your-key" | gcloud secrets create OPENAI_API_KEY --data-file=-
```

And grant your Cloud Run service account access to read it:

```bash
gcloud secrets add-iam-policy-binding OPENAI_API_KEY \
  --member="serviceAccount:YOUR_RUNTIME_SA@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```
