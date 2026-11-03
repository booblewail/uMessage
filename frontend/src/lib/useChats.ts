"use client";

import { useCallback, useEffect, useState } from "react";
import { api, toApiError, type ApiError, type Chat, type Platform } from "@/lib/api";
import { upsertChat } from "@/lib/messageList";
import type { Subscribe } from "@/lib/ws";

export type ChatsState =
  | { kind: "loading" }
  | { kind: "loaded"; chats: Chat[] }
  | { kind: "failed"; error: ApiError };

/**
 * The Chat list for `platform` (all Platforms when null), newest first. It reloads whenever
 * `reloadKey` changes (e.g. as First Import adds Chats, or the live socket reconnects); the
 * previous list stays on screen while the next one loads. `NEW_MESSAGE` events move their
 * Chat to the top (adding it if it is new); `updateChat` shows a change made in the inbox.
 */
export function useChats(
  platform: Platform | null,
  reloadKey: string,
  subscribe: Subscribe,
): { state: ChatsState; updateChat: (chat: Chat) => void } {
  const [state, setState] = useState<ChatsState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    api.chats(platform ?? undefined).then(
      ({ chats }) => {
        if (!cancelled) setState({ kind: "loaded", chats });
      },
      (error: unknown) => {
        if (!cancelled) setState({ kind: "failed", error: toApiError(error) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [platform, reloadKey]);

  useEffect(
    () =>
      subscribe((event) => {
        if (event.type !== "NEW_MESSAGE" || (platform && event.chat.platform !== platform)) return;
        setState((current) =>
          current.kind === "loaded" ? { kind: "loaded", chats: upsertChat(current.chats, event.chat) } : current,
        );
      }),
    [platform, subscribe],
  );

  const updateChat = useCallback((chat: Chat) => {
    setState((current) =>
      current.kind === "loaded" ? { kind: "loaded", chats: upsertChat(current.chats, chat) } : current,
    );
  }, []);

  return { state, updateChat };
}
