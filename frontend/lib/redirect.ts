// Safe post-auth redirect target (BR-U5-15, SEC-8). Only same-origin paths are honored;
// absolute URLs, protocol-relative `//host`, and backslash tricks fall back — closing the
// open-redirect/phishing vector on ?redirect.
export function safeRedirect(raw: string | null | undefined, fallback = '/search'): string {
  if (!raw) return fallback;
  // A single leading '/', not '//' or '/\' (protocol-relative / backslash).
  if (!/^\/(?![/\\])/.test(raw)) return fallback;
  return raw;
}
