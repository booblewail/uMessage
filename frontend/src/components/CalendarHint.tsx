import { CalendarCheck2 } from "lucide-react";
import type { CalendarEntryRef } from "@/lib/api";
import { formatEntryWhen } from "@/lib/format";

/** "You already have Dinner at Mum's, Fri 19:30 from this Chat" (its upcoming Calendar Entries). */
export function CalendarHint({ entries }: { entries: CalendarEntryRef[] }) {
  if (entries.length === 0) return null;
  const [first, ...more] = entries;
  return (
    <p data-testid="calendar-hint" className="flex items-start gap-1.5 text-xs text-slate-700">
      <CalendarCheck2 className="mt-px size-3.5 shrink-0 text-emerald-700" aria-hidden />
      <span>
        You already have{" "}
        <em className="font-semibold not-italic">
          {first.title}, {formatEntryWhen(first.start, first.allDay)}
        </em>
        {more.length > 0 && ` and ${more.length} more`} from this Chat
      </span>
    </p>
  );
}
