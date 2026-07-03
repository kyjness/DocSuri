'use client';

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import styles from './ScrollToTopButton.module.css';

// "맨 위로" button for the long reading surfaces (본문 / 본문 번역).
//
// Portalled to <body> so its `position: fixed` resolves against the real viewport — inside the
// reading tree it would be trapped by the phone-frame's `contain: layout` containing block and
// scroll away with the content. It is anchored to the bottom-right of the phone frame on
// desktop (and the viewport bottom-right on full-bleed mobile, via the clamp), and stays put
// while the content scrolls. The active scroller is learned from capture-phase scroll events
// (scroll doesn't bubble), so it works whichever element actually scrolls.
const SHOW_AFTER_PX = 280;
const EDGE = 16;

export function ScrollToTopButton() {
  const scrollerRef = useRef<HTMLElement | null>(null);
  const [visible, setVisible] = useState(false);
  const [pos, setPos] = useState({ right: EDGE, bottom: EDGE });

  // Pin to the phone frame's bottom-right corner (clamped to the viewport for full-bleed mobile,
  // where the frame is taller than the screen). Recompute on viewport / frame resize.
  useEffect(() => {
    const frame = document.querySelector<HTMLElement>('[data-testid="phone-mockup-frame"]');
    if (!frame) return;
    const place = () => {
      const r = frame.getBoundingClientRect();
      setPos({
        right: Math.max(EDGE, window.innerWidth - r.right + EDGE),
        bottom: Math.max(EDGE, window.innerHeight - r.bottom + EDGE),
      });
    };
    place();
    window.addEventListener('resize', place);
    const ro = new ResizeObserver(place);
    ro.observe(frame);
    return () => {
      window.removeEventListener('resize', place);
      ro.disconnect();
    };
  }, []);

  // Reveal once any container scrolls past the threshold.
  useEffect(() => {
    const onScroll = (e: Event) => {
      const target = e.target;
      const scroller =
        target instanceof HTMLElement ? target : (document.scrollingElement as HTMLElement | null);
      if (!scroller) return;
      scrollerRef.current = scroller;
      setVisible(scroller.scrollTop > SHOW_AFTER_PX);
    };
    document.addEventListener('scroll', onScroll, { capture: true, passive: true });
    return () => document.removeEventListener('scroll', onScroll, { capture: true });
  }, []);

  if (typeof document === 'undefined') return null;
  return createPortal(
    <button
      type="button"
      className={visible ? `${styles.btn} ${styles.visible}` : styles.btn}
      style={{ right: pos.right, bottom: pos.bottom }}
      onClick={() => scrollerRef.current?.scrollTo({ top: 0, behavior: 'smooth' })}
      aria-label="맨 위로"
      aria-hidden={!visible}
      tabIndex={visible ? 0 : -1}
      data-testid="scroll-to-top"
    >
      ↑
    </button>,
    document.body,
  );
}
