import type { Metadata } from "next";
import { InboxView } from "@/components/InboxView";

export const metadata: Metadata = { title: "Inbox · uMessage" };

export default function InboxPage() {
  return <InboxView />;
}
