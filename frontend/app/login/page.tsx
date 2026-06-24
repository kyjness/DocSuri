import { Suspense } from 'react';
import styles from '../page.module.css';
import { AppHeader } from '@/components/AppHeader';
import { LoginForm } from '@/components/LoginForm';

// Login route (US-A2). LoginForm reads search params, so it sits under Suspense.
export default function LoginPage() {
  // Back-mode header (← 로그인) to match the in-app sub-route pattern (detail/본문/번역);
  // the fixed destination is the hero landing. The header title carries the screen name, so
  // the page no longer repeats it as a separate heading.
  return (
    <div className={styles.screen}>
      <AppHeader title="로그인" backHref="/" />
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </div>
  );
}
