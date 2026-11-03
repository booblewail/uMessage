// Typed REST client for the uMessage backend.

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
export const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN || "";

export type Mode = "real" | "demo";

export interface MessageSourceStatus {
  name: string;
  running: boolean;
}

export type FirstImportState = "waiting" | "running" | "completed" | "failed";

export interface FirstImportStatus {
  state: FirstImportState;
  /** Known once the Chats have been listed. */
  chatsTotal: number | null;
  chatsImported: number;
  error: string | null;
}

export interface AppStatus {
  mode: Mode;
  messageSource: MessageSourceStatus;
  firstImport: FirstImportStatus;
}

export const PLATFORMS = ["imessage", "instagram", "messenger", "whatsapp", "discord"] as const;
export type Platform = (typeof PLATFORMS)[number];

export interface LastMessage {
  senderName: string;
  text: string;
  sentAt: string;
  outbound: boolean;
}

export interface Chat {
  id: number;
  platform: Platform;
  kind: "one_to_one" | "group";
  title: string;
  /** When the last Message was sent (the Chat's last activity if it has none). */
  lastMessageAt: string;
  lastMessage: LastMessage | null;
}

export interface Message {
  id: number;
  chatId: number;
  senderName: string;
  sentAt: string;
  text: string;
  /** True for an Outbound Message: one the user sent, from any client. */
  outbound: boolean;
}

/**
 * The newest `limit` Messages older than `before`, oldest first (display order).
 * Pass `olderCursor` as `before` to get the page before this one.
 */
export interface MessagePage {
  messages: Message[];
  hasOlder: boolean;
  olderCursor: number | null;
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
    const detail = await errorDetail(response);
    throw new ApiError("http", detail ?? `${path} failed with HTTP ${response.status}`, response.status);
  }
  return (await response.json()) as T;
}

/** The backend's own explanation of an error (FastAPI's `detail`), if it gave a readable one. */
async function errorDetail(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && typeof body.detail[0]?.msg === "string") return body.detail[0].msg;
  } catch {
    // not JSON
  }
  return null;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError("http", String(error));
}

export const api = {
  health: () => request<Health>("/api/health"),
  status: () => request<AppStatus>("/api/status"),
  /** Chats newest first; `platform` narrows the list to one Platform. */
  chats: (platform?: Platform) =>
    request<{ chats: Chat[] }>(`/api/chats${query({ platform })}`),
  messages: (chatId: number, options: { before?: number; limit?: number } = {}) =>
    request<MessagePage>(`/api/chats/${chatId}/messages${query(options)}`),
  /** Send a Message through Beeper Desktop; resolves to the stored Outbound Message. */
  sendMessage: (chatId: number, text: string) =>
    request<Message>(`/api/chats/${chatId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
};
