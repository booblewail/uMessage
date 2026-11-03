"use client";

import { useState } from "react";
import { Inbox, MessageSquareDashed } from "lucide-react";
import type { Chat, Platform } from "@/lib/api";
import { PLATFORM_LOOKS } from "@/lib/platforms";
import { useAppStatus } from "@/lib/useAppStatus";
import { useChats } from "@/lib/useChats";
import { ChatList } from "@/components/ChatList";
import { DemoModeBadge } from "@/components/DemoModeBadge";
import { FirstImportNotice } from "@/components/FirstImportNotice";
import { MessageSourceBanner } from "@/components/MessageSourceBanner";
import { MessageThread } from "@/components/MessageThread";
import { PlatformFilter } from "@/components/PlatformFilter";

export function InboxView() {
  const state = useAppStatus();
  const status = state.kind === "loaded" ? state.status : null;
  const firstImport = status?.firstImport ?? null;

  const [platform, setPlatform] = useState<Platform | null>(null);
  const [selected, setSelected] = useState<Chat | null>(null);
  // Reload the list as First Import adds Chats.
  const reloadKey = firstImport ? `${firstImport.state}:${firstImport.chatsImported}` : "";
  const chats = useChats(platform, reloadKey);

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
        {status?.mode === "demo" && <DemoModeBadge />}
      </header>

      <MessageSourceBanner state={state} />
      {firstImport && <FirstImportNotice firstImport={firstImport} />}

      <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,2fr)_minmax(0,3fr)] gap-4 md:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] md:grid-rows-1">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="border-b border-slate-200 p-3">
            <PlatformFilter selected={platform} onSelect={setPlatform} />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <ChatList
              state={chats}
              selectedId={selected?.id ?? null}
              onSelect={setSelected}
              emptyText={emptyText}
            />
          </div>
        </aside>

        <main className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white">
          {selected ? (
            <MessageThread key={selected.id} chat={selected} />
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
