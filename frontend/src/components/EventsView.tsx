"use client";

import { CalendarClock, CalendarDays, CalendarRange, LoaderCircle } from "lucide-react";
import { PENDING_REVIEW, type EventQuery } from "@/lib/events";
import { useEvents, type EventsState } from "@/lib/useEvents";
import { useInboxSocket } from "@/lib/ws";
import { Agenda } from "@/components/Agenda";
import { AppNav } from "@/components/AppNav";
import { LiveIndicator } from "@/components/LiveIndicator";
import { ReviewCard } from "@/components/ReviewCard";

function Loading({ state }: { state: EventsState }) {
  if (state.kind === "loading") {
    return (
      <p className="flex items-center gap-2 p-4 text-sm text-slate-500">
        <LoaderCircle className="size-4 animate-spin" aria-hidden />
        Loading plans…
      </p>
    );
  }
  return state.kind === "failed" ? (
    <p className="p-4 text-sm text-rose-700">Couldn&apos;t load plans: {state.error.message}</p>
  ) : null;
}

const UPCOMING: EventQuery = { status: ["confirmed"], upcoming: true };

/** The plans page: the Pending Review queue, and the agenda of upcoming Confirmed plans. Live. */
export function EventsView() {
  const socket = useInboxSocket();
  const queue = useEvents(PENDING_REVIEW, socket.subscribe, socket.reconnects);
  const agenda = useEvents(UPCOMING, socket.subscribe, socket.reconnects);
  const pending = queue.state.kind === "loaded" ? queue.state.events : null;

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-4 px-4 py-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <CalendarDays className="size-6 text-indigo-600" aria-hidden />
          Plans
        </h1>
        <div className="flex items-center gap-3">
          <AppNav pendingCount={pending?.length ?? null} />
          <LiveIndicator live={socket.live} />
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section aria-labelledby="review-heading" className="flex flex-col gap-3">
          <h2 id="review-heading" className="flex items-center gap-2 font-semibold">
            <CalendarClock className="size-4 text-amber-600" aria-hidden />
            Pending Review
            {pending && <span className="text-sm font-normal text-slate-500">({pending.length})</span>}
          </h2>
          <Loading state={queue.state} />
          {pending?.length === 0 && (
            <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
              Nothing to review. New plans spotted in your Chats show up here.
            </p>
          )}
          {pending && pending.length > 0 && (
            <ul aria-label="Pending Review" className="flex flex-col gap-3">
              {pending.map((event) => (
                <ReviewCard key={event.id} event={event} onChanged={queue.showEvent} />
              ))}
            </ul>
          )}
        </section>

        <section
          aria-labelledby="agenda-heading"
          className="flex flex-col gap-3 self-start rounded-xl border border-slate-200 bg-white p-3"
        >
          <h2 id="agenda-heading" className="flex items-center gap-2 px-1 font-semibold">
            <CalendarRange className="size-4 text-emerald-600" aria-hidden />
            Upcoming
          </h2>
          <Loading state={agenda.state} />
          {agenda.state.kind === "loaded" && <Agenda events={agenda.state.events} />}
        </section>
      </div>
    </div>
  );
}
