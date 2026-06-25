import type { Metadata, Viewport } from 'next';
import './globals.css';
import { SessionProvider } from '@/components/session/SessionContext';
import { SavedLibraryProvider } from '@/lib/library/savedLibrary';
import { PhoneMockupFrame } from '@/components/PhoneMockupFrame';

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
    <html lang="ko">
      <body>
        <SessionProvider>
          <SavedLibraryProvider>
            <PhoneMockupFrame>{children}</PhoneMockupFrame>
          </SavedLibraryProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
