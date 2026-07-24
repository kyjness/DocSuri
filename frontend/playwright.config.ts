import { defineConfig, devices } from '@playwright/test';

/**
 * E2E config — phone-first viewport (NFR-U1). Drives the mock-first app
 * (MockTransport), so no backend/gateway is required.
 */
export default defineConfig({
  testDir: './e2e',
  use: {
    baseURL: 'http://localhost:3000',
    ...devices['iPhone 13'],
  },
  webServer: {
    command:
      'corepack pnpm@9.15.9 build && node scripts/prepare-standalone-assets.mjs && node .next/standalone/server.js',
    url: 'http://localhost:3000',
    // Hold the app to the mock transport this suite is written against. Without it a developer's
    // .env.local — the solo-local one points the app at a gateway on :8000 — is read by the build
    // below, and every spec fails against a backend the suite never promised to start. Empty
    // beats absent here: an explicit value takes precedence over .env files, where unsetting
    // would just let .env.local win. Kept in the config, not the npm script, so it holds however
    // playwright is invoked.
    env: {
      NEXT_PUBLIC_DOCSURI_REAL_API: '',
      DOCSURI_GATEWAY_URL: '',
    },
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
