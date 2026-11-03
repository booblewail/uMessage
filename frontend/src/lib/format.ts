// Times arrive from the API in UTC (ISO 8601) and are shown in the browser's time zone.

function isSameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

const TIME = { hour: "2-digit", minute: "2-digit" } as const;

/** Short time for the Chat list: "14:05" today, "Mon" this week, "3 Nov" before that. */
export function formatChatTime(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (isSameDay(date, now)) return date.toLocaleTimeString(undefined, TIME);
  const sixDaysAgo = new Date(now);
  sixDaysAgo.setDate(now.getDate() - 6);
  sixDaysAgo.setHours(0, 0, 0, 0);
  if (date >= sixDaysAgo) return date.toLocaleDateString(undefined, { weekday: "short" });
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Time for a Message: "14:05" today, otherwise "3 Nov, 14:05". */
export function formatMessageTime(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (isSameDay(date, now)) return date.toLocaleTimeString(undefined, TIME);
  return date.toLocaleString(undefined, { day: "numeric", month: "short", ...TIME });
}
