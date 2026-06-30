'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useSession } from './session/SessionContext';
import { StateView } from './StateView';

// RouteGuard (LC-4, BR-U5-15, SEC-8) — client-side reflection of protected
// routes. Anonymous users are redirected to login with the destination
// preserved. Backend 401/403 remains authoritative.

export function RouteGuard({ redirectTo, children }: { redirectTo: string; children: React.ReactNode }) {
  const { status, signingOut } = useSession();
  const router = useRouter();
  const sawSignOut = useRef(false);

  // Logout callers must navigate after signOut; this latch only suppresses RouteGuard's /login race.
  if (signingOut) sawSignOut.current = true;
  const isSignOutFlow = signingOut || sawSignOut.current;

  useEffect(() => {
    if (status === 'anonymous' && !isSignOutFlow) {
      router.replace(`/login?redirect=${encodeURIComponent(redirectTo)}`);
    }
  }, [status, isSignOutFlow, redirectTo, router]);

  if (status === 'authenticated') return <>{children}</>;
  if (isSignOutFlow) {
    return <StateView kind="loading" title="로그아웃 중…" message="잠시만 기다려 주세요." />;
  }
  return <StateView kind="loading" title="페이지를 불러오는 중…" message="잠시만 기다려 주세요." />;
}
