"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, toApiError, type ApiError, type DetectedEvent, type Message, type MessagePage } from "@/lib/api";
import { mergeMessages, withDetectedEvent } from "@/lib/messageList";
import type { Subscribe } from "@/lib/ws";

export const PAGE_SIZE = 50;

export type MessagesState =
  | { kind: "loading" }
  | { kind: "failed"; error: ApiError }
  | {
      kind: "loaded";
      /** Oldest first, as the API pages them. */
      messages: Message[];
      olderCursor: number | null;
      /** Where the newer Messages not yet loaded start (null: loaded up to the present). */
      newerCursor: number | null;
      loading: "older" | "newer" | null;
      /** Why the last attempt to load more Messages failed (the loaded ones stay). */
      loadError: string | null;
    };

type Loaded = Extract<MessagesState, { kind: "loaded" }>;

function fromPage(page: MessagePage): Loaded {
  return {
    kind: "loaded",
    messages: page.messages,
    olderCursor: page.olderCursor,
    newerCursor: page.newerCursor,
    loading: null,
    loadError: null,
  };
}

/** Fold the newest page into what is shown: merged if they overlap, else it replaces it. */
function withNewestPage(current: MessagesState, page: MessagePage): MessagesState {
  if (current.kind !== "loaded" || page.messages.length === 0) return fromPage(page);
  const ids = new Set(current.messages.map((message) => message.id));
  const overlaps = !page.hasOlder || page.messages.some((message) => ids.has(message.id));
  if (!overlaps) return fromPage(page);
  return { ...current, messages: mergeMessages(current.messages, page.messages), newerCursor: null };
}

/**
 * A Chat's Messages: the newest page first (or, given `around`, the page centred on that
 * Message: an Anchor Message a link jumps to), then older pages added by `loadOlder` (from
 * Beeper Desktop once the stored ones run out, which the API does transparently) and newer
 * ones by `loadNewer`, down to the present. `NEW_MESSAGE` events for the Chat are added live
 * (each Message once), and `EVENT_DETECTED` events put the Detected Event beneath its Anchor
 * Message; the newest page is fetched again whenever `reconnects` changes. Mount it with
 * `key={chatId}` (and `around`).
 */
export function useMessages(chatId: number, around: number | null, subscribe: Subscribe, reconnects: number) {
  const [state, setState] = useState<MessagesState>({ kind: "loading" });
  // The Message to open at, until the page around it has loaded; after that (and on a
  // reconnect) the newest page is fetched.
  const jumpTo = useRef(around);

  useEffect(() => {
    let cancelled = false;
    const target = jumpTo.current;
    const options = target !== null ? { around: target } : {};
    api.messages(chatId, { ...options, limit: PAGE_SIZE }).then(
      (loaded) => {
        if (cancelled) return;
        setState((current) => (target !== null ? fromPage(loaded) : withNewestPage(current, loaded)));
        jumpTo.current = null;
      },
      (error: unknown) => {
        if (!cancelled) setState({ kind: "failed", error: toApiError(error) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [chatId, reconnects]);

  /** Show a Message (e.g. one just sent) unless it is already shown. */
  const addMessage = useCallback((message: Message) => {
    setState((current) =>
      current.kind === "loaded" ? { ...current, messages: mergeMessages(current.messages, [message]) } : current,
    );
  }, []);

  /** Show a Detected Event as it now is (e.g. just Dismissed) beneath its Anchor Message. */
  const showEvent = useCallback((event: DetectedEvent) => {
    setState((current) =>
      current.kind === "loaded" ? { ...current, messages: withDetectedEvent(current.messages, event) } : current,
    );
  }, []);

  useEffect(
    () =>
      subscribe((event) => {
        if (event.type === "NEW_MESSAGE" && event.chatId === chatId) addMessage(event.message);
        if (event.type === "EVENT_DETECTED" && event.event.chatId === chatId) showEvent(event.event);
      }),
    [chatId, subscribe, addMessage, showEvent],
  );

  const load = useCallback(
    (direction: "older" | "newer") => {
      if (state.kind !== "loaded" || state.loading) return;
      const cursor = direction === "older" ? state.olderCursor : state.newerCursor;
      if (cursor === null) return;
      setState({ ...state, loading: direction, loadError: null });
      const options = direction === "older" ? { before: cursor } : { after: cursor };
      api.messages(chatId, { ...options, limit: PAGE_SIZE }).then(
        (page) =>
          setState((current) =>
            current.kind === "loaded"
              ? {
                  ...current,
                  messages: mergeMessages(current.messages, page.messages),
                  ...(direction === "older" ? { olderCursor: page.olderCursor } : { newerCursor: page.newerCursor }),
                  loading: null,
                }
              : current,
          ),
        (error: unknown) =>
          setState((current) =>
            current.kind === "loaded" ? { ...current, loading: null, loadError: toApiError(error).message } : current,
          ),
      );
    },
    [chatId, state],
  );

  const loadOlder = useCallback(() => load("older"), [load]);
  const loadNewer = useCallback(() => load("newer"), [load]);
  return { state, loadOlder, loadNewer, addMessage, showEvent };
}
