import type { Platform } from "@/lib/api";
import { PLATFORM_LOOKS } from "@/lib/platforms";

export function PlatformBadge({ platform }: { platform: Platform }) {
  const { label, Icon, badge } = PLATFORM_LOOKS[platform];
  return (
    <span
      data-testid="platform-badge"
      data-platform={platform}
      className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${badge}`}
    >
      <Icon className="size-3" aria-hidden />
      {label}
    </span>
  );
}
