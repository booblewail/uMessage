"use client";

import { useState } from "react";
import { api, toApiError, type DetectedEvent } from "@/lib/api";

/**
 * Reviewing one Pending Review Detected Event: Dismiss it, or open the edit dialog to
 * confirm it ("Add to Calendar"). `onChanged` gets it as it is afterwards.
 */
export function useEventActions(event: DetectedEvent, onChanged: (event: DetectedEvent) => void) {
  const [dismissing, setDismissing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dismiss = async () => {
    setDismissing(true);
    setError(null);
    try {
      onChanged(await api.dismissEvent(event.id));
    } catch (failure) {
      setError(toApiError(failure).message);
      setDismissing(false);
    }
  };

  const confirmed = (updated: DetectedEvent) => {
    setEditing(false);
    onChanged(updated);
  };

  return { dismissing, editing, setEditing, error, dismiss: () => void dismiss(), confirmed };
}
