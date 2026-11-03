"use client";

import { useEffect, useState } from "react";
import { api, toApiError, type ApiError, type Chat, type Platform } from "@/lib/api";

export type ChatsState =
  | { kind: "loading" }
  | { kind: "loaded"; chats: Chat[] }
  | { kind: "failed"; error: ApiError };

/**
 * The Chat list for `platform` (all Platforms when null), newest first. It reloads whenever
 * `reloadKey` changes (e.g. as First Import adds Chats); the previous list stays on screen
 * while the next one loads.
 */
export function useChats(platform: Platform | null, reloadKey: string): ChatsState {
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

  return state;
}
