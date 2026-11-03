// The "Add to Calendar" form: a Detected Event as editable inputs in the browser's local time,
// and back into the edits the confirm API takes.

import type { ConfirmEdits, DetectedEvent } from "@/lib/api";

/**
 * Both kinds of time are kept, so switching all-day on and off doesn't lose what was typed:
 * `startDate`/`endDate` ("YYYY-MM-DD", end inclusive) for an all-day plan, `startTime`/`endTime`
 * (`datetime-local` values, "YYYY-MM-DDTHH:mm") for a timed one. An empty end means none.
 */
export interface EventForm {
  title: string;
  allDay: boolean;
  startDate: string;
  endDate: string;
  startTime: string;
  endTime: string;
  location: string;
}

const DEFAULT_TIME = "09:00";

const pad = (n: number) => String(n).padStart(2, "0");
const localDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const localDateTime = (d: Date) => `${localDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

export function formFromEvent(event: DetectedEvent): EventForm {
  const start = new Date(event.start);
  const end = event.end ? new Date(event.end) : null;
  const startDate = localDate(start);
  return {
    title: event.title,
    allDay: event.allDay,
    startDate,
    endDate: end ? localDate(end) : startDate,
    startTime: event.allDay ? `${startDate}T${DEFAULT_TIME}` : localDateTime(start),
    endTime: end && !event.allDay ? localDateTime(end) : "",
    location: event.location ?? "",
  };
}

/** Switch between all-day and timed, carrying the days (and times) over. */
export function withAllDay(form: EventForm, allDay: boolean): EventForm {
  if (allDay === form.allDay) return form;
  if (allDay) {
    const startDate = form.startTime.slice(0, 10) || form.startDate;
    const endDate = form.endTime.slice(0, 10);
    return { ...form, allDay, startDate, endDate: endDate >= startDate ? endDate : startDate };
  }
  const time = form.startTime.slice(11) || DEFAULT_TIME;
  const endTime = form.endTime.slice(0, 10) === form.endDate ? form.endTime : "";
  return { ...form, allDay, startTime: `${form.startDate}T${time}`, endTime };
}

/** What's wrong with the form, in words for the user; null when it can be confirmed. */
export function formProblem(form: EventForm): string | null {
  if (!form.title.trim()) return "Give the plan a title.";
  if (form.allDay) {
    if (!form.startDate) return "Pick the day it starts.";
    if (form.endDate && form.endDate < form.startDate) return "It can't end before it starts.";
    return null;
  }
  if (!form.startTime) return "Pick when it starts.";
  if (form.endTime && new Date(form.endTime) <= new Date(form.startTime)) {
    return "It has to end after it starts.";
  }
  return null;
}

/** The edits to confirm with (call it once `formProblem` is null). */
export function editsFromForm(form: EventForm): ConfirmEdits {
  const common = { title: form.title.trim(), location: form.location.trim() || null };
  if (form.allDay) {
    return { ...common, allDay: true, start: form.startDate, end: form.endDate || null };
  }
  return {
    ...common,
    allDay: false,
    start: new Date(form.startTime).toISOString(),
    end: form.endTime ? new Date(form.endTime).toISOString() : null,
  };
}
