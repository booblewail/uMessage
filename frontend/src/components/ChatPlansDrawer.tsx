"use client";

import Link from "next/link";
import { CalendarCheck, CalendarClock, LoaderCircle, X } from "lucide-react";
import { anchorLink } from "@/lib/events";
import { formatEventTime } from "@/lib/format";
import type { EventsState } from "@/lib/useEvents";

interface Props {
  chatTitle: string;
  state: EventsState;
  onClose: () => void;
}

/** Beside the open Chat: its upcoming plans (Pending Review and Confirmed), each a link to its Anchor Message. */
export function ChatPlansDrawer({ chatTitle, state, onClose }: Props) {
  return (
    <aside
      aria-label={`Upcoming plans in ${chatTitle}`}
      data-testid="chat-plans"
      className="flex w-72 shrink-0 flex-col border-l border-slate-200 bg-white"
    >
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h3 className="text-sm font-semibold">Upcoming plans</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close upcoming plans"
          className="rounded-full p-1 text-slate-500 hover:bg-slate-100"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {state.kind === "loading" && (
          <p className="flex items-center gap-2 p-2 text-sm text-slate-500">
            <LoaderCircle className="size-4 animate-spin" aria-hidden />
            Loading…
          </p>
        )}
        {state.kind === "failed" && <p className="p-2 text-sm text-rose-700">{state.error.message}</p>}
        {state.kind === "loaded" && state.events.length === 0 && (
          <p className="p-2 text-sm text-slate-500">No upcoming plans in this Chat.</p>
        )}
        {state.kind === "loaded" && state.events.length > 0 && (
          <ul className="flex flex-col gap-1">
            {state.events.map((event) => {
              const confirmed = event.status === "confirmed";
              const Icon = confirmed ? CalendarCheck : CalendarClock;
              return (
                <li key={event.id} data-testid="chat-plan" data-status={event.status}>
                  <Link
                    href={anchorLink(event)}
                    className="flex flex-col gap-1 rounded-lg px-2 py-2 text-sm hover:bg-slate-50"
                  >
                    <span className="flex items-center gap-1.5 font-medium">
                      <Icon className={`size-3.5 shrink-0 ${confirmed ? "text-emerald-600" : "text-amber-600"}`} aria-hidden />
                      <span className="truncate">{event.title}</span>
                    </span>
                    <span className="text-xs text-slate-600">
                      {formatEventTime(event.start, event.end, event.allDay)}
                    </span>
                    <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                      {confirmed ? "On your calendar" : "Pending review"}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
