import { test, expect } from '@playwright/test';

// Paper-detail layout on a phone (NFR-U1), against the mock-first app. Needs real layout, so it
// lives here rather than in vitest (jsdom computes no geometry).
//
// The metadata header renders the source's own text. An abstract ending in a code URL is an
// unbreakable run wider than the phone; unwrapped, it widened the whole page, and a phone browser
// then lays the fixed 요약 / 초록 번역 / 각주 트리 modals out against that wider page — all three
// slid off screen on that paper only.

test('an abstract with a long URL wraps instead of widening the page', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('hero-cta-signup').click();
  await page.getByTestId('signup-email').fill('demo@docsuri.dev');
  await page.getByTestId('signup-password').fill('demo-password-123');
  await page.getByTestId('signup-submit').click();
  await page.getByTestId('login-email').fill('demo@docsuri.dev');
  await page.getByTestId('login-password').fill('demo-password-123');
  await page.getByTestId('login-submit').click();
  await expect(page.getByTestId('search-input')).toBeVisible();

  await page.goto('/paper/2103.00112v3');
  const abstract = page.getByTestId('paper-abstract');
  await expect(abstract).toContainText('gitee.com/mindspore');

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBe(clientWidth);
});
