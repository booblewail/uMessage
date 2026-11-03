"use client";

import { useCallback, useEffect, useState } from "react";
import { api, toApiError, type ApiError, type Message } from "@/lib/api";

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
    };

/**
 * A Chat's Messages: the newest page first, then older pages prepended by `loadOlder`.
 * Mount it with `key={chatId}` so switching Chats starts afresh.
 */
export function useMessages(chatId: number): { state: MessagesState; loadOlder: () => void } {
  const [state, setState] = useState<MessagesState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    api.messages(chatId, { limit: PAGE_SIZE }).then(
      (page) => {
        if (cancelled) return;
        setState({
          kind: "loaded",
          messages: page.messages,
          olderCursor: page.olderCursor,
          loadingOlder: false,
        });
      },
      (error: unknown) => {
        if (!cancelled) setState({ kind: "failed", error: toApiError(error) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [chatId]);

  const loadOlder = useCallback(() => {
    if (state.kind !== "loaded" || state.olderCursor === null || state.loadingOlder) return;
    const before = state.olderCursor;
    setState({ ...state, loadingOlder: true });
    api.messages(chatId, { before, limit: PAGE_SIZE }).then(
      (page) =>
        setState((current) =>
          current.kind === "loaded"
            ? {
                kind: "loaded",
                messages: [...page.messages, ...current.messages],
                olderCursor: page.olderCursor,
                loadingOlder: false,
              }
            : current,
        ),
      (error: unknown) => setState({ kind: "failed", error: toApiError(error) }),
    );
  }, [chatId, state]);

  return { state, loadOlder };
}
