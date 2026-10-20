import { test, expect, type Page } from '@playwright/test';

// 헤더의 ← 가 실제 뒤로가기처럼 동작하는가 (LC-1) — mock-first 앱, 백엔드 불필요.
//
// ← 가 고정된 부모 화면으로 '새로 이동'하던 때는 누를 때마다 방문 기록이 하나씩 쌓였다.
// 검색 → A → ← → B → ← 뒤의 기록은 [검색, A, 검색, B, 검색]이 되고, 폰의 뒤로가기 제스처가
// 그 기록을 거슬러 오르며 앞서 열었던 논문을 차례로 다시 보여 줬다. 그래서 화면이 아니라
// **← 를 누른 뒤 브라우저 뒤로가기가 어디로 가는지**를 본다.

async function loginAndSearch(page: Page) {
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
  await expect(page.getByTestId('result-list')).toBeVisible();
}

async function openCard(page: Page, index: number): Promise<string> {
  await page.getByTestId('result-card-title').nth(index).click();
  await expect(page).toHaveURL(/\/paper\/[^/]+$/);
  await expect(page.getByTestId('app-header-back')).toBeVisible();
  return new URL(page.url()).pathname;
}

async function tapBack(page: Page) {
  await page.getByTestId('app-header-back').click();
}

test('← 로 돌아온 뒤 열었던 논문은 브라우저 뒤로가기에 다시 나타나지 않는다', async ({ page }) => {
  await loginAndSearch(page);

  const first = await openCard(page, 0);
  await tapBack(page);
  await expect(page).toHaveURL(/\/search/);

  const second = await openCard(page, 1);
  expect(second, '서로 다른 두 논문을 열어야 검사가 성립한다').not.toBe(first);
  await tapBack(page);
  await expect(page).toHaveURL(/\/search/);

  // 검색 화면에서 한 번 더 뒤로 가면 검색 이전(로그인 흐름)으로 나가야 한다. 기록이 쌓였다면
  // 여기서 두 번째 논문이, 그다음엔 첫 번째 논문이 나온다.
  await page.goBack();
  const path = new URL(page.url()).pathname;
  expect(path).not.toBe(second);
  expect(path).not.toBe(first);
});

test('전문 번역 → ← → 상세 → ← → 검색 결과, 그리고 그 기록만 남는다', async ({ page }) => {
  await loginAndSearch(page);
  const detail = await openCard(page, 0);

  await page.getByTestId('open-full-translation').click();
  await expect(page).toHaveURL(/\/translate/);

  await tapBack(page);
  await expect(page).toHaveURL(new RegExp(`${detail}$`));
  await tapBack(page);
  await expect(page).toHaveURL(/\/search/);
  await expect(page.getByTestId('result-list')).toBeVisible();

  // 앞으로 가기에는 지나온 상세가 남아 있어야 한다 — 새로 쌓은 게 아니라 되돌아왔다는 뜻이다.
  await page.goForward();
  await expect(page).toHaveURL(new RegExp(`${detail}$`));
});

test('링크로 바로 들어온 상세에서 ← 는 사이트를 떠나지 않고 검색으로 간다', async ({ page }) => {
  await loginAndSearch(page);
  // 새 문서로 연다(전체 로드) — 이 문서 안에서는 상세 뒤에 앱 화면이 없다.
  await page.goto('/paper/1706.03762v5');
  await expect(page.getByTestId('app-header-back')).toBeVisible();

  await tapBack(page);
  await expect(page).toHaveURL(/\/search/);
});
