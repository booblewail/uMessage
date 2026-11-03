// Lists of Detected Events kept in step with live `EVENT_DETECTED` updates.

import type { DetectedEvent, EventFilter } from "@/lib/api";

/** The inbox link that opens a Detected Event's Chat at its Anchor Message. */
export function anchorLink(event: Pick<DetectedEvent, "chatId" | "anchorMessageId">): string {
  return `/inbox?chat=${event.chatId}&message=${event.anchorMessageId}`;
}

/** Midnight at the start of today in the browser's time zone, as ISO 8601. */
export function startOfToday(now: Date = new Date()): string {
  const midnight = new Date(now);
  midnight.setHours(0, 0, 0, 0);
  return midnight.toISOString();
}

/** A filter for a live list of Detected Events; `upcoming`: from the start of today on. */
export type EventQuery = EventFilter & { upcoming?: boolean };

/** The events API filter for `query`, as of now (call it outside rendering). */
export function resolveQuery({ upcoming, ...filter }: EventQuery): EventFilter {
  return upcoming ? { ...filter, from: startOfToday() } : filter;
}

/** Whether `event` belongs in a list fetched with `filter` (as the events API filters). */
export function matchesFilter(event: DetectedEvent, filter: EventFilter): boolean {
  if (filter.status && !filter.status.includes(event.status)) return false;
  if (filter.chatId !== undefined && event.chatId !== filter.chatId) return false;
  if (filter.from && Date.parse(event.start) < Date.parse(filter.from)) return false;
  return true;
}

/**
 * The list with `event` as it now is: replaced, added or (no longer matching) removed, soonest
 * first; unless what is listed of it is newer (by `updatedAt`).
 */
export function withEvent(events: DetectedEvent[], event: DetectedEvent, query: EventQuery): DetectedEvent[] {
  const filter = resolveQuery(query);
  const listed = events.find((candidate) => candidate.id === event.id);
  if (listed && Date.parse(listed.updatedAt) > Date.parse(event.updatedAt)) return events;
  const others = events.filter((candidate) => candidate.id !== event.id);
  if (!matchesFilter(event, filter)) return others;
  return [...others, event].sort((a, b) => Date.parse(a.start) - Date.parse(b.start) || a.id - b.id);
}

/** Confirmed Detected Events grouped by their (local) start day, in order. */
export function byDay(events: DetectedEvent[]): { day: string; events: DetectedEvent[] }[] {
  const groups = new Map<string, DetectedEvent[]>();
  for (const event of events) {
    const day = new Date(event.start).toDateString();
    groups.set(day, [...(groups.get(day) ?? []), event]);
  }
  return [...groups].map(([day, grouped]) => ({ day, events: grouped }));
}

/** The plans awaiting the user's review (and any being added to the calendar right now). */
export const PENDING_REVIEW: EventQuery = { status: ["pending_review", "confirming"] };
