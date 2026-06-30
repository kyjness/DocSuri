'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { getApiClient } from '@/lib/api';
import type { SessionInfo } from '@/types/generated';

// SessionContext (LC-3, NFR-U5-S7) — app-wide session state derived from
// currentSession(). Holds only non-sensitive SessionInfo; the token lives in the
// httpOnly cookie and is never read here (BR-U5-14).

type SessionStatus = 'loading' | 'anonymous' | 'authenticated';

interface SessionValue {
  status: SessionStatus;
  user: SessionInfo | null;
  signingOut: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

const SessionCtx = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [user, setUser] = useState<SessionInfo | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const session = await getApiClient().currentSession();
      setUser(session);
      setStatus(session ? 'authenticated' : 'anonymous');
    } catch {
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  const signOut = useCallback(async () => {
    setSigningOut(true);
    try {
      await getApiClient().logout();
    } finally {
      setUser(null);
      setStatus('anonymous');
      setSigningOut(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<SessionValue>(
    () => ({ status, user, signingOut, refresh, signOut }),
    [status, user, signingOut, refresh, signOut],
  );

  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionCtx);
  if (!ctx) throw new Error('useSession must be used within a SessionProvider');
  return ctx;
}
