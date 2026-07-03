import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

/**
 * Security headers / CSP (LC-8, P-S2, SEC-4).
 *
 * frame-ancestors 'self' satisfies the phone-mockup carve-out (NFR-U2): the
 * desktop mockup frame is same-origin, so the app is never embedded by a third
 * party. Production script-src uses a per-request nonce (no 'unsafe-inline'); dev
 * keeps 'unsafe-inline'/'unsafe-eval' for HMR (see isDev below).
 */
// Next.js dev (Fast Refresh / HMR / webpack) evaluates code via `eval` and injects
// inline scripts, which require 'unsafe-eval'/'unsafe-inline'. Allow both ONLY in
// development. A nonce disables 'unsafe-inline' per the CSP spec (browsers ignore
// 'unsafe-inline' once a nonce is present), so dev must NOT emit one or HMR breaks.
// Production drops 'unsafe-inline'/'unsafe-eval' entirely and uses a per-request
// nonce instead (SEC-4, NFR-U5-S2, P-S2).
const isDev = process.env.NODE_ENV !== 'production';

const RECAPTCHA_SCRIPT_HOSTS = [
  'https://www.google.com/recaptcha/',
  'https://www.gstatic.com/recaptcha/',
];

function buildScriptSrc(nonce: string): string {
  return isDev
    ? ["'self'", "'unsafe-inline'", "'unsafe-eval'", ...RECAPTCHA_SCRIPT_HOSTS].join(' ')
    : ["'self'", `'nonce-${nonce}'`, ...RECAPTCHA_SCRIPT_HOSTS].join(' ');
}

function buildCsp(nonce: string): string {
  return [
    "default-src 'self'",
    `script-src ${buildScriptSrc(nonce)}`,
    // Styling nonce is out of scope — style-src keeps 'unsafe-inline'.
    "style-src 'self' 'unsafe-inline'",
    // Figure/table images are short-lived presigned S3 GET URLs (SEC-9): the object host must be
    // whitelisted or the browser blocks them (broken-image icons). Scoped to the region's S3 hosts.
    "img-src 'self' data: https://*.s3.ap-northeast-2.amazonaws.com https://s3.ap-northeast-2.amazonaws.com",
    "connect-src 'self' https://www.google.com/recaptcha/",
    "frame-src 'self' https://www.google.com/recaptcha/",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'self'",
    "form-action 'self'",
  ].join('; ');
}

export function middleware(request: NextRequest) {
  // Per-request nonce (Edge runtime has Web Crypto). Only meaningful in prod's
  // script-src; generated unconditionally to keep the header plumbing uniform.
  const nonce = crypto.randomUUID();
  const csp = buildCsp(nonce);

  // Set on the REQUEST headers so Next's own inline bootstrap scripts (and
  // app/layout.tsx reading `x-nonce`) get auto-nonced from the same value.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('content-security-policy', csp);
  // Dev renders scripts without a nonce (permitted by dev's 'unsafe-inline'); only
  // hand the nonce to layout in prod, where it's actually required.
  if (!isDev) requestHeaders.set('x-nonce', nonce);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set('Content-Security-Policy', csp);
  response.headers.set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  response.headers.set('X-Frame-Options', 'SAMEORIGIN');
  return response;
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
