const TOKEN_KEY = "google_id_token";

export interface UserInfo {
  user_id: number;
  email: string;
  name: string;
  picture: string;
  sessions: unknown[];
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

async function fetchProfile(idToken: string): Promise<UserInfo> {
  const res = await fetch("/api/auth/verify", {
    method: "POST",
    headers: { Authorization: `Bearer ${idToken}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to verify session");
  }
  return res.json();
}

export async function verifyToken(idToken: string): Promise<UserInfo> {
  const userInfo = await fetchProfile(idToken);
  setToken(idToken);
  return userInfo;
}

export async function getCurrentUser(): Promise<UserInfo> {
  const token = getToken();
  if (!token) throw new Error("No stored token");
  return fetchProfile(token);
}