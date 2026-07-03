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
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
