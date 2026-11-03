import { FlaskConical } from "lucide-react";

export function DemoModeBadge() {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full bg-violet-100 px-3 py-1 text-xs font-medium text-violet-800"
      title="Fake adapters: no Beeper, Gemini or Google Calendar credentials are used."
    >
      <FlaskConical className="size-3.5" aria-hidden />
      Demo mode
    </span>
  );
}
