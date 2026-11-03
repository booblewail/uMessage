import { Layers } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { PLATFORMS, type Platform } from "@/lib/api";
import { PLATFORM_LOOKS } from "@/lib/platforms";

interface Props {
  selected: Platform | null;
  onSelect: (platform: Platform | null) => void;
}

function Pill(props: {
  label: string;
  Icon: LucideIcon;
  pressed: boolean;
  selectedClasses: string;
  onClick: () => void;
}) {
  const { label, Icon, pressed, selectedClasses, onClick } = props;
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium transition-colors ${
        pressed
          ? selectedClasses
          : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-100"
      }`}
    >
      <Icon className="size-3.5" aria-hidden />
      {label}
    </button>
  );
}

/** Filter pills that narrow the Chat list to one Platform (or show them all). */
export function PlatformFilter({ selected, onSelect }: Props) {
  return (
    <div role="group" aria-label="Filter Chats by Platform" className="flex flex-wrap gap-2">
      <Pill
        label="All"
        Icon={Layers}
        pressed={selected === null}
        selectedClasses="border-slate-800 bg-slate-800 text-white"
        onClick={() => onSelect(null)}
      />
      {PLATFORMS.map((platform) => {
        const { label, Icon, selected: selectedClasses } = PLATFORM_LOOKS[platform];
        return (
          <Pill
            key={platform}
            label={label}
            Icon={Icon}
            pressed={selected === platform}
            selectedClasses={selectedClasses}
            onClick={() => onSelect(platform)}
          />
        );
      })}
    </div>
  );
}
