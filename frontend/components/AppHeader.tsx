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
  /**
   * 목적지가 **자기 스크롤을 스스로 복원**할 때 켠다(검색 화면이 그렇다). 라우터의 기본
   * 동작은 이동 후 맨 위로 스크롤하는 것인데, 그 처리가 화면의 복원보다 뒤에 돌아 복원한
   * 위치를 덮는다. `scroll={false}`로 라우터를 비켜 두면 화면이 자기 위치를 되돌린다.
   * 목적지가 복원하지 않는 화면(본문 → 상세 등)에서는 켜면 안 된다 — 이전 화면의 스크롤이
   * 그대로 남아 엉뚱한 위치에서 열린다.
   */
  backRestoresScroll?: boolean;
}

export function AppHeader({ title, backHref, backRestoresScroll = false }: AppHeaderProps) {
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
            scroll={!backRestoresScroll}
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
