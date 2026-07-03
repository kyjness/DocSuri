'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import styles from './AppHeader.module.css';
import { useSession } from './session/SessionContext';

// Primary destinations, mirrored from BottomNav. On desktop these render inline in the
// header (a top nav bar); on phones the BottomNav tab bar owns navigation and these are
// hidden. Kept here so the desktop bar reads like an ordinary web app nav.
const NAV_LINKS = [
  { href: '/search', label: '검색', isActive: (p: string) => p.startsWith('/search') || p.startsWith('/paper') },
  { href: '/agent', label: '에이전트', isActive: (p: string) => p.startsWith('/agent') },
  { href: '/mypage', label: '마이페이지', isActive: (p: string) => p.startsWith('/mypage') },
];

// AppHeader (LC-1) — minimal top bar. Default: brand link (+ desktop nav links). Sign-out
// lives in 마이페이지 → 설정, not here.
// Back mode (`backHref`): a left back-arrow to a FIXED destination instead of the brand, for
// full-screen sub-routes (paper detail → /search, 본문 / 본문 번역 → the detail page). A fixed
// destination (not history back) is deliberate: these are app routes (not browser tabs), and
// history back is fragile after an interleaved login redirect (session expiry) or a deep link.
interface AppHeaderProps {
  title?: string;
  /** Show a back arrow to this fixed destination instead of the brand. */
  backHref?: string;
}

export function AppHeader({ title, backHref }: AppHeaderProps) {
  const { status } = useSession();
  const pathname = usePathname() ?? '';
  // Authenticated users treat the brand as the app home (search); anonymous /
  // first-time visitors land on the hero. The nav flow is silent on this, so
  // this is a code-level navigation choice.
  const brandHref = status === 'authenticated' ? '/search' : '/';

  return (
    <header className={styles.header}>
      <div className={styles.lead}>
        {backHref ? (
          <Link
            href={backHref}
            className={styles.back}
            aria-label="뒤로"
            data-testid="app-header-back"
          >
            ←
          </Link>
        ) : (
          <Link href={brandHref} className={styles.brand} data-testid="app-header-brand">
            {/* Decorative mark: the brand text beside it carries the accessible name. */}
            {/* eslint-disable-next-line @next/next/no-img-element -- small static brand asset (8KB); next/image not configured */}
            <img src="/logo.png" alt="" className={styles.brandLogo} width={32} height={32} />
            {title}
          </Link>
        )}
        {backHref && title ? <span className={styles.titleText}>{title}</span> : null}
      </div>
      {/* On phones the bottom tab bar (BottomNav) owns 검색/마이페이지; this inline nav is
          hidden there (CSS) and shown on desktop. In back mode (sub-routes) it's suppressed. */}
      {status === 'authenticated' && !backHref ? (
        <nav className={styles.nav} aria-label="주요 메뉴">
          {NAV_LINKS.map(({ href, label, isActive }) => {
            const active = isActive(pathname);
            return (
              <Link
                key={href}
                href={href}
                className={styles.navLink}
                data-active={active}
                aria-current={active ? 'page' : undefined}
              >
                {label}
              </Link>
            );
          })}
        </nav>
      ) : null}
    </header>
  );
}
