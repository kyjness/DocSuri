import { defineConfig, devices } from '@playwright/test';

/**
 * Real-stack E2E config (u5 render-verification, Part 2) — distinct from the mock-first
 * `playwright.config.ts`. This one drives the app against the RUNNING local stack (Next.js dev
 * on :3000 in real mode via `.env.local`, U6 gateway on :8000, s3proxy for WebP), so the specs
 * see REAL corpus doc-models, real signed WebP figures, and the real Korean translation path —
 * the things the headless math sweep cannot see (table overflow, WebP load, layout).
 *
 * Prereq: the local stack is up (`./dev.sh`). A global setup logs in as the smoke account and
 * saves a storage state, so every spec starts authenticated (the doc-model route is guarded).
 *
 * Run: `pnpm run e2e:real` (or `pnpm exec playwright test -c playwright.real.config.ts`).
 */
export default defineConfig({
  testDir: './e2e-real',
  globalSetup: './e2e-real/global-setup.ts',
  // One worker: the specs read the shared local stack; keep load predictable and screenshots ordered.
  workers: 1,
  use: {
    baseURL: 'http://localhost:3000',
    ...devices['iPhone 13'],
    storageState: './e2e-real/.auth/state.json',
    screenshot: 'only-on-failure',
  },
  webServer: {
    // Start the dev server the way `./dev.sh` does: source the ROOT `.env` first, THEN `pnpm dev`.
    // That `.env` carries AWS_ENDPOINT_URL_S3 (the s3proxy origin) — without it the CSP middleware
    // omits the local asset origin from img-src and every figure WebP is blocked in the browser
    // (the frontend's own `.env.local` only sets the gateway/real-API flags). `pnpm dev` still reads
    // `.env.local` for the real-transport switch. reuseExistingServer lets a `./dev.sh` stack (which
    // already sourced `.env`) be reused; otherwise this starts a correctly-provisioned one.
    command: 'bash -c "set -a; [ -f ../.env ] && . ../.env; set +a; exec pnpm run dev"',
    url: 'http://localhost:3000',
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
