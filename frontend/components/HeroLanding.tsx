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
      <h1 className={styles.title}>DocSuri</h1>
      <p className={styles.subtitle}>
        질문을 입력하면 근거 있는 논문을 찾아드려요.
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
