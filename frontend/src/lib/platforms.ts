import { Camera, Gamepad2, MessageCircle, MessagesSquare, Phone } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Platform } from "@/lib/api";

export interface PlatformLook {
  label: string;
  Icon: LucideIcon;
  /** Badge colours (background + text). */
  badge: string;
  /** Filter pill colours when the pill is selected. */
  selected: string;
}

export const PLATFORM_LOOKS: Record<Platform, PlatformLook> = {
  imessage: {
    label: "iMessage",
    Icon: MessageCircle,
    badge: "bg-sky-100 text-sky-800",
    selected: "border-sky-600 bg-sky-600 text-white",
  },
  instagram: {
    label: "Instagram",
    Icon: Camera,
    badge: "bg-pink-100 text-pink-800",
    selected: "border-pink-600 bg-pink-600 text-white",
  },
  messenger: {
    label: "Messenger",
    Icon: MessagesSquare,
    badge: "bg-blue-100 text-blue-800",
    selected: "border-blue-600 bg-blue-600 text-white",
  },
  whatsapp: {
    label: "WhatsApp",
    Icon: Phone,
    badge: "bg-emerald-100 text-emerald-800",
    selected: "border-emerald-600 bg-emerald-600 text-white",
  },
  discord: {
    label: "Discord",
    Icon: Gamepad2,
    badge: "bg-indigo-100 text-indigo-800",
    selected: "border-indigo-600 bg-indigo-600 text-white",
  },
};
