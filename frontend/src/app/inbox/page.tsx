import { Suspense } from "react";
import type { Metadata } from "next";
import { InboxView } from "@/components/InboxView";

export const metadata: Metadata = { title: "Inbox · uMessage" };

export default function InboxPage() {
  // The open Chat comes from the URL's search params, which are only known at request time.
  return (
    <Suspense>
      <InboxView />
    </Suspense>
  );
}
