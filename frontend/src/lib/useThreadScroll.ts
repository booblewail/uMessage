"use client";

import { useLayoutEffect, useRef } from "react";
import type { Message } from "@/lib/api";

/** How close to the top (px) scrolling has to get before older Messages load. */
const LOAD_OLDER_WITHIN_PX = 150;
/** How close to the bottom (px) counts as "reading the newest Messages". */
const AT_BOTTOM_WITHIN_PX = 80;

/**
 * Scrolling for a thread: starts at the newest Message, follows new ones while the reader is
 * at the bottom (and always for their own), loads older Messages near the top, and keeps the
 * Messages on screen steady while older ones are added above them.
 */
export function useThreadScroll(messages: Message[], canLoadOlder: boolean, loadOlder: () => void) {
  const scroller = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  // Distance from the bottom to restore once older Messages have been added above.
  const restoreFromBottom = useRef<number | null>(null);
  const oldestId = messages[0]?.id;
  const newest = messages.at(-1);

  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element || restoreFromBottom.current === null) return;
    element.scrollTop = element.scrollHeight - restoreFromBottom.current;
    restoreFromBottom.current = null;
  }, [oldestId]);

  const newestId = newest?.id;
  const newestOutbound = newest?.outbound ?? false;
  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element || newestId === undefined) return;
    if (atBottom.current || newestOutbound) element.scrollTop = element.scrollHeight;
  }, [newestId, newestOutbound]);

  const requestOlder = () => {
    const element = scroller.current;
    if (!element || !canLoadOlder) return;
    restoreFromBottom.current = element.scrollHeight - element.scrollTop;
    loadOlder();
  };

  // Load on scrolling *into* the top zone, so a failed load isn't retried on every scroll event.
  const nearTop = useRef(false);
  const onScroll = () => {
    const element = scroller.current;
    if (!element) return;
    atBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < AT_BOTTOM_WITHIN_PX;
    const wasNearTop = nearTop.current;
    nearTop.current = element.scrollTop < LOAD_OLDER_WITHIN_PX;
    if (nearTop.current && !wasNearTop) requestOlder();
  };

  return { scroller, onScroll, requestOlder };
}
