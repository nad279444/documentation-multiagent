const BASE = '/api';

export interface GenerateRequest {
  repo_url: string;
  doc_type: 'api' | 'architecture';
  branch?: string | null;
}

export interface GenerateResponse {
  run_id: number;
  thread_id: string;
  status: string;
  cached: boolean;
}

export interface RunStatus {
  run_id: number;
  status: string;
  doc_type: string;
  commit_sha: string;
  output: string | null;
  eval_report: Record<string, unknown> | null;
  repo_url: string;
}

export async function submitGeneration(req: GenerateRequest): Promise<GenerateResponse> {
  const res = await fetch(`${BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to submit');
  }
  return res.json();
}

export async function getRun(runId: number): Promise<RunStatus> {
  const res = await fetch(`${BASE}/runs/${runId}`);
  if (!res.ok) throw new Error('Run not found');
  return res.json();
}

export async function getDocument(runId: number): Promise<string> {
  const res = await fetch(`${BASE}/runs/${runId}/document`);
  if (!res.ok) throw new Error('Document not available');
  return res.text();
}

export interface ChatResponse {
  reply: string;
  document: string;
  edited: boolean;
}

export async function sendChat(runId: number, message: string): Promise<ChatResponse> {
  const res = await fetch(`${BASE}/runs/${runId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Chat failed');
  }
  return res.json();
}
