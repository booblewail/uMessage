"use client";

import { useState } from "react";
import { CalendarCheck, CalendarClock, LoaderCircle, MapPin, X } from "lucide-react";
import { api, toApiError, type DetectedEvent } from "@/lib/api";
import { formatEventTime } from "@/lib/format";

interface Props {
  event: DetectedEvent;
  /** Which side its Anchor Message sits on (an Outbound Message is on the right). */
  outbound: boolean;
  /** Called with the Detected Event as it is once Dismissed. */
  onChanged: (event: DetectedEvent) => void;
}

/**
 * A Detected Event beneath its Anchor Message: what, when and where, and Dismiss while it is
 * Pending Review (Add to Calendar arrives with #9). Dismissed ones aren't shown.
 */
export function DetectedEventBanner({ event, outbound, onChanged }: Props) {
  const [dismissing, setDismissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (event.status === "dismissed") return null;
  const pending = event.status === "pending_review";

  const dismiss = async () => {
    setDismissing(true);
    setError(null);
    try {
      onChanged(await api.dismissEvent(event.id));
    } catch (failure) {
      setError(toApiError(failure).message);
      setDismissing(false);
    }
  };

  const Icon = pending ? CalendarClock : CalendarCheck;
  return (
    <aside
      aria-label={`Detected Event: ${event.title}`}
      data-testid="detected-event"
      data-status={event.status}
      className={`flex w-full max-w-sm flex-col gap-2 rounded-xl border px-3.5 py-2.5 text-sm shadow-sm ${
        outbound ? "self-end" : "self-start"
      } ${pending ? "border-amber-300 bg-amber-50 text-amber-950" : "border-emerald-300 bg-emerald-50 text-emerald-950"}`}
    >
      <div className="flex items-start gap-2.5">
        <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide opacity-70">
            {pending ? "Plan spotted" : "On your calendar"}
          </p>
          <p className="font-semibold" data-testid="detected-event-title">
            {event.title}
          </p>
          <p data-testid="detected-event-time">
            <time dateTime={event.start}>{formatEventTime(event.start, event.end, event.allDay)}</time>
          </p>
          {event.location && (
            <p className="flex items-center gap-1 opacity-80">
              <MapPin className="size-3.5 shrink-0" aria-hidden />
              <span className="truncate">{event.location}</span>
            </p>
          )}
        </div>
      </div>
      {pending && (
        <div className="flex items-center justify-end gap-2">
          {error && (
            <p role="alert" className="mr-auto text-xs text-rose-700">
              Couldn&apos;t dismiss: {error}
            </p>
          )}
          <button
            type="button"
            onClick={() => void dismiss()}
            disabled={dismissing}
            data-testid="dismiss-event"
            className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-white px-3 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-60"
          >
            {dismissing ? (
              <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <X className="size-3.5" aria-hidden />
            )}
            Dismiss
          </button>
        </div>
      )}
    </aside>
  );
}
