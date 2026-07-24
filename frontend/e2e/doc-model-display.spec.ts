import { test, expect, type Page } from '@playwright/test';

// Doc-model display correctness on a phone (NFR-U1), against the mock-first app.
//
// These assertions need real layout, so no unit test can stand in for them: vitest runs in jsdom,
// which computes no geometry and applies no CSS modules, so scrollWidth/clientWidth are always 0
// there. The viewer's unit suite covers behaviour (what renders, what the anchor jumps to); this
// covers whether wide content stays readable rather than being clipped or crushed.
//
// The fixtures are deliberately wider than the viewport (a 6-column table, a multi-head attention
// equation) because that is the case worth guarding — real papers routinely exceed a phone.

async function openBody(page: Page) {
  await page.goto('/');
  await page.getByTestId('hero-cta-signup').click();
  await page.getByTestId('signup-email').fill('demo@docsuri.dev');
  await page.getByTestId('signup-password').fill('demo-password-123');
  await page.getByTestId('signup-submit').click();
  await page.getByTestId('login-email').fill('demo@docsuri.dev');
  await page.getByTestId('login-password').fill('demo-password-123');
  await page.getByTestId('login-submit').click();
  await page.getByTestId('search-input').fill('transformer attention');
  await page.getByTestId('search-submit').click();
  await page.getByTestId('result-card').first().click();
  await page.goto('/paper/2401.00001/doc-model?version=1');
  await expect(page.getByTestId('docmodel-toc')).toBeVisible();
}

test('a table wider than the phone scrolls inside its own box, not the page', async ({ page }) => {
  await openBody(page);
  const wrap = page.locator('[class*="tableWrap"]').first();
  await expect(wrap).toBeVisible();

  // The wide table overflows its container and that container — not the page — takes the scroll.
  const { scrollWidth, clientWidth } = await wrap.evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }));
  expect(scrollWidth).toBeGreaterThan(clientWidth);

  // The page body must never scroll sideways — that is the phone-layout failure this guards.
  const bodyOverflows = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(bodyOverflows).toBe(false);
});

test('a display equation wider than the phone scrolls at full size, not scaled down', async ({
  page,
}) => {
  await openBody(page);
  const formula = page.locator('[class*="formulaInner"]').first();
  await expect(formula).toBeVisible();
  // MathJax renders lazily; wait for the SVG rather than a fixed timeout.
  const svg = formula.locator('svg').first();
  await expect(svg).toBeVisible();

  const m = await formula.evaluate((el) => {
    const s = el.querySelector('svg') as SVGElement | null;
    const rendered = s ? s.getBoundingClientRect().width : 0;
    // Natural width = what the equation wants before any max-width clamp.
    let natural = rendered;
    if (s) {
      const prev = s.style.maxWidth;
      s.style.maxWidth = 'none';
      natural = s.getBoundingClientRect().width;
      s.style.maxWidth = prev;
    }
    return { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth, rendered, natural };
  });

  // The equation is genuinely too wide for the viewport — otherwise this test proves nothing.
  expect(m.natural).toBeGreaterThan(m.clientWidth);

  // It must keep its size and let the box scroll. MathJax's global `max-width: 100%` (which stops
  // a long INLINE expression from pushing the page sideways) used to win here instead, scaling the
  // equation to fit: 834px rendered at 332px, 40% of natural size, glyphs near 6px. Scaling to fit
  // is the failure mode, so assert the size survived rather than accepting either outcome.
  expect(m.rendered).toBeGreaterThan(m.clientWidth);
  expect(m.scrollWidth).toBeGreaterThan(m.clientWidth);

  const bodyOverflows = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(bodyOverflows).toBe(false);
});
