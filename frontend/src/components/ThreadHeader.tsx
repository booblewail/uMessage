"use client";

import { useState } from "react";
import { CalendarOff, CalendarSearch, LoaderCircle, User, Users } from "lucide-react";
import { api, toApiError, type Chat } from "@/lib/api";
import { PlatformBadge } from "@/components/PlatformBadge";

interface Props {
  chat: Chat;
  /** Called with the Chat as it is once excluded or included again. */
  onChatChanged: (chat: Chat) => void;
}

/** The open Chat's title and Platform, and the switch that makes it an Excluded Chat. */
export function ThreadHeader({ chat, onChatChanged }: Props) {
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
      <div className="flex items-center gap-3">
        <span className="flex size-9 items-center justify-center rounded-full bg-slate-100 text-slate-500">
          <Avatar className="size-4" aria-hidden />
        </span>
        <h2 className="min-w-0 flex-1 truncate font-semibold" data-testid="thread-title">
          {chat.title}
        </h2>
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
      {error && (
        <p role="alert" className="text-xs text-rose-700">
          Couldn&apos;t change plan detection: {error}
        </p>
      )}
    </header>
  );
}
