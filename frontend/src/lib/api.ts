// Typed REST client for the uMessage backend.

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN || "";

export type Mode = "real" | "demo";

export interface MessageSourceStatus {
  name: string;
  running: boolean;
}

export interface AppStatus {
  mode: Mode;
  messageSource: MessageSourceStatus;
}

export interface Health {
  status: "ok";
  database: "ok";
}

export type ApiErrorKind = "unreachable" | "unauthorized" | "http";

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (API_TOKEN) headers.set("Authorization", `Bearer ${API_TOKEN}`);

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new ApiError("unreachable", `Can't reach the uMessage backend at ${API_URL}`);
  }
  if (response.status === 401) {
    throw new ApiError("unauthorized", "The backend rejected the API token", 401);
  }
  if (!response.ok) {
    throw new ApiError("http", `${path} failed with HTTP ${response.status}`, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  status: () => request<AppStatus>("/api/status"),
};
