import { getToken } from './auth';

const BASE = '/api';

function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

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

export interface RecentRun {
  run_id: number;
  doc_type: "api" | "architecture";
  status: string;
  output: string | null;
  repo_url: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  edited: boolean;
}

export async function getRecentRuns(): Promise<RecentRun[]> {
  const res = await fetch(`${BASE}/runs`, { headers: authHeaders() });
  if (!res.ok) throw new Error("Failed to load recent runs");
  const data = (await res.json()) as { runs: RecentRun[] };
  return data.runs;
}

export async function loadChatHistory(runId: number): Promise<ChatMessage[]> {
  const res = await fetch(`${BASE}/runs/${runId}/chat/history`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to load chat history");
  const data = (await res.json()) as { messages: ChatMessage[] };
  return data.messages;
}

export async function clearChat(runId: number): Promise<void> {
  const res = await fetch(`${BASE}/runs/${runId}/chat`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to clear chat history");
}

export interface StreamHandlers {
  onStage?: (stage: string) => void;
  onToken?: (text: string) => void;
  onDone?: (status: string) => void;
  onError?: (message: string) => void;
}

interface StreamEvent {
  type: string;
  stage?: string;
  text?: string;
  status?: string;
  error?: string;
}

/**
 * Opens the SSE stream for a run and dispatches stage/token/done events.
 * Returns a cancel function; call it to abort the connection.
 */
export function streamRun(
  runId: number,
  handlers: StreamHandlers,
): () => void {
  const controller = new AbortController();

  const handleEvent = (evt: StreamEvent) => {
    switch (evt.type) {
      case "stage":
        handlers.onStage?.(evt.stage ?? "");
        break;
      case "token":
        handlers.onToken?.(evt.text ?? "");
        break;
      case "done":
        handlers.onDone?.(evt.status ?? "");
        break;
      case "error":
        handlers.onError?.(evt.error ?? "Stream error");
        break;
    }
  };

  fetch(`${BASE}/runs/${runId}/stream`, {
    headers: { ...authHeaders(), Accept: "text/event-stream" },
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) throw new Error("Stream unavailable");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          for (const line of raw.split("\n")) {
            if (line.startsWith("data: ")) {
              try {
                handleEvent(JSON.parse(line.slice(6)) as StreamEvent);
              } catch {
                /* ignore malformed frames */
              }
            }
          }
        }
      }
    })
    .catch((err: unknown) => {
      if (!controller.signal.aborted) {
        handlers.onError?.(err instanceof Error ? err.message : "Stream error");
      }
    });

  return () => controller.abort();
}

export async function submitGeneration(req: GenerateRequest): Promise<GenerateResponse> {
  const res = await fetch(`${BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to submit');
  }
  return res.json();
}

export async function getRun(runId: number): Promise<RunStatus> {
  const res = await fetch(`${BASE}/runs/${runId}`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Run not found');
  return res.json();
}

export async function getDocument(runId: number): Promise<string> {
  const res = await fetch(`${BASE}/runs/${runId}/document`, {
    headers: authHeaders(),
  });
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
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Chat failed');
  }
  return res.json();
}
