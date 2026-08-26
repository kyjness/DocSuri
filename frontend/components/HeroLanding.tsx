'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import styles from './HeroLanding.module.css';
import { useSession } from './session/SessionContext';

// HeroLanding (LC-1, US-H1) — the magic-moment entry for anonymous / first-time
// visitors (sign up / log in; search requires auth, U2 FD §Q5=A). Authenticated
// users have no use for the landing, so they go straight to search (FD intent:
// authenticated → SearchScreen). The CTA area stays hidden until the session
// resolves so the auth prompts don't flash before a redirect.

// 가입 없이 둘러보기 — 빌드 시점에 박히는 게이트다(`NEXT_PUBLIC_*`). 데모 배포에서만 켠다:
// 가입 장벽을 없애는 공개 표면이라 실서비스 이미지에 켜진 채 나가면 안 된다. 백엔드에도 같은
// 이름의 스위치가 따로 있고(`DOCSURI_DEMO_LOGIN_ENABLED`), 꺼져 있으면 404다 — 버튼만 숨기고
// 엔드포인트가 열려 있으면 숨긴 것이 아니다.
const DEMO_LOGIN_ENABLED = process.env.NEXT_PUBLIC_DOCSURI_DEMO_LOGIN_ENABLED === '1';

export function HeroLanding() {
  const { status, refresh } = useSession();
  const router = useRouter();
  const [demoPending, setDemoPending] = useState(false);
  const [demoError, setDemoError] = useState('');

  async function startDemo() {
    setDemoPending(true);
    setDemoError('');
    try {
      // BFF가 게이트웨이의 Set-Cookie를 브라우저로 중계한다 — 세션 토큰이 클라이언트 JS에
      // 들어오지 않는다(SEC-3/12). 그래서 응답 본문에서 꺼낼 것이 없고, 성공이면 바로 넘긴다.
      // 경로는 `/bff/auth/demo`다 — 계정 라우터가 `/auth`에 붙어 있다(`/api/auth`가 아니다).
      // 처음에 `/bff/api/auth/demo`로 적었더니 배포본에서 401이 났다: 그 경로는 라우터에 없어
      // 미들웨어 단계에서 끊긴다. 다른 인증 호출(`/auth/signup`·`/auth/login`)도 전부 `/auth`다.
      const res = await fetch('/bff/auth/demo', { method: 'POST' });
      if (!res.ok) throw new Error(String(res.status));
      // **세션을 먼저 갱신한다.** 쿠키는 응답에 실려 오지만 컨텍스트는 아직 anonymous라,
      // 그대로 이동하면 `/search`의 가드가 로그인 화면으로 되돌린다 — 화면에서는 "버튼을
      // 눌렀는데 로그인 페이지로 간다"로 보인다. 로그인 폼도 같은 순서다(refresh → 이동).
      await refresh();
      // `replace`다 — 뒤로 가기로 랜딩에 돌아와 다시 계정을 만드는 것을 막는다.
      router.replace('/search');
    } catch {
      setDemoError('지금은 둘러보기를 시작할 수 없어요. 잠시 후 다시 시도해 주세요.');
      setDemoPending(false);
    }
  }

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
          {DEMO_LOGIN_ENABLED ? (
            <button
              type="button"
              className={styles.tertiary}
              onClick={startDemo}
              disabled={demoPending}
              data-testid="hero-cta-demo"
            >
              {demoPending ? '들어가는 중…' : '가입없이 로그인'}
            </button>
          ) : null}
          {demoError ? (
            <p className={styles.demoError} role="alert" data-testid="hero-demo-error">
              {demoError}
            </p>
          ) : null}
        </div>
      ) : null}
      {/* Legal links — reachable from the homepage so Google/social OAuth review can
          find the privacy policy; the consent screen also carries these URLs. */}
      <footer className={styles.legalFooter}>
        <Link href="/privacy" className={styles.legalLink}>
          개인정보처리방침
        </Link>
        <span aria-hidden="true">·</span>
        <Link href="/terms" className={styles.legalLink}>
          이용약관
        </Link>
      </footer>
    </section>
  );
}
