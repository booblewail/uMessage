"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type AppStatus } from "@/lib/api";

const POLL_INTERVAL_MS = 5000;

export type AppStatusState =
  | { kind: "loading" }
  | { kind: "loaded"; status: AppStatus }
  | { kind: "failed"; error: ApiError };

/** Polls `/api/status`, so the inbox notices Beeper Desktop starting or stopping. */
export function useAppStatus(): AppStatusState {
  const [state, setState] = useState<AppStatusState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const status = await api.status();
        if (!cancelled) setState({ kind: "loaded", status });
      } catch (error) {
        const apiError =
          error instanceof ApiError ? error : new ApiError("http", String(error));
        if (!cancelled) setState({ kind: "failed", error: apiError });
      }
    };
    void load();
    const timer = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return state;
}
