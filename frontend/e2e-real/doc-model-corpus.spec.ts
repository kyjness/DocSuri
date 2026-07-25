import { test, expect, type Page } from '@playwright/test';

// Real-stack doc-model render audit (u5 render-verification, Part 2). Loads REAL corpus papers
// through the live viewer (real gateway + s3proxy WebP) and checks the things a headless render
// sweep cannot see: the page never scrolls sideways on a phone, figure WebPs actually load, math
// renders as MathJax SVG (not the fallback chip), and the Korean translation view renders. A
// full-page screenshot is archived per paper for visual review.
//
// Curated papers all have COMPLETE asset crops (verified via the paper_asset backfill), so the
// figure-load assertion is meaningful. 2402.01809 is the one re-ingested with the current parser
// (@10); the rest span older parser generations to exercise render resilience.
const PAPERS: { id: string; version: number; note: string }[] = [
  { id: '2402.01809', version: 1, note: 'parser @10 (current), complete assets' },
  { id: '2210.12090', version: 1, note: 'figures + wide tables' },
  { id: '2112.01799', version: 1, note: 'figure-heavy (12)' },
  { id: '2510.23156', version: 2, note: 'v2, balanced figures/tables' },
];

async function pageOverflowsSideways(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
}

for (const paper of PAPERS) {
  test(`doc-model renders on a phone without clipping: ${paper.id} (${paper.note})`, async ({
    page,
  }) => {
    await page.goto(`/paper/${paper.id}/doc-model?version=${paper.version}`);

    // Renders (not stuck on a loader, not redirected to login, not license-gated).
    await expect(page.getByTestId('docmodel-viewer')).toBeVisible({ timeout: 30_000 });

    // The phone-layout failure this guards: the page body must never scroll horizontally. Wide
    // content (tables, display equations) has to scroll inside its own box instead.
    expect(await pageOverflowsSideways(page)).toBe(false);

    // At least one figure WebP actually loads from s3proxy. This is the assertion that catches the
    // CSP img-src gap (a signed URL the browser refuses) and an empty/mis-signed manifest — a curl
    // presign check cannot, since it doesn't enforce CSP. Figures are `loading="lazy"`, so scroll
    // the first one into view to trigger the load before reading its decoded size. Guarded on
    // presence (like the math block below): a table-only paper has no `figure img` and must not fail
    // on a scroll timeout — a blocked/mis-signed URL still leaves the `<img>` in the DOM (naturalWidth
    // 0), so this still fires whenever a figure exists.
    const figures = page.locator('figure img');
    if ((await figures.count()) > 0) {
      const firstFigure = figures.first();
      await firstFigure.scrollIntoViewIfNeeded({ timeout: 20_000 });
      await expect
        .poll(() => firstFigure.evaluate((el: HTMLImageElement) => el.naturalWidth), {
          timeout: 20_000,
        })
        .toBeGreaterThan(0);
    }

    // Math: once the lazy MathJax engine has resolved, a display equation becomes inline SVG. Only
    // some papers carry display formulas, so assert conditionally — if this paper has any, the first
    // must render as SVG (confirms the engine loaded and the LaTeX didn't collapse to the chip).
    const formulaBlocks = page.locator('[class*="formulaInner"]');
    if ((await formulaBlocks.count()) > 0) {
      await expect(formulaBlocks.first().locator('svg')).toBeVisible({ timeout: 30_000 });
    }

    // Still no sideways scroll after figures + math have laid out (a too-wide SVG/table that escaped
    // its box would trip this now even if it passed before the async content landed).
    expect(await pageOverflowsSideways(page)).toBe(false);

    await page.screenshot({ path: test.info().outputPath(`${paper.id}-doc-model.png`) });
  });
}

test('Korean translation view renders the structured body: 2402.01809', async ({ page }) => {
  await page.goto('/paper/2402.01809/translate?version=1');
  // The translated view reuses the same rich viewer (DocModelBody), so the same structure renders —
  // only the text differs (Korean). Confirms the translation read path + Korean layout.
  await expect(page.getByTestId('docmodel-viewer')).toBeVisible({ timeout: 30_000 });
  expect(await pageOverflowsSideways(page)).toBe(false);
  await page.screenshot({ path: test.info().outputPath('2402.01809-translate.png') });
});
