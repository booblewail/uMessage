"use client";

import { ChevronUp, LoaderCircle } from "lucide-react";
import type { Chat } from "@/lib/api";
import { useMessages, type MessagesState } from "@/lib/useMessages";
import { useThreadScroll } from "@/lib/useThreadScroll";
import type { Subscribe } from "@/lib/ws";
import { MessageBubble } from "@/components/MessageBubble";
import { ReplyBar } from "@/components/ReplyBar";
import { ThreadHeader } from "@/components/ThreadHeader";

interface Props {
  chat: Chat;
  subscribe: Subscribe;
  /** Changes whenever the live socket reconnects (the thread then refetches). */
  reconnects: number;
  /** Called with the Chat as it is after a change made here (excluded or included). */
  onChatChanged: (chat: Chat) => void;
}

type Loaded = Extract<MessagesState, { kind: "loaded" }>;

/** Above the Messages: loading older ones, a button to load them, or the start of the Chat. */
function OlderMessages({ state, onLoad }: { state: Loaded; onLoad: () => void }) {
  if (state.loadingOlder) {
    return (
      <p className="mb-4 flex items-center justify-center gap-2 text-xs text-slate-500" data-testid="loading-older">
        <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
        Loading older Messages…
      </p>
    );
  }
  if (state.olderCursor === null) {
    return state.messages.length > 0 ? (
      <p className="mb-4 text-center text-xs text-slate-400" data-testid="start-of-chat">
        Start of this Chat
      </p>
    ) : null;
  }
  return (
    <div className="mb-4 flex flex-col items-center gap-1">
      {state.olderError && (
        <p role="alert" className="text-xs text-rose-700">
          Couldn&apos;t load older Messages: {state.olderError}
        </p>
      )}
      <button
        type="button"
        onClick={onLoad}
        data-testid="load-older"
        className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
      >
        <ChevronUp className="size-3.5" aria-hidden />
        {state.olderError ? "Try again" : "Older Messages"}
      </button>
    </div>
  );
}

/**
 * The open Chat: its Messages oldest to newest, scrolled to the newest, with new ones added
 * live and older ones loaded on scrolling to the top, and Detected Events beneath their
 * Anchor Messages. Mount with key={chat.id}.
 */
export function MessageThread({ chat, subscribe, reconnects, onChatChanged }: Props) {
  const { state, loadOlder, addMessage, showEvent } = useMessages(chat.id, subscribe, reconnects);
  const loaded = state.kind === "loaded" ? state : null;
  const canLoadOlder = loaded !== null && loaded.olderCursor !== null && !loaded.loadingOlder;
  const { scroller, onScroll, requestOlder } = useThreadScroll(loaded?.messages ?? [], canLoadOlder, loadOlder);

  return (
    <section aria-label={`Messages in ${chat.title}`} className="flex min-h-0 flex-1 flex-col">
      <ThreadHeader chat={chat} onChatChanged={onChatChanged} />

      <div
        ref={scroller}
        onScroll={onScroll}
        data-testid="thread-scroller"
        className="min-h-0 flex-1 overflow-y-auto bg-slate-50 px-5 py-4"
      >
        {state.kind === "loading" && (
          <p className="flex items-center gap-2 text-sm text-slate-500">
            <LoaderCircle className="size-4 animate-spin" aria-hidden />
            Loading Messages…
          </p>
        )}
        {state.kind === "failed" && (
          <p className="text-sm text-rose-700">Couldn&apos;t load Messages: {state.error.message}</p>
        )}
        {loaded && (
          <>
            <OlderMessages state={loaded} onLoad={requestOlder} />
            {loaded.messages.length === 0 ? (
              <p className="text-center text-sm text-slate-500">No text Messages in this Chat yet.</p>
            ) : (
              <ol aria-label="Messages" className="flex flex-col gap-3">
                {loaded.messages.map((message) => (
                  <MessageBubble key={message.id} message={message} onEventChanged={showEvent} />
                ))}
              </ol>
            )}
          </>
        )}
      </div>
      <ReplyBar chatId={chat.id} chatTitle={chat.title} onSent={addMessage} />
    </section>
  );
}
