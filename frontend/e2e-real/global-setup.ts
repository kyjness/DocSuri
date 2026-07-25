import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

// Global setup for the real-stack audit: log in through the real UI as the local smoke account and
// persist the session so every spec starts authenticated (the doc-model route is behind RouteGuard).
// Credentials match tools/local/smoke.py's seeded account (override via env for a different one).
const BASE_URL = 'http://localhost:3000';
const STATE_PATH = './e2e-real/.auth/state.json';
const EMAIL = process.env.SMOKE_EMAIL ?? 'smoke@local.test';
const PASSWORD = process.env.SMOKE_PASSWORD ?? 'SmokeLocal#2026';

export default async function globalSetup() {
  mkdirSync(dirname(STATE_PATH), { recursive: true });
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(`${BASE_URL}/login`);
    await page.getByTestId('login-email').fill(EMAIL);
    await page.getByTestId('login-password').fill(PASSWORD);
    await page.getByTestId('login-submit').click();
    // A successful login navigates away from /login (into the authed app shell). Fail loudly here
    // rather than letting every spec redirect back to login with a cryptic error.
    await page.waitForURL((url) => !url.pathname.endsWith('/login'), { timeout: 20_000 });
    // Warm + verify the session against a GUARDED page before persisting state: RouteGuard's first
    // session check can 401 then recover, so let that settle here (during setup) rather than racing
    // it in every spec. If the guarded viewer never renders, the whole run should fail here, loudly.
    await page.goto(`${BASE_URL}/paper/2402.01809/doc-model?version=1`);
    await page.getByTestId('docmodel-viewer').waitFor({ state: 'visible', timeout: 30_000 });
    // The session cookie is issued `Secure` (correct for the real HTTPS deployment). But this local
    // stack is plain HTTP, and Playwright does NOT replay a Secure cookie over http:// into a
    // restored context — so a live-login context authenticates while a storageState one silently
    // redirects to /login. Clear `secure` on the persisted cookies: harmless on http localhost, and
    // it lets the restored session actually carry. (The app/server are untouched.)
    const state = await page.context().storageState();
    const patched = { ...state, cookies: state.cookies.map((c) => ({ ...c, secure: false })) };
    writeFileSync(STATE_PATH, JSON.stringify(patched));
  } finally {
    await browser.close();
  }
}
