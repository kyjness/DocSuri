import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

/**
 * Security headers / CSP (LC-8, P-S2, SEC-4).
 *
 * frame-ancestors 'self' satisfies the phone-mockup carve-out (NFR-U2): the
 * desktop mockup frame is same-origin, so the app is never embedded by a third
 * party. Concrete values / nonce strategy are refined at code/Infra stage.
 */
// Next.js dev (Fast Refresh / HMR / webpack) evaluates code via `eval`, which
// requires 'unsafe-eval'. Allow it ONLY in development; production stays strict
// (no unsafe-eval) per SEC-4.
const isDev = process.env.NODE_ENV !== 'production';
const scriptSrc = [
  "'self'",
  "'unsafe-inline'",
  "https://www.google.com/recaptcha/",
  "https://www.gstatic.com/recaptcha/",
  ...(isDev ? ["'unsafe-eval'"] : []),
].join(' ');

const CSP = [
  "default-src 'self'",
  `script-src ${scriptSrc}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self' https://www.google.com/recaptcha/",
  "frame-src 'self' https://www.google.com/recaptcha/",
  "object-src 'none'",
  "base-uri 'self'",
  "frame-ancestors 'self'",
  "form-action 'self'",
].join('; ');

export function middleware(_request: NextRequest) {
  const response = NextResponse.next();
  response.headers.set('Content-Security-Policy', CSP);
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  response.headers.set('X-Frame-Options', 'SAMEORIGIN');
  return response;
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
