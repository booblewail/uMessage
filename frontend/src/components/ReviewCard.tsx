"use client";

import Link from "next/link";
import { CalendarPlus, LoaderCircle, MapPin, MessageSquareQuote, X } from "lucide-react";
import type { DetectedEvent } from "@/lib/api";
import { anchorLink } from "@/lib/events";
import { formatEventTime, formatMessageTime } from "@/lib/format";
import { useEventActions } from "@/lib/useEventActions";
import { CalendarHint } from "@/components/CalendarHint";
import { EventEditDialog } from "@/components/EventEditDialog";
import { PlatformBadge } from "@/components/PlatformBadge";

interface Props {
  event: DetectedEvent;
  /** Called with the Detected Event as it is once Confirmed or Dismissed. */
  onChanged: (event: DetectedEvent) => void;
}

const BUTTON = "inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium disabled:opacity-60";

/**
 * A Pending Review Detected Event on the plans page: its Chat, the Anchor Message quoted (a
 * link back to it in the inbox), what, when and where; "Approve & Sync" (edit, then confirm
 * onto the calendar) or Dismiss.
 */
export function ReviewCard({ event, onChanged }: Props) {
  const { dismissing, editing, setEditing, error, dismiss, confirmed } = useEventActions(event, onChanged);
  const confirming = event.status === "confirming";
  const anchor = event.anchorMessage;
  return (
    <li
      data-testid="review-card"
      data-event-id={event.id}
      className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-white p-4 shadow-sm"
    >
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="truncate font-medium text-slate-700" data-testid="review-card-chat">
          {event.chat.title}
        </span>
        <PlatformBadge platform={event.chat.platform} />
      </div>
      <Link
        href={anchorLink(event)}
        data-testid="anchor-link"
        title="Open the Chat at this Message"
        className="group flex gap-2 rounded-lg border-l-4 border-slate-300 bg-slate-50 px-3 py-2 text-sm hover:border-indigo-400 hover:bg-indigo-50"
      >
        <MessageSquareQuote className="mt-0.5 size-4 shrink-0 text-slate-400 group-hover:text-indigo-500" aria-hidden />
        <span className="min-w-0">
          <span className="text-xs text-slate-500">
            <span className="font-medium text-slate-700">{anchor.outbound ? "You" : anchor.senderName}</span>
            {" · "}
            <time dateTime={anchor.sentAt}>{formatMessageTime(anchor.sentAt)}</time>
          </span>
          <q className="line-clamp-3 block whitespace-pre-wrap text-slate-800 before:content-none after:content-none">
            {anchor.text}
          </q>
        </span>
      </Link>
      <div>
        <p className="font-semibold" data-testid="review-card-title">
          {event.title}
        </p>
        <p className="text-sm text-slate-700">
          <time dateTime={event.start}>{formatEventTime(event.start, event.end, event.allDay)}</time>
        </p>
        {event.location && (
          <p className="flex items-center gap-1 text-sm text-slate-600">
            <MapPin className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate">{event.location}</span>
          </p>
        )}
      </div>
      <CalendarHint entries={event.existingCalendarEntries} />
      <div className="flex items-center justify-end gap-2">
        {error && (
          <p role="alert" className="mr-auto text-xs text-rose-700">
            Couldn&apos;t dismiss: {error}
          </p>
        )}
        <button
          type="button"
          onClick={dismiss}
          disabled={dismissing || confirming}
          data-testid="dismiss-event"
          className={`${BUTTON} border border-slate-300 text-slate-700 hover:bg-slate-100`}
        >
          {dismissing ? <LoaderCircle className="size-3.5 animate-spin" aria-hidden /> : <X className="size-3.5" aria-hidden />}
          Dismiss
        </button>
        <button
          type="button"
          onClick={() => setEditing(true)}
          disabled={dismissing || confirming}
          data-testid="approve-event"
          className={`${BUTTON} bg-indigo-600 text-white hover:bg-indigo-700`}
        >
          {confirming ? <LoaderCircle className="size-3.5 animate-spin" aria-hidden /> : <CalendarPlus className="size-3.5" aria-hidden />}
          {confirming ? "Adding…" : "Approve & Sync"}
        </button>
      </div>
      {editing && !confirming && (
        <EventEditDialog event={event} onConfirmed={confirmed} onClose={() => setEditing(false)} />
      )}
    </li>
  );
}
