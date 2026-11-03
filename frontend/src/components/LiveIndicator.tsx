import { Radio, WifiOff } from "lucide-react";

/** Whether new Messages are arriving live, or the inbox is reconnecting to the backend. */
export function LiveIndicator({ live }: { live: boolean }) {
  return live ? (
    <span
      data-testid="live-indicator"
      data-live="true"
      className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"
    >
      <Radio className="size-3.5" aria-hidden />
      Live
    </span>
  ) : (
    <span
      data-testid="live-indicator"
      data-live="false"
      title="New Messages show up once the inbox has reconnected"
      className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600"
    >
      <WifiOff className="size-3.5" aria-hidden />
      Reconnecting…
    </span>
  );
}
