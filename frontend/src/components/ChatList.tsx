import { CalendarOff, LoaderCircle, User, Users } from "lucide-react";
import type { Chat } from "@/lib/api";
import { formatChatTime } from "@/lib/format";
import type { ChatsState } from "@/lib/useChats";
import { PlatformBadge } from "@/components/PlatformBadge";

interface Props {
  state: ChatsState;
  selectedId: number | null;
  onSelect: (chat: Chat) => void;
  /** What to say when there are no Chats to show. */
  emptyText: string;
}

function preview(chat: Chat): string {
  const last = chat.lastMessage;
  if (!last) return "No text Messages yet";
  const who = last.outbound ? "You" : chat.kind === "group" ? last.senderName : null;
  return who ? `${who}: ${last.text}` : last.text;
}

function ChatRow({ chat, selected, onSelect }: { chat: Chat; selected: boolean; onSelect: () => void }) {
  const Avatar = chat.kind === "group" ? Users : User;
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        data-testid="chat-row"
        data-platform={chat.platform}
        data-excluded={chat.excluded}
        className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors ${
          selected ? "bg-indigo-50" : "hover:bg-slate-50"
        }`}
      >
        <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-500">
          <Avatar className="size-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate font-medium">{chat.title}</span>
              {chat.excluded && (
                <span title="Excluded Chat: plan detection is off" data-testid="excluded-chat-mark">
                  <CalendarOff className="size-3.5 shrink-0 text-slate-400" aria-hidden />
                  <span className="sr-only">(Excluded Chat: plan detection off)</span>
                </span>
              )}
            </span>
            <time dateTime={chat.lastMessageAt} className="shrink-0 text-xs text-slate-500">
              {formatChatTime(chat.lastMessageAt)}
            </time>
          </span>
          <span className="mt-0.5 flex items-center justify-between gap-2">
            <span className="truncate text-sm text-slate-600">{preview(chat)}</span>
            <PlatformBadge platform={chat.platform} />
          </span>
        </span>
      </button>
    </li>
  );
}

/** The inbox's Chat list, newest first, each Chat with its Platform badge. */
export function ChatList({ state, selectedId, onSelect, emptyText }: Props) {
  if (state.kind === "loading") {
    return (
      <p className="flex items-center gap-2 p-6 text-sm text-slate-500">
        <LoaderCircle className="size-4 animate-spin" aria-hidden />
        Loading Chats…
      </p>
    );
  }
  if (state.kind === "failed") {
    return <p className="p-6 text-sm text-rose-700">Couldn&apos;t load Chats: {state.error.message}</p>;
  }
  if (state.chats.length === 0) {
    return <p className="p-6 text-center text-sm text-slate-500">{emptyText}</p>;
  }
  return (
    <ul aria-label="Chats" className="divide-y divide-slate-100">
      {state.chats.map((chat) => (
        <ChatRow
          key={chat.id}
          chat={chat}
          selected={chat.id === selectedId}
          onSelect={() => onSelect(chat)}
        />
      ))}
    </ul>
  );
}
