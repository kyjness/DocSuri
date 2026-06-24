'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import styles from './BottomNav.module.css';
import { useSession } from './session/SessionContext';

// BottomNav — mobile-first fixed bottom tab bar, shown only when authenticated.
// Two destinations today: 검색 / 마이페이지(라이브러리). "에이전트" 탭은 해당 기능이
// 생긴 뒤 추가한다 — 빈 목적지로 가는 탭은 두지 않는다. A spacer reserves layout space
// so page content can scroll clear of the fixed bar (scoped to pages that mount this).

function SearchIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

function UserIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </svg>
  );
}

const TABS = [
  { href: '/search', label: '검색', Icon: SearchIcon, isActive: (p: string) => p.startsWith('/search') || p.startsWith('/paper') },
  { href: '/library', label: '마이페이지', Icon: UserIcon, isActive: (p: string) => p.startsWith('/library') },
];

export function BottomNav() {
  const { status } = useSession();
  const pathname = usePathname() ?? '';
  if (status !== 'authenticated') return null;

  return (
    <>
      <div className={styles.spacer} aria-hidden="true" />
      <nav className={styles.nav} aria-label="주요 메뉴">
        {TABS.map(({ href, label, Icon, isActive }) => {
          const active = isActive(pathname);
          return (
            <Link
              key={href}
              href={href}
              className={styles.tab}
              data-active={active}
              aria-current={active ? 'page' : undefined}
              data-testid={`bottom-nav-${href.slice(1)}`}
            >
              <span className={styles.icon}>
                <Icon />
              </span>
              <span className={styles.label}>{label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}
