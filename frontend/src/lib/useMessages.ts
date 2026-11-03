"use client";

import { useCallback, useEffect, useState } from "react";
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
      loadingOlder: boolean;
      /** Why the last attempt to load older Messages failed (the loaded ones stay). */
      olderError: string | null;
    };

type Loaded = Extract<MessagesState, { kind: "loaded" }>;

/** Fold the newest page into what is shown: merged if they overlap, else it replaces it. */
function withNewestPage(current: MessagesState, page: MessagePage): MessagesState {
  const fresh: Loaded = {
    kind: "loaded",
    messages: page.messages,
    olderCursor: page.olderCursor,
    loadingOlder: false,
    olderError: null,
  };
  if (current.kind !== "loaded" || page.messages.length === 0) return fresh;
  const ids = new Set(current.messages.map((message) => message.id));
  const overlaps = !page.hasOlder || page.messages.some((message) => ids.has(message.id));
  return overlaps ? { ...current, messages: mergeMessages(current.messages, page.messages) } : fresh;
}

/**
 * A Chat's Messages: the newest page first, then older pages prepended by `loadOlder` (from
 * Beeper Desktop once the stored ones run out, which the API does transparently).
 * `NEW_MESSAGE` events for the Chat are added live (each Message once), and `EVENT_DETECTED`
 * events put the Detected Event beneath its Anchor Message; the newest page is fetched again
 * whenever `reconnects` changes. Mount it with `key={chatId}`.
 */
export function useMessages(
  chatId: number,
  subscribe: Subscribe,
  reconnects: number,
): {
  state: MessagesState;
  loadOlder: () => void;
  addMessage: (message: Message) => void;
  showEvent: (event: DetectedEvent) => void;
} {
  const [state, setState] = useState<MessagesState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    api.messages(chatId, { limit: PAGE_SIZE }).then(
      (page) => {
        if (!cancelled) setState((current) => withNewestPage(current, page));
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

  const loadOlder = useCallback(() => {
    if (state.kind !== "loaded" || state.olderCursor === null || state.loadingOlder) return;
    const before = state.olderCursor;
    setState({ ...state, loadingOlder: true, olderError: null });
    api.messages(chatId, { before, limit: PAGE_SIZE }).then(
      (page) =>
        setState((current) =>
          current.kind === "loaded"
            ? {
                ...current,
                messages: mergeMessages(current.messages, page.messages),
                olderCursor: page.olderCursor,
                loadingOlder: false,
              }
            : current,
        ),
      (error: unknown) =>
        setState((current) =>
          current.kind === "loaded"
            ? { ...current, loadingOlder: false, olderError: toApiError(error).message }
            : current,
        ),
    );
  }, [chatId, state]);

  return { state, loadOlder, addMessage, showEvent };
}
