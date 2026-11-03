import { CalendarOff, TriangleAlert } from "lucide-react";
import type { PlanDetectionStatus } from "@/lib/api";

/** Says when plan detection is off (no Gemini API key) or its last check failed. */
export function PlanDetectionNotice({ planDetection }: { planDetection: PlanDetectionStatus }) {
  const { enabled, reason, lastError } = planDetection;
  if (enabled && !lastError) return null;
  const Icon = enabled ? TriangleAlert : CalendarOff;
  return (
    <p
      role="status"
      data-testid="plan-detection-notice"
      className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600"
    >
      <Icon className="size-4 shrink-0 text-slate-400" aria-hidden />
      {enabled ? `The last check for plans failed: ${lastError}` : reason}
    </p>
  );
}
