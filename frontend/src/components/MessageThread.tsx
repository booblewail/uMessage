"use client";

import { useMemo, useState } from "react";
import { LoaderCircle } from "lucide-react";
import type { Chat } from "@/lib/api";
import type { EventQuery } from "@/lib/events";
import { useEvents } from "@/lib/useEvents";
import { useMessages } from "@/lib/useMessages";
import { useThreadScroll } from "@/lib/useThreadScroll";
import type { Subscribe } from "@/lib/ws";
import { ChatPlansDrawer } from "@/components/ChatPlansDrawer";
import { MessageBubble } from "@/components/MessageBubble";
import { ReplyBar } from "@/components/ReplyBar";
import { NewerMessages, OlderMessages } from "@/components/ThreadEdges";
import { ThreadHeader } from "@/components/ThreadHeader";

interface Props {
  chat: Chat;
  /** The Message to open at, highlighted (an Anchor Message a link jumps to). */
  highlightId: number | null;
  subscribe: Subscribe;
  /** Changes whenever the live socket reconnects (the thread then refetches). */
  reconnects: number;
  /** Called with the Chat as it is after a change made here (excluded or included). */
  onChatChanged: (chat: Chat) => void;
}

/**
 * The open Chat: its Messages oldest to newest, scrolled to the newest (or to the highlighted
 * Message), with new ones added live and more loaded on scrolling to the top or bottom, and
 * Detected Events beneath their Anchor Messages; beside it, on demand, its upcoming plans.
 * Mount with key={chat.id + highlightId}.
 */
export function MessageThread({ chat, highlightId, subscribe, reconnects, onChatChanged }: Props) {
  const { state, loadOlder, loadNewer, addMessage, showEvent } = useMessages(chat.id, highlightId, subscribe, reconnects);
  const loaded = state.kind === "loaded" ? state : null;
  const { scroller, onScroll, requestOlder } = useThreadScroll(loaded?.messages ?? [], {
    canLoadOlder: loaded !== null && loaded.olderCursor !== null && loaded.loading === null,
    loadOlder,
    canLoadNewer: loaded !== null && loaded.newerCursor !== null,
    loadNewer,
    highlightId,
  });
  const upcoming = useMemo<EventQuery>(
    () => ({ chatId: chat.id, status: ["pending_review", "confirming", "confirmed"], upcoming: true }),
    [chat.id],
  );
  const plans = useEvents(upcoming, subscribe, reconnects);
  const [plansOpen, setPlansOpen] = useState(false);
  const plansCount = plans.state.kind === "loaded" ? plans.state.events.length : null;

  return (
    <div className="flex min-h-0 flex-1">
      <section aria-label={`Messages in ${chat.title}`} className="flex min-h-0 min-w-0 flex-1 flex-col">
        <ThreadHeader
          chat={chat}
          onChatChanged={onChatChanged}
          plansCount={plansCount}
          plansOpen={plansOpen}
          onTogglePlans={() => setPlansOpen((open) => !open)}
        />

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
                    <MessageBubble
                      key={message.id}
                      message={message}
                      highlighted={message.id === highlightId}
                      onEventChanged={showEvent}
                    />
                  ))}
                </ol>
              )}
              <NewerMessages state={loaded} onLoad={loadNewer} />
            </>
          )}
        </div>
        <ReplyBar chatId={chat.id} chatTitle={chat.title} onSent={addMessage} />
      </section>
      {plansOpen && (
        <ChatPlansDrawer chatTitle={chat.title} state={plans.state} onClose={() => setPlansOpen(false)} />
      )}
    </div>
  );
}
