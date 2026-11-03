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

export interface PlanDetectionStatus {
  /** Whether new Messages are checked for plans. */
  enabled: boolean;
  /** Why plan detection is off (null when it is on). */
  reason: string | null;
  /** Why the last Plan Model call failed; null once one succeeds. */
  lastError: string | null;
}

export interface CalendarStatus {
  /** Whether Calendar Entries can be created right now. */
  connected: boolean;
  /** Why not, and what to do (null when connected). */
  reason: string | null;
}

export interface AppStatus {
  mode: Mode;
  messageSource: MessageSourceStatus;
  firstImport: FirstImportStatus;
  planDetection: PlanDetectionStatus;
  calendar: CalendarStatus;
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
  /** An Excluded Chat: never checked for plans. */
  excluded: boolean;
}

/** `confirming` only while its Calendar Entry is being created. */
export type DetectedEventStatus = "pending_review" | "confirming" | "confirmed" | "dismissed";

/** The Chat a Detected Event was found in. */
export interface EventChat {
  id: number;
  title: string;
  platform: Platform;
}

/** A Detected Event's Anchor Message: the latest Message that shaped it. */
export interface AnchorMessage {
  id: number;
  senderName: string;
  text: string;
  sentAt: string;
  outbound: boolean;
}

/** An upcoming Calendar Entry, by the Confirmed Detected Event it was made from. */
export interface CalendarEntryRef {
  id: number;
  title: string;
  start: string;
  allDay: boolean;
}

/** A plan found in a Chat, shown beneath its Anchor Message. */
export interface DetectedEvent {
  id: number;
  chatId: number;
  chat: EventChat;
  anchorMessageId: number;
  anchorMessage: AnchorMessage;
  title: string;
  /** UTC; an all-day plan starts at local midnight of its date. */
  start: string;
  /** UTC; null when the Chat didn't say. All-day: midnight of its last day. */
  end: string | null;
  allDay: boolean;
  location: string | null;
  confidence: number;
  status: DetectedEventStatus;
  /** Its Calendar Entry, once Confirmed. */
  calendarEntryId: string | null;
  /** Upcoming Calendar Entries its Chat already has (other Confirmed ones), soonest first. */
  existingCalendarEntries: CalendarEntryRef[];
  createdAt: string;
  updatedAt: string;
}

/**
 * Edits made before confirming. Timed: `start`/`end` are ISO 8601 with offset. All-day: they
 * are YYYY-MM-DD, the first and last day (inclusive). A null `end`: no end (a timed plan
 * gets the default length).
 */
export interface ConfirmEdits {
  title: string;
  allDay: boolean;
  start: string;
  end: string | null;
  location: string | null;
}

export interface Message {
  id: number;
  chatId: number;
  senderName: string;
  sentAt: string;
  text: string;
  /** True for an Outbound Message: one the user sent, from any client. */
  outbound: boolean;
  /** The Detected Events (any status) it is the Anchor Message of; usually none or one. */
  detectedEvents: DetectedEvent[];
}

/**
 * A page of Messages, oldest first (display order): the newest `limit` older than `before`,
 * the oldest `limit` newer than `after`, or `limit` centred on `around`. Pass `olderCursor`
 * as `before` for the page before this one, `newerCursor` as `after` for the one after.
 */
export interface MessagePage {
  messages: Message[];
  hasOlder: boolean;
  olderCursor: number | null;
  /** False once the page reaches the newest Message. */
  hasNewer: boolean;
  newerCursor: number | null;
}

export interface EventFilter {
  /** Only these statuses (any when left out). */
  status?: DetectedEventStatus[];
  chatId?: number;
  /** Only those starting at or after this ISO 8601 time. */
  from?: string;
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

function query(params: Record<string, string | number | string[] | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, Array.isArray(value) ? value.join(",") : String(value));
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
  /** At most one of `before`, `after` and `around` (a Message id). */
  messages: (chatId: number, options: { before?: number; after?: number; around?: number; limit?: number } = {}) =>
    request<MessagePage>(`/api/chats/${chatId}/messages${query(options)}`),
  /** Make a Chat an Excluded Chat (never checked for plans), or include it again. */
  setChatExcluded: (chatId: number, excluded: boolean) =>
    request<Chat>(`/api/chats/${chatId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ excluded }),
    }),
  /** Detected Events, soonest first, each with its Chat and Anchor Message. */
  events: (filter: EventFilter = {}) =>
    request<{ events: DetectedEvent[] }>(`/api/events${query({ ...filter })}`),
  /** Dismiss a Pending Review Detected Event; resolves to it, now Dismissed. */
  dismissEvent: (eventId: number) =>
    request<DetectedEvent>(`/api/events/${eventId}/dismiss`, { method: "POST" }),
  /** Put a Pending Review Detected Event on the calendar (with edits); resolves to it, Confirmed. */
  confirmEvent: (eventId: number, edits: ConfirmEdits) =>
    request<DetectedEvent>(`/api/events/${eventId}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(edits),
    }),
  /** Send a Message through Beeper Desktop; resolves to the stored Outbound Message. */
  sendMessage: (chatId: number, text: string) =>
    request<Message>(`/api/chats/${chatId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
};
