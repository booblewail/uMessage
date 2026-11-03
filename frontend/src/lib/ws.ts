"use client";

// Reconnecting WebSocket to the backend's `/ws`: live inbox events.

import { useCallback, useEffect, useRef, useState } from "react";
import { API_TOKEN, API_URL, type Chat, type Message } from "@/lib/api";

export type InboxEvent =
  /** Sent on every (re)connect: refetch then, to catch up on anything missed while away. */
  | { type: "CONNECTED" }
  /** A Message was stored: the Message as the messages API shows it, and its Chat as listed. */
  | { type: "NEW_MESSAGE"; chatId: number; message: Message; chat: Chat };

export type InboxListener = (event: InboxEvent) => void;
/** Listen to inbox events; returns the function that stops listening. */
export type Subscribe = (listener: InboxListener) => () => void;

export interface InboxSocket {
  /** Whether live updates are flowing right now. */
  live: boolean;
  /** How many times the socket has come back after dropping (starts at 0). */
  reconnects: number;
  subscribe: Subscribe;
}

const FIRST_RETRY_MS = 1000;
const MAX_RETRY_MS = 30_000;

function socketUrl(): string {
  const url = new URL("/ws", API_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("token", API_TOKEN);
  return url.toString();
}

/** One WebSocket for the inbox, reconnecting with exponential backoff (1 s up to 30 s). */
export function useInboxSocket(): InboxSocket {
  const listeners = useRef(new Set<InboxListener>());
  const [live, setLive] = useState(false);
  const [reconnects, setReconnects] = useState(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let retryMs = FIRST_RETRY_MS;
    let connectedBefore = false;
    let stopped = false;

    const connect = () => {
      socket = new WebSocket(socketUrl());
      socket.onmessage = (message: MessageEvent<string>) => {
        let event: InboxEvent;
        try {
          event = JSON.parse(message.data) as InboxEvent;
        } catch {
          return;
        }
        if (event.type === "CONNECTED") {
          retryMs = FIRST_RETRY_MS;
          setLive(true);
          if (connectedBefore) setReconnects((count) => count + 1);
          connectedBefore = true;
        }
        for (const listener of listeners.current) listener(event);
      };
      socket.onclose = () => {
        setLive(false);
        if (stopped) return;
        timer = setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, MAX_RETRY_MS);
      };
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, []);

  const subscribe = useCallback<Subscribe>((listener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);

  return { live, reconnects, subscribe };
}
