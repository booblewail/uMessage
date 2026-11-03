"use client";

import { useEffect, useState } from "react";
import { api, toApiError, type ApiError, type AppStatus } from "@/lib/api";

const POLL_INTERVAL_MS = 5000;
/** Faster while First Import runs, so its progress (and the Chats it adds) show promptly. */
const IMPORT_POLL_INTERVAL_MS = 1000;

export type AppStatusState =
  | { kind: "loading" }
  | { kind: "loaded"; status: AppStatus }
  | { kind: "failed"; error: ApiError };

/** Polls `/api/status`, so the inbox notices Beeper Desktop starting or stopping. */
export function useAppStatus(): AppStatusState {
  const [state, setState] = useState<AppStatusState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      let interval = POLL_INTERVAL_MS;
      try {
        const status = await api.status();
        if (status.firstImport.state === "running") interval = IMPORT_POLL_INTERVAL_MS;
        if (!cancelled) setState({ kind: "loaded", status });
      } catch (error) {
        if (!cancelled) setState({ kind: "failed", error: toApiError(error) });
      }
      if (!cancelled) timer = setTimeout(load, interval);
    };
    void load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return state;
}
