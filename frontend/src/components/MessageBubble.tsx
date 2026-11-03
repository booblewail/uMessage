import { ArrowUpRight } from "lucide-react";
import type { Message } from "@/lib/api";
import { formatMessageTime } from "@/lib/format";

/** One Message; the user's own (an Outbound Message) sits on the right, marked "You". */
export function MessageBubble({ message }: { message: Message }) {
  const { outbound } = message;
  return (
    <li
      data-testid="message"
      data-outbound={outbound}
      className={`flex flex-col gap-1 ${outbound ? "items-end" : "items-start"}`}
    >
      <span className="flex items-center gap-1.5 px-1 text-xs text-slate-500">
        {outbound ? (
          <span className="inline-flex items-center gap-0.5 font-medium text-indigo-700" title="Outbound Message">
            <ArrowUpRight className="size-3" aria-hidden />
            You
            <span className="sr-only">(Outbound Message)</span>
          </span>
        ) : (
          <span className="font-medium text-slate-700">{message.senderName}</span>
        )}
        <time dateTime={message.sentAt}>{formatMessageTime(message.sentAt)}</time>
      </span>
      <p
        className={`max-w-[75%] whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-sm ${
          outbound
            ? "rounded-br-sm bg-indigo-600 text-white"
            : "rounded-bl-sm border border-slate-200 bg-white text-slate-900"
        }`}
      >
        {message.text}
      </p>
    </li>
  );
}
