import type { Metadata, Viewport } from 'next';
import './globals.css';
import { SessionProvider } from '@/components/session/SessionContext';
import { ThemeProvider } from '@/components/theme/ThemeContext';
import { SavedLibraryProvider } from '@/lib/library/savedLibrary';
import { PhoneMockupFrame } from '@/components/PhoneMockupFrame';
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

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        {/* Applies the stored dark/light override before React hydrates, so there's no
            flash of the wrong theme (the script runs before first paint). */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <ThemeProvider>
          <SessionProvider>
            <SavedLibraryProvider>
              <PhoneMockupFrame>{children}</PhoneMockupFrame>
            </SavedLibraryProvider>
          </SessionProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
