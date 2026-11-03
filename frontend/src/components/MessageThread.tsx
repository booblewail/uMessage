"use client";

import { useLayoutEffect, useRef } from "react";
import { ChevronUp, LoaderCircle, User, Users } from "lucide-react";
import type { Chat } from "@/lib/api";
import { useMessages } from "@/lib/useMessages";
import { MessageBubble } from "@/components/MessageBubble";
import { PlatformBadge } from "@/components/PlatformBadge";

/** The open Chat: its Messages oldest to newest, scrolled to the newest. Mount with key={chat.id}. */
export function MessageThread({ chat }: { chat: Chat }) {
  const { state, loadOlder } = useMessages(chat.id);
  const scroller = useRef<HTMLDivElement>(null);
  const newestId = state.kind === "loaded" ? state.messages.at(-1)?.id : undefined;

  useLayoutEffect(() => {
    const element = scroller.current;
    if (element && newestId !== undefined) element.scrollTop = element.scrollHeight;
  }, [newestId]);

  const Avatar = chat.kind === "group" ? Users : User;
  return (
    <section aria-label={`Messages in ${chat.title}`} className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center gap-3 border-b border-slate-200 px-5 py-3">
        <span className="flex size-9 items-center justify-center rounded-full bg-slate-100 text-slate-500">
          <Avatar className="size-4" aria-hidden />
        </span>
        <h2 className="min-w-0 flex-1 truncate font-semibold" data-testid="thread-title">
          {chat.title}
        </h2>
        <PlatformBadge platform={chat.platform} />
      </header>

      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto bg-slate-50 px-5 py-4">
        {state.kind === "loading" && (
          <p className="flex items-center gap-2 text-sm text-slate-500">
            <LoaderCircle className="size-4 animate-spin" aria-hidden />
            Loading Messages…
          </p>
        )}
        {state.kind === "failed" && (
          <p className="text-sm text-rose-700">Couldn&apos;t load Messages: {state.error.message}</p>
        )}
        {state.kind === "loaded" && (
          <>
            {state.olderCursor !== null && (
              <div className="mb-4 flex justify-center">
                <button
                  type="button"
                  onClick={loadOlder}
                  disabled={state.loadingOlder}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-60"
                >
                  <ChevronUp className="size-3.5" aria-hidden />
                  {state.loadingOlder ? "Loading…" : "Older Messages"}
                </button>
              </div>
            )}
            {state.messages.length === 0 ? (
              <p className="text-center text-sm text-slate-500">No text Messages in this Chat yet.</p>
            ) : (
              <ol aria-label="Messages" className="flex flex-col gap-3">
                {state.messages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
              </ol>
            )}
          </>
        )}
      </div>
    </section>
  );
}
