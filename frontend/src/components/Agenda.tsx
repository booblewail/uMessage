import Link from "next/link";
import { CalendarCheck, MapPin } from "lucide-react";
import type { DetectedEvent } from "@/lib/api";
import { anchorLink, byDay } from "@/lib/events";
import { formatAgendaDay } from "@/lib/format";
import { PlatformBadge } from "@/components/PlatformBadge";

const TIME = { hour: "2-digit", minute: "2-digit" } as const;

function AgendaItem({ event }: { event: DetectedEvent }) {
  const start = new Date(event.start);
  return (
    <li data-testid="agenda-item" data-event-id={event.id}>
      <Link
        href={anchorLink(event)}
        title="Open the Chat at the Message this plan came from"
        className="flex items-start gap-3 rounded-lg px-3 py-2 hover:bg-slate-50"
      >
        <span className="w-20 shrink-0 whitespace-nowrap pt-0.5 text-sm tabular-nums text-slate-600">
          {event.allDay ? "All day" : start.toLocaleTimeString(undefined, TIME)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 font-medium">
            <CalendarCheck className="size-3.5 shrink-0 text-emerald-600" aria-hidden />
            <span className="truncate" data-testid="agenda-item-title">
              {event.title}
            </span>
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
            <span className="truncate">{event.chat.title}</span>
            <PlatformBadge platform={event.chat.platform} />
            {event.location && (
              <span className="inline-flex items-center gap-0.5">
                <MapPin className="size-3" aria-hidden />
                {event.location}
              </span>
            )}
          </span>
        </span>
      </Link>
    </li>
  );
}

/** Upcoming Confirmed plans (each on the calendar), grouped by day; each links to its Chat. */
export function Agenda({ events }: { events: DetectedEvent[] }) {
  if (events.length === 0) {
    return <p className="p-4 text-sm text-slate-500">Nothing on your calendar from your Chats yet.</p>;
  }
  return (
    <ol aria-label="Upcoming plans" className="flex flex-col gap-4">
      {byDay(events).map(({ day, events: onDay }) => (
        <li key={day}>
          <h3 className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-500" data-testid="agenda-day">
            {formatAgendaDay(onDay[0].start)}
          </h3>
          <ul className="flex flex-col">
            {onDay.map((event) => (
              <AgendaItem key={event.id} event={event} />
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
}
