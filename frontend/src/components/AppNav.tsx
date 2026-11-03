"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarDays, Inbox } from "lucide-react";

interface Props {
  /** How many Detected Events are Pending Review (null until known). */
  pendingCount: number | null;
}

const LINK = "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium transition-colors";

/** Links between the inbox and the plans page, with the Pending Review count. */
export function AppNav({ pendingCount }: Props) {
  const path = usePathname();
  const style = (href: string) =>
    `${LINK} ${path === href ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-200"}`;
  return (
    <nav aria-label="uMessage" className="flex items-center gap-1 rounded-full bg-slate-100 p-1">
      <Link href="/inbox" className={style("/inbox")} aria-current={path === "/inbox" ? "page" : undefined}>
        <Inbox className="size-4" aria-hidden />
        Inbox
      </Link>
      <Link
        href="/events"
        className={style("/events")}
        aria-current={path === "/events" ? "page" : undefined}
        data-testid="nav-events"
      >
        <CalendarDays className="size-4" aria-hidden />
        Plans
        {pendingCount !== null && pendingCount > 0 && (
          <span
            data-testid="pending-count"
            title={`${pendingCount} to review`}
            className="min-w-5 rounded-full bg-amber-500 px-1.5 text-center text-xs font-semibold text-white"
          >
            {pendingCount}
          </span>
        )}
      </Link>
    </nav>
  );
}
