// Mock account state — derived from shared/dtos/accounts.schema.json (BR-U5-19).
// Session for mock-first development. `password` is never stored or echoed
// (SEC-12/3) — login only flips an authenticated flag.
//
// Backed by localStorage (with an in-memory fallback for non-browser contexts) so the
// mock session behaves like the real httpOnly cookie: shared across same-origin documents
// and persisted across reloads. This is what lets the desktop phone preview — a separate
// iframe document — stay logged in when toggled, instead of each iframe getting a fresh
// empty in-memory session.
import type { SessionInfo, SignupResult } from '@/types/generated';

const SESSION_KEY = 'docsuri-mock-session';

// Fallback store when localStorage is unavailable (e.g. SSR / private mode).
let memorySession: SessionInfo | null = null;

function readSession(): SessionInfo | null {
  if (typeof window === 'undefined') return memorySession;
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as SessionInfo) : null;
  } catch {
    return memorySession;
  }
}

function writeSession(next: SessionInfo | null): void {
  memorySession = next;
  if (typeof window === 'undefined') return;
  try {
    if (next) window.localStorage.setItem(SESSION_KEY, JSON.stringify(next));
    else window.localStorage.removeItem(SESSION_KEY);
  } catch {
    // localStorage unavailable — the in-memory fallback still holds the session.
  }
}

export function mockSignup(): SignupResult {
  return { accountId: 'acct_mock_0001' };
}

export function mockLogin(email: string): SessionInfo {
  const session: SessionInfo = {
    userId: `user_${hash(email)}`,
    expiresAt: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
  };
  writeSession(session);
  return session;
}

export function mockLogout(): void {
  writeSession(null);
}

export function mockCurrentSession(): SessionInfo | null {
  return readSession();
}

function hash(s: string): string {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h).toString(36);
}
