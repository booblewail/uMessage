"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { LoaderCircle, SendHorizontal } from "lucide-react";
import { api, toApiError, type Message } from "@/lib/api";

interface Props {
  chatId: number;
  chatTitle: string;
  /** Called with the stored Outbound Message once Beeper Desktop has sent it. */
  onSent: (message: Message) => void;
}

/** Type and send a reply: Enter sends, Shift+Enter starts a new line. */
export function ReplyBar({ chatId, chatTitle, onSent }: Props) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const canSend = text.trim() !== "" && !sending;

  // Focus the box when the Chat opens and again once a send has finished.
  useEffect(() => {
    if (!sending) input.current?.focus();
  }, [sending]);

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    setError(null);
    try {
      onSent(await api.sendMessage(chatId, text));
      setText("");
    } catch (failure) {
      setError(toApiError(failure).message);
    } finally {
      setSending(false);
    }
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void send();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  };

  return (
    <form onSubmit={onSubmit} className="border-t border-slate-200 bg-white px-4 py-3" aria-label="Reply">
      {error && (
        <p role="alert" data-testid="reply-error" className="mb-2 text-sm text-rose-700">
          Couldn&apos;t send: {error}
        </p>
      )}
      <div className="flex items-end gap-2">
        <textarea
          ref={input}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          disabled={sending}
          rows={1}
          placeholder={`Message ${chatTitle}`}
          aria-label={`Reply to ${chatTitle}`}
          data-testid="reply-input"
          className="max-h-40 min-h-10 flex-1 resize-none rounded-xl border border-slate-300 px-3 py-2 text-sm [field-sizing:content] focus:border-indigo-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-500"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send"
          data-testid="reply-send"
          className="flex size-10 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white hover:bg-indigo-700 disabled:bg-slate-300"
        >
          {sending ? (
            <LoaderCircle className="size-4 animate-spin" aria-hidden />
          ) : (
            <SendHorizontal className="size-4" aria-hidden />
          )}
        </button>
      </div>
    </form>
  );
}
