"use client";

import { useLayoutEffect, useRef } from "react";
import type { Message } from "@/lib/api";

/** How close to the top or bottom (px) scrolling has to get before more Messages load. */
const LOAD_MORE_WITHIN_PX = 150;
/** How close to the bottom (px) counts as "reading the newest Messages". */
const AT_BOTTOM_WITHIN_PX = 80;

interface Options {
  canLoadOlder: boolean;
  loadOlder: () => void;
  /** Whether newer Messages than the loaded ones are waiting (opened at an older Message). */
  canLoadNewer: boolean;
  loadNewer: () => void;
  /** The Message to open at, centred (an Anchor Message a link jumps to). */
  highlightId: number | null;
}

/**
 * Scrolling for a thread: starts at the newest Message (or centred on `highlightId`), follows
 * new ones while the reader is at the bottom of an up-to-date thread (and always for their
 * own), loads older Messages near the top and newer ones near the bottom, and keeps the
 * Messages on screen steady while older ones are added above them.
 */
export function useThreadScroll(messages: Message[], options: Options) {
  const { canLoadOlder, loadOlder, canLoadNewer, loadNewer, highlightId } = options;
  const scroller = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  // Distance from the bottom to restore once older Messages have been added above.
  const restoreFromBottom = useRef<number | null>(null);
  const jumped = useRef(highlightId === null);
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
    if (!element || newestId === undefined || !jumped.current) return;
    if ((atBottom.current && !canLoadNewer) || newestOutbound) element.scrollTop = element.scrollHeight;
  }, [newestId, newestOutbound, canLoadNewer]);

  // Once the page around the highlighted Message is shown, centre it.
  const hasMessages = messages.length > 0;
  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element || !hasMessages || jumped.current) return;
    jumped.current = true;
    const target = element.querySelector(`[data-message-id="${highlightId}"]`);
    if (!target) {
      element.scrollTop = element.scrollHeight;
      return;
    }
    // Scroll the thread only (scrollIntoView would scroll the whole page too).
    const box = target.getBoundingClientRect();
    const view = element.getBoundingClientRect();
    element.scrollTop += box.top - view.top - (element.clientHeight - box.height) / 2;
  }, [hasMessages, highlightId]);

  const requestOlder = () => {
    const element = scroller.current;
    if (!element || !canLoadOlder) return;
    restoreFromBottom.current = element.scrollHeight - element.scrollTop;
    loadOlder();
  };

  // Load on scrolling *into* the top or bottom zone, so a failed load isn't retried on every
  // scroll event.
  const nearTop = useRef(false);
  const nearBottom = useRef(false);
  const onScroll = () => {
    const element = scroller.current;
    if (!element) return;
    const fromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    atBottom.current = fromBottom < AT_BOTTOM_WITHIN_PX;
    const wasNearTop = nearTop.current;
    nearTop.current = element.scrollTop < LOAD_MORE_WITHIN_PX;
    if (nearTop.current && !wasNearTop) requestOlder();
    const wasNearBottom = nearBottom.current;
    nearBottom.current = fromBottom < LOAD_MORE_WITHIN_PX;
    if (nearBottom.current && !wasNearBottom && canLoadNewer) loadNewer();
  };

  return { scroller, onScroll, requestOlder };
}
