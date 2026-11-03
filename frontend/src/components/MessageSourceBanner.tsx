import { CircleCheck, KeyRound, LoaderCircle, MonitorOff, ServerCrash } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { API_URL } from "@/lib/api";
import type { AppStatusState } from "@/lib/useAppStatus";

type Tone = "neutral" | "good" | "warning" | "bad";

interface BannerContent {
  tone: Tone;
  Icon: LucideIcon;
  title: string;
  detail: string;
  spin?: boolean;
}

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "border-slate-200 bg-white text-slate-700",
  good: "border-emerald-200 bg-emerald-50 text-emerald-900",
  warning: "border-amber-300 bg-amber-50 text-amber-900",
  bad: "border-rose-300 bg-rose-50 text-rose-900",
};

function describe(state: AppStatusState): BannerContent {
  if (state.kind === "loading") {
    return {
      tone: "neutral",
      Icon: LoaderCircle,
      title: "Checking Beeper Desktop…",
      detail: "Asking the uMessage backend whether Beeper Desktop is running.",
      spin: true,
    };
  }
  if (state.kind === "failed") {
    if (state.error.kind === "unauthorized") {
      return {
        tone: "bad",
        Icon: KeyRound,
        title: "The backend rejected the API token",
        detail: "Make NEXT_PUBLIC_API_TOKEN (or API_TOKEN) in .env match the backend's API_TOKEN.",
      };
    }
    return {
      tone: "bad",
      Icon: ServerCrash,
      title: "Can't reach the uMessage backend",
      detail: `Nothing answered at ${API_URL}. Is \`make dev\` running?`,
    };
  }
  const { name, running } = state.status.messageSource;
  if (running) {
    return {
      tone: "good",
      Icon: CircleCheck,
      title: `${name} is running`,
      detail: "uMessage can read your Chats through it.",
    };
  }
  return {
    tone: "warning",
    Icon: MonitorOff,
    title: `${name} isn't running`,
    detail: `Open ${name} on this Mac. uMessage picks up your Chats as soon as it's running.`,
  };
}

export function MessageSourceBanner({ state }: { state: AppStatusState }) {
  const { tone, Icon, title, detail, spin } = describe(state);
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="message-source-status"
      className={`flex items-start gap-3 rounded-xl border p-4 ${TONE_CLASSES[tone]}`}
    >
      <Icon className={`mt-0.5 size-5 shrink-0 ${spin ? "animate-spin" : ""}`} aria-hidden />
      <div>
        <p className="font-medium">{title}</p>
        <p className="text-sm opacity-80">{detail}</p>
      </div>
    </div>
  );
}
