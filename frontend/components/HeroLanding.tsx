'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import styles from './HeroLanding.module.css';
import { useSession } from './session/SessionContext';

// HeroLanding (LC-1, US-H1) — the magic-moment entry for anonymous / first-time
// visitors (sign up / log in; search requires auth, U2 FD §Q5=A). Authenticated
// users have no use for the landing, so they go straight to search (FD intent:
// authenticated → SearchScreen). The CTA area stays hidden until the session
// resolves so the auth prompts don't flash before a redirect.

export function HeroLanding() {
  const { status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === 'authenticated') {
      router.replace('/search');
    }
  }, [status, router]);

  return (
    <section className={styles.root} data-testid="hero-landing">
      {/* Decorative: the <h1> already names the brand, so the mark is alt="" to avoid
          a screen reader announcing "DocSuri" twice. */}
      {/* eslint-disable-next-line @next/next/no-img-element -- small static brand asset (8KB); next/image not configured */}
      <img src="/logo.png" alt="" className={styles.logo} width={120} height={120} />
      <h1 className={styles.title}>DocSuri</h1>
      <p className={styles.tagline}>논문을 독수리처럼 날카롭게 포착하다</p>
      <p className={styles.subtitle}>
        쏟아지는 AI·머신러닝 논문들에서 근거 있는 핵심만 받아보세요.
      </p>

      {status === 'anonymous' ? (
        <div className={styles.actions}>
          <Link href="/signup" className={styles.primary} data-testid="hero-cta-signup">
            시작하기
          </Link>
          <Link href="/login?redirect=/search" className={styles.secondary} data-testid="hero-cta-login">
            로그인
          </Link>
        </div>
      ) : null}
    </section>
  );
}
