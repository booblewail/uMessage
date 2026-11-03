import { ChevronDown, ChevronUp, LoaderCircle } from "lucide-react";
import type { MessagesState } from "@/lib/useMessages";

type Loaded = Extract<MessagesState, { kind: "loaded" }>;

const PILL =
  "inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100";

function Loading({ testId, text }: { testId: string; text: string }) {
  return (
    <p className="my-4 flex items-center justify-center gap-2 text-xs text-slate-500" data-testid={testId}>
      <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
      {text}
    </p>
  );
}

/** Above the Messages: loading older ones, a button to load them, or the start of the Chat. */
export function OlderMessages({ state, onLoad }: { state: Loaded; onLoad: () => void }) {
  if (state.loading === "older") return <Loading testId="loading-older" text="Loading older Messages…" />;
  if (state.olderCursor === null) {
    return state.messages.length > 0 ? (
      <p className="mb-4 text-center text-xs text-slate-400" data-testid="start-of-chat">
        Start of this Chat
      </p>
    ) : null;
  }
  const failed = state.loadError !== null && state.loading === null;
  return (
    <div className="mb-4 flex flex-col items-center gap-1">
      {failed && (
        <p role="alert" className="text-xs text-rose-700">
          Couldn&apos;t load more Messages: {state.loadError}
        </p>
      )}
      <button type="button" onClick={onLoad} data-testid="load-older" className={PILL}>
        <ChevronUp className="size-3.5" aria-hidden />
        {failed ? "Try again" : "Older Messages"}
      </button>
    </div>
  );
}

/** Below the Messages of a thread opened further back: loading newer ones, or a button to. */
export function NewerMessages({ state, onLoad }: { state: Loaded; onLoad: () => void }) {
  if (state.loading === "newer") return <Loading testId="loading-newer" text="Loading newer Messages…" />;
  if (state.newerCursor === null) return null;
  return (
    <div className="mt-4 flex justify-center">
      <button type="button" onClick={onLoad} data-testid="load-newer" className={PILL}>
        <ChevronDown className="size-3.5" aria-hidden />
        Newer Messages
      </button>
    </div>
  );
}
