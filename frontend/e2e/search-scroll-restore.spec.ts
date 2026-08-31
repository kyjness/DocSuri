import { test, expect, type Page } from '@playwright/test';

// 뒤로가기가 보던 자리로 돌아오는가 (US-H1/D1) — mock-first 앱, 백엔드 불필요.
//
// **유닛 테스트로는 안 잡힌다.** 복원은 라우터의 이동 후 맨-위 스크롤·브라우저의 자체 복원과
// **경합**하고, jsdom에는 그 둘이 없다. 실제로 배포본에서 "빨리 돌아오면 되는데 좀 있다가
// 누르면 맨 위로" 라는 모양으로 났다 — 결과 목록은 살아 있었으니 스냅샷이 아니라 타이밍이다.
// 그래서 상세 페이지에 **머무는 시간**을 변수로 둔 케이스를 함께 둔다.

// 목 데이터의 결과 목록은 짧다(스크롤 여지 약 540px). 그 안에서 충분히 떨어진 지점을 쓴다 —
// 목표를 여지보다 크게 잡으면 브라우저가 최대치로 깎아 '복원됨'이 우연히 성립한다.
const SCROLL_TO = 400;

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

/** 목록이 스크롤될 만큼 긴지 확인하고 내려간다. 짧으면 이 검사는 아무것도 증명하지 못한다. */
async function scrollDown(page: Page): Promise<number> {
  const max = await page.evaluate(
    () => document.documentElement.scrollHeight - window.innerHeight,
  );
  expect(max, '결과 목록이 스크롤될 만큼 길어야 검사가 성립한다').toBeGreaterThan(SCROLL_TO);
  await page.evaluate((y) => window.scrollTo(0, y), SCROLL_TO);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(SCROLL_TO);
  return SCROLL_TO;
}

/** 지금 위치에서 **화면에 보이는** 카드를 누른다.
 *
 * 첫 카드를 누르면 Playwright가 클릭 전에 그 요소를 화면 안으로 자동 스크롤한다 — 목록
 * 맨 위로 올라간 뒤 클릭되므로 "보던 자리"가 애초에 0이 되어, 검사가 복원이 아니라
 * 자동 스크롤을 재고 있게 된다(처음에 그렇게 짜서 통과/실패가 뒤집혔다). */
async function clickVisibleCard(page: Page) {
  const card = page.getByTestId('result-card-title').last();
  const box = await card.boundingBox();
  const viewport = await page.evaluate(() => window.innerHeight);
  expect(box, '카드의 위치를 읽을 수 있어야 한다').not.toBeNull();
  expect(box!.y, '누를 카드가 이미 보여야 자동 스크롤이 안 끼어든다').toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport);
  await card.click();
}

async function openFirstCardAndReturn(page: Page, dwellMs: number) {
  await clickVisibleCard(page);
  await expect(page.getByTestId('app-header-back')).toBeVisible();
  if (dwellMs > 0) await page.waitForTimeout(dwellMs);
  await page.getByTestId('app-header-back').click();
  await expect(page.getByTestId('result-list')).toBeVisible();
}

// 상세 페이지에 머문 시간이 짧을 때와 길 때 — 배포본에서 갈렸던 그 축.
for (const dwellMs of [0, 3000]) {
  test(`← 로 돌아오면 보던 자리다 (상세에 ${dwellMs}ms 머문 뒤)`, async ({ page }) => {
    await loginAndSearch(page);
    const at = await scrollDown(page);

    await openFirstCardAndReturn(page, dwellMs);

    // 복원은 몇 프레임에 걸쳐 자리를 잡을 수 있으므로 폴링으로 본다. 라우터가 맨 위로
    // 보낸 뒤 우리가 되돌리는 경합이라, 한 시점만 찍으면 어느 쪽이든 우연히 통과한다.
    await expect
      .poll(() => page.evaluate(() => window.scrollY), { timeout: 3000 })
      .toBeGreaterThan(at - 50);
  });
}

test('브라우저 뒤로가기로도 보던 자리다', async ({ page }) => {
  await loginAndSearch(page);
  const at = await scrollDown(page);

  await clickVisibleCard(page);
  await expect(page.getByTestId('app-header-back')).toBeVisible();
  await page.goBack();
  await expect(page.getByTestId('result-list')).toBeVisible();

  await expect
    .poll(() => page.evaluate(() => window.scrollY), { timeout: 3000 })
    .toBeGreaterThan(at - 50);
});

test('✕ 로 검색을 지우면 다음 진입은 맨 위에서 시작한다', async ({ page }) => {
  await loginAndSearch(page);
  await scrollDown(page);
  await page.getByTestId('search-clear').click();
  await expect(page.getByTestId('result-list')).toHaveCount(0);

  await page.goto('/search');
  await expect(page.getByTestId('search-input')).toHaveValue('');
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
});
