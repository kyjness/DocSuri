'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { recordEntry } from '@/lib/navHistory';

// Stamps each history entry with the screen it was entered from, so the header's ← can tell
// whether going back stays in the app (lib/navHistory). Rendered once in the root layout.
export function NavHistoryTracker() {
  const pathname = usePathname();
  useEffect(() => {
    if (pathname) recordEntry(pathname);
  }, [pathname]);
  return null;
}
