"use client";

import { Inbox } from "lucide-react";
import { DemoModeBadge } from "@/components/DemoModeBadge";
import { MessageSourceBanner } from "@/components/MessageSourceBanner";
import { useAppStatus } from "@/lib/useAppStatus";

export function InboxView() {
  const state = useAppStatus();
  const isDemo = state.kind === "loaded" && state.status.mode === "demo";

  return (
    <div className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-4 py-8">
      <header className="flex items-center justify-between gap-4">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Inbox className="size-6 text-indigo-600" aria-hidden />
          Inbox
        </h1>
        {isDemo && <DemoModeBadge />}
      </header>

      <MessageSourceBanner state={state} />

      <section className="rounded-xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">
        Your Chats will appear here.
      </section>
    </div>
  );
}
