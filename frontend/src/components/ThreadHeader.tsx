"use client";

import { useState } from "react";
import { CalendarDays, CalendarOff, CalendarSearch, LoaderCircle, User, Users } from "lucide-react";
import { api, toApiError, type Chat } from "@/lib/api";
import { PlatformBadge } from "@/components/PlatformBadge";

interface Props {
  chat: Chat;
  /** Called with the Chat as it is once excluded or included again. */
  onChatChanged: (chat: Chat) => void;
  /** How many upcoming plans the Chat has (null until known). */
  plansCount: number | null;
  plansOpen: boolean;
  onTogglePlans: () => void;
}

/**
 * The open Chat's title and Platform, the button that shows its upcoming plans, and the
 * switch that makes it an Excluded Chat.
 */
export function ThreadHeader({ chat, onChatChanged, plansCount, plansOpen, onTogglePlans }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const detecting = !chat.excluded;

  const toggle = async () => {
    setSaving(true);
    setError(null);
    try {
      onChatChanged(await api.setChatExcluded(chat.id, detecting));
    } catch (failure) {
      setError(toApiError(failure).message);
    } finally {
      setSaving(false);
    }
  };

  const Avatar = chat.kind === "group" ? Users : User;
  const Icon = saving ? LoaderCircle : detecting ? CalendarSearch : CalendarOff;
  return (
    <header className="flex flex-col gap-1 border-b border-slate-200 px-5 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-500">
          <Avatar className="size-4" aria-hidden />
        </span>
        <h2 className="min-w-28 flex-1 truncate font-semibold" data-testid="thread-title">
          {chat.title}
        </h2>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={onTogglePlans}
            aria-pressed={plansOpen}
            data-testid="toggle-chat-plans"
            title="This Chat's upcoming plans"
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
              plansOpen ? "border-slate-800 bg-slate-800 text-white" : "border-slate-300 text-slate-700 hover:bg-slate-100"
            }`}
          >
            <CalendarDays className="size-3.5" aria-hidden />
            Plans{plansCount ? ` (${plansCount})` : ""}
          </button>
          <button
            type="button"
            role="switch"
            aria-checked={detecting}
            onClick={() => void toggle()}
            disabled={saving}
            data-testid="plan-detection-toggle"
            title={
              detecting
                ? "This Chat is checked for plans. Turn off to make it an Excluded Chat (never sent for plan detection)."
                : "Excluded Chat: never checked for plans. Turn on to check new Messages again."
            }
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium disabled:opacity-60 ${
              detecting
                ? "border-indigo-200 bg-indigo-50 text-indigo-800 hover:bg-indigo-100"
                : "border-slate-300 bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            <Icon className={`size-3.5 ${saving ? "animate-spin" : ""}`} aria-hidden />
            Plan detection {detecting ? "on" : "off"}
          </button>
          <PlatformBadge platform={chat.platform} />
        </div>
      </div>
      {error && (
        <p role="alert" className="text-xs text-rose-700">
          Couldn&apos;t change plan detection: {error}
        </p>
      )}
    </header>
  );
}
