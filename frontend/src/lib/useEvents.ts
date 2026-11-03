"use client";

import { useCallback, useEffect, useState } from "react";
import { api, toApiError, type ApiError, type DetectedEvent } from "@/lib/api";
import { resolveQuery, withEvent, type EventQuery } from "@/lib/events";
import type { Subscribe } from "@/lib/ws";

export type EventsState =
  | { kind: "loading" }
  | { kind: "loaded"; events: DetectedEvent[] }
  | { kind: "failed"; error: ApiError };

/**
 * The Detected Events matching `filter` (`upcoming`: from the start of today), soonest first, kept live: every `EVENT_DETECTED`
 * adds, updates or removes its event, and the list is fetched again whenever `reconnects`
 * (or `filter`: memoise it) changes.
 */
export function useEvents(
  filter: EventQuery,
  subscribe: Subscribe,
  reconnects: number,
): { state: EventsState; showEvent: (event: DetectedEvent) => void } {
  const [state, setState] = useState<EventsState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    api.events(resolveQuery(filter)).then(
      ({ events }) => {
        if (!cancelled) setState({ kind: "loaded", events });
      },
      (error: unknown) => {
        if (!cancelled) setState({ kind: "failed", error: toApiError(error) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [filter, reconnects]);

  /** Show a Detected Event as it now is (e.g. just Confirmed here). */
  const showEvent = useCallback(
    (event: DetectedEvent) =>
      setState((current) =>
        current.kind === "loaded" ? { kind: "loaded", events: withEvent(current.events, event, filter) } : current,
      ),
    [filter],
  );

  useEffect(
    () =>
      subscribe((event) => {
        if (event.type === "EVENT_DETECTED") showEvent(event.event);
      }),
    [subscribe, showEvent],
  );

  return { state, showEvent };
}
