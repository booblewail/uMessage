"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Inbox, MessageSquareDashed } from "lucide-react";
import type { Chat, Platform } from "@/lib/api";
import { PENDING_REVIEW } from "@/lib/events";
import { PLATFORM_LOOKS } from "@/lib/platforms";
import { useAppStatus } from "@/lib/useAppStatus";
import { useChats } from "@/lib/useChats";
import { useEvents } from "@/lib/useEvents";
import { useInboxSocket } from "@/lib/ws";
import { AppNav } from "@/components/AppNav";
import { ChatList } from "@/components/ChatList";
import { DemoModeBadge } from "@/components/DemoModeBadge";
import { FirstImportNotice } from "@/components/FirstImportNotice";
import { LiveIndicator } from "@/components/LiveIndicator";
import { MessageSourceBanner } from "@/components/MessageSourceBanner";
import { MessageThread } from "@/components/MessageThread";
import { PlanDetectionNotice } from "@/components/PlanDetectionNotice";
import { PlatformFilter } from "@/components/PlatformFilter";

/** A positive integer from the URL, or null. */
function idParam(value: string | null): number | null {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/**
 * The inbox. The open Chat is in the URL (`/inbox?chat=<id>`); `&message=<id>` opens it at
 * that Message, highlighted (how links to an Anchor Message land).
 */
export function InboxView() {
  const state = useAppStatus();
  const socket = useInboxSocket();
  const status = state.kind === "loaded" ? state.status : null;
  const firstImport = status?.firstImport ?? null;
  const router = useRouter();
  const params = useSearchParams();
  const chatId = idParam(params.get("chat"));
  const messageId = idParam(params.get("message"));

  const [platform, setPlatform] = useState<Platform | null>(null);
  // Reload the list as First Import adds Chats, and after the live socket reconnects.
  const importKey = firstImport ? `${firstImport.state}:${firstImport.chatsImported}` : "";
  const { state: chats, updateChat } = useChats(platform, `${importKey}:${socket.reconnects}`, socket.subscribe);
  const pending = useEvents(PENDING_REVIEW, socket.subscribe, socket.reconnects);
  // The Chat picked last stays open while a Platform filter hides it from the list.
  const [picked, setPicked] = useState<Chat | null>(null);
  const listed = chats.kind === "loaded" ? chats.chats.find((chat) => chat.id === chatId) : undefined;
  const selected = listed ?? (picked && picked.id === chatId ? picked : null);
  const select = (chat: Chat) => {
    setPicked(chat);
    router.push(`/inbox?chat=${chat.id}`);
  };
  const onChatChanged = (chat: Chat) => {
    updateChat(chat);
    setPicked(chat);
  };

  const emptyText =
    firstImport && firstImport.state !== "completed"
      ? "Your Chats appear here once First Import has brought them in."
      : platform
        ? `No ${PLATFORM_LOOKS[platform].label} Chats.`
        : "No Chats yet.";

  return (
    <div className="mx-auto flex h-screen max-w-6xl flex-col gap-4 px-4 py-6">
      <header className="flex items-center justify-between gap-4">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Inbox className="size-6 text-indigo-600" aria-hidden />
          Inbox
        </h1>
        <div className="flex items-center gap-3">
          <AppNav pendingCount={pending.state.kind === "loaded" ? pending.state.events.length : null} />
          <LiveIndicator live={socket.live} />
          {status?.mode === "demo" && <DemoModeBadge />}
        </div>
      </header>

      <MessageSourceBanner state={state} />
      {firstImport && <FirstImportNotice firstImport={firstImport} />}
      {status && <PlanDetectionNotice planDetection={status.planDetection} />}

      <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,2fr)_minmax(0,3fr)] gap-4 md:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] md:grid-rows-1">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="border-b border-slate-200 p-3">
            <PlatformFilter selected={platform} onSelect={setPlatform} />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <ChatList
              state={chats}
              selectedId={selected?.id ?? null}
              onSelect={select}
              emptyText={emptyText}
            />
          </div>
        </aside>

        <main className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white">
          {selected ? (
            <MessageThread
              key={`${selected.id}:${messageId ?? ""}`}
              chat={selected}
              highlightId={messageId}
              subscribe={socket.subscribe}
              reconnects={socket.reconnects}
              onChatChanged={onChatChanged}
            />
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-10 text-sm text-slate-500">
              <MessageSquareDashed className="size-8 text-slate-300" aria-hidden />
              Pick a Chat to read its Messages.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
