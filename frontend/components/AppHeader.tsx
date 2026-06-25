'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import styles from './AppHeader.module.css';
import { useSession } from './session/SessionContext';

// AppHeader (LC-1) — minimal top bar. Default: brand link + sign-out (home screens).
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
  const { status, signOut } = useSession();
  const router = useRouter();
  // Authenticated users treat the brand as the app home (search); anonymous /
  // first-time visitors land on the hero. The nav flow is silent on this, so
  // this is a code-level navigation choice.
  const brandHref = status === 'authenticated' ? '/search' : '/';

  // Sign out, then return to the hero landing (`/`) so the post-logout screen matches the
  // first-visit screen (a RouteGuard on a protected page would otherwise bounce to /login).
  const handleSignOut = async () => {
    await signOut();
    router.push('/');
  };

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
      {/* 화면 이동(검색/마이페이지)은 하단 탭바(BottomNav)가 담당한다.
          상단은 브랜드/뒤로 + 로그아웃만 유지한다. */}
      {status === 'authenticated' ? (
        <button
          type="button"
          className={styles.signout}
          onClick={() => void handleSignOut()}
          data-testid="app-header-signout"
        >
          로그아웃
        </button>
      ) : null}
    </header>
  );
}
