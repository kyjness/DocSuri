import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { ScrollToTopButton } from '@/components/ScrollToTopButton';

// The button is portalled to <body> and pinned with `position: fixed` (so it sticks while the
// content scrolls); its corner offsets are computed from the phone-frame rect. These tests lock
// the positioning math: it hugs the frame's bottom-right on desktop and clamps to the viewport
// corner on full-bleed mobile (frame taller than the screen).

function mockFrame(rect: Partial<DOMRect>): HTMLElement {
  const frame = document.createElement('div');
  frame.setAttribute('data-testid', 'phone-mockup-frame');
  frame.getBoundingClientRect = () => rect as DOMRect;
  document.body.appendChild(frame);
  return frame;
}

function setViewport(width: number, height: number): void {
  Object.defineProperty(window, 'innerWidth', { value: width, configurable: true });
  Object.defineProperty(window, 'innerHeight', { value: height, configurable: true });
}

afterEach(() => {
  cleanup();
  document.querySelector('[data-testid="phone-mockup-frame"]')?.remove();
});

describe('ScrollToTopButton', () => {
  it('pins to the phone-frame bottom-right corner on desktop', () => {
    // 412px frame centred in a 1280×800 window with 24px stage padding (bottom at 776).
    mockFrame({ right: 846, bottom: 776, left: 434, top: 24, width: 412, height: 752 });
    setViewport(1280, 800);
    render(<ScrollToTopButton />);
    const btn = document.querySelector<HTMLElement>('button[aria-label="맨 위로"]')!;
    expect(btn.style.right).toBe('450px'); // 1280 - 846 + 16
    expect(btn.style.bottom).toBe('40px'); // 800 - 776 + 16
  });

  it('clamps to the viewport corner on full-bleed mobile (frame taller than the screen)', () => {
    mockFrame({ right: 390, bottom: 2000, left: 0, top: 0, width: 390, height: 2000 });
    setViewport(390, 844);
    render(<ScrollToTopButton />);
    const btn = document.querySelector<HTMLElement>('button[aria-label="맨 위로"]')!;
    expect(btn.style.right).toBe('16px'); // max(16, 390 - 390 + 16)
    expect(btn.style.bottom).toBe('16px'); // max(16, 844 - 2000 + 16) -> clamped
  });
});
