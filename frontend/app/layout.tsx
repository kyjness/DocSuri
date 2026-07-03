import type { Metadata, Viewport } from 'next';
import { headers } from 'next/headers';
import './globals.css';
import { SessionProvider } from '@/components/session/SessionContext';
import { ThemeProvider } from '@/components/theme/ThemeContext';
import { SavedLibraryProvider } from '@/lib/library/savedLibrary';
import { PhoneMockupFrame } from '@/components/PhoneMockupFrame';
import { ViewModePreview } from '@/components/ViewModePreview';
import { THEME_INIT_SCRIPT } from '@/lib/theme';

// AppShell (LC-1) — SSR root layout: phone-mockup frame + session context.
// stateless server (P-SC1); session lives in the httpOnly cookie.

export const metadata: Metadata = {
  title: 'DocSuri',
  description: '근거 있는 논문 검색 — 폰 우선 웹',
  icons: { icon: '/logo.png', apple: '/logo.png' },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Production CSP script-src has no 'unsafe-inline' (middleware.ts, SEC-4); this inline
  // theme-init script needs the per-request nonce middleware minted to stay allowed.
  // Dev's CSP keeps 'unsafe-inline' and never sets x-nonce, so nonce is undefined there.
  const nonce = (await headers()).get('x-nonce') ?? undefined;
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        {/* Applies the stored dark/light override before React hydrates, so there's no
            flash of the wrong theme (the script runs before first paint). */}
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <ThemeProvider>
          <SessionProvider>
            <SavedLibraryProvider>
              <ViewModePreview />
              <PhoneMockupFrame>{children}</PhoneMockupFrame>
            </SavedLibraryProvider>
          </SessionProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
