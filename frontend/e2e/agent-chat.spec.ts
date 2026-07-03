import { test, expect } from '@playwright/test';

test('authenticated user opens agent tab and sends a novelty message', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem(
      'docsuri-mock-session',
      JSON.stringify({
        userId: 'user_agent_e2e',
        expiresAt: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
      }),
    );
  });
  await page.goto('/agent');

  await expect(page.getByTestId('agent-chat-screen')).toBeVisible();

  await page.getByTestId('agent-mode-novelty').click();
  await page.getByTestId('agent-composer-input').fill('RAG 평가 자동화 아이디어');
  await page.getByTestId('agent-composer-submit').click();

  await expect(page.getByText(/차별점은 데이터셋 조건/)).toBeVisible();
  await expect(page.getByTestId('agent-timeline')).toBeVisible();
});
