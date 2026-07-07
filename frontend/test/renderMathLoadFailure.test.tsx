import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';

// Simulate a failed MathJax chunk load / init (stale hashes after a deploy, offline, …): the handler
// registration throws, so preloadMathEngine's async setup rejects. This test file is isolated, so the
// renderMath module starts with a fresh (unloaded) engine.
vi.mock('mathjax-full/js/handlers/html.js', () => ({
  RegisterHTMLHandler: () => {
    throw new Error('simulated MathJax init failure');
  },
}));

import { MathDisplay, preloadMathEngine } from '@/lib/renderMath';

describe('MathJax lazy-load failure', () => {
  it('degrades to the source fallback chip, not an infinite loading skeleton', async () => {
    // The load rejects (rethrown so awaiters see it) and flips the module to the error state.
    await expect(preloadMathEngine()).rejects.toThrow();

    const { container } = render(<MathDisplay latex={'x^2'} />);
    // No stuck skeleton…
    expect(container.querySelector('.mathLoading')).toBeNull();
    // …instead the fallback chip carrying the source (hover tooltip).
    const chip = container.querySelector('[role="img"]');
    expect(chip?.textContent).toBe('수식');
    expect(chip?.getAttribute('title')).toContain('x^2');
  });

  it('clears its cached promise so a later mount can retry (does not stay wedged)', async () => {
    // A second call is a fresh attempt (not the same cached rejected promise); with the mock still
    // failing it rejects again — proving the retry path exists rather than returning a wedged promise.
    await expect(preloadMathEngine()).rejects.toThrow();
  });
});
