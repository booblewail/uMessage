import { CircleAlert, CloudDownload, Hourglass } from "lucide-react";
import type { FirstImportStatus } from "@/lib/api";

/** First Import's progress; nothing once it has completed. */
export function FirstImportNotice({ firstImport }: { firstImport: FirstImportStatus }) {
  const { state, chatsTotal, chatsImported, error } = firstImport;
  if (state === "completed") return null;

  if (state === "failed") {
    return (
      <div data-testid="first-import" className="flex items-start gap-3 rounded-xl border border-rose-300 bg-rose-50 p-4 text-rose-900">
        <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
        <div>
          <p className="font-medium">First Import didn&apos;t finish</p>
          <p className="text-sm opacity-80">
            {error ?? "Something went wrong."} It runs again the next time uMessage starts.
          </p>
        </div>
      </div>
    );
  }

  if (state === "waiting") {
    return (
      <div data-testid="first-import" className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 text-slate-700">
        <Hourglass className="size-5 shrink-0" aria-hidden />
        <p className="text-sm">First Import of your Chats starts as soon as Beeper Desktop is running.</p>
      </div>
    );
  }

  const percent = chatsTotal ? Math.round((chatsImported / chatsTotal) * 100) : 0;
  return (
    <div data-testid="first-import" className="flex items-center gap-3 rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-indigo-900">
      <CloudDownload className="size-5 shrink-0 animate-pulse" aria-hidden />
      <div className="flex-1">
        <p className="text-sm font-medium">
          Importing your Chats
          {chatsTotal !== null && ` · ${chatsImported} of ${chatsTotal}`}
        </p>
        <div
          role="progressbar"
          aria-label="First Import progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          className="mt-2 h-1.5 overflow-hidden rounded-full bg-indigo-100"
        >
          <div className="h-full bg-indigo-600 transition-all" style={{ width: `${percent}%` }} />
        </div>
      </div>
    </div>
  );
}
