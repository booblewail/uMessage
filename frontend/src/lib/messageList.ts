// Keeping lists of Chats and Messages in order as live updates arrive.

import type { Chat, DetectedEvent, Message } from "@/lib/api";

function byTimeThenId(a: { time: string; id: number }, b: { time: string; id: number }): number {
  const diff = Date.parse(a.time) - Date.parse(b.time);
  return diff !== 0 ? diff : a.id - b.id;
}

/** Both lists' Messages, each once (by id; `incoming` wins), oldest first. */
export function mergeMessages(current: Message[], incoming: Message[]): Message[] {
  const byId = new Map(current.map((message) => [message.id, message]));
  for (const message of incoming) byId.set(message.id, message);
  return [...byId.values()].sort((a, b) =>
    byTimeThenId({ time: a.sentAt, id: a.id }, { time: b.sentAt, id: b.id }),
  );
}

/** The Chat list with `chat` added or updated, newest first (unless `chat` is out of date). */
export function upsertChat(chats: Chat[], chat: Chat): Chat[] {
  const existing = chats.find((candidate) => candidate.id === chat.id);
  if (existing && Date.parse(existing.lastMessageAt) > Date.parse(chat.lastMessageAt)) return chats;
  return [chat, ...chats.filter((candidate) => candidate.id !== chat.id)].sort((a, b) =>
    byTimeThenId({ time: b.lastMessageAt, id: b.id }, { time: a.lastMessageAt, id: a.id }),
  );
}

/**
 * The Messages with `event` beneath its Anchor Message only (it may have moved on), unless
 * what is shown of it is newer (by `updatedAt`).
 */
export function withDetectedEvent(messages: Message[], event: DetectedEvent): Message[] {
  const shown = messages.flatMap((message) => message.detectedEvents).find((other) => other.id === event.id);
  if (shown && Date.parse(shown.updatedAt) > Date.parse(event.updatedAt)) return messages;
  return messages.map((message) => {
    const others = message.detectedEvents.filter((candidate) => candidate.id !== event.id);
    if (message.id === event.anchorMessageId) return { ...message, detectedEvents: [...others, event] };
    return others.length === message.detectedEvents.length ? message : { ...message, detectedEvents: others };
  });
}
