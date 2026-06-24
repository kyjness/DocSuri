'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import styles from './AuthForm.module.css';
import { getApiClient, UserFacingError } from '@/lib/api';

// VerifyEmail (US-A1, BR-A5) — landing page for the emailed activation link. Reads
// ?token=, calls the backend once, and shows a friendly terminal state with a path
// to login — instead of dumping raw backend JSON in the browser. The emailed link
// points here (PUBLIC_APP_URL/verify-email), NOT at the BFF/backend directly.

type State = 'verifying' | 'success' | 'error';

export function VerifyEmail() {
  const params = useSearchParams();
  const token = params.get('token') ?? '';
  const [state, setState] = useState<State>('verifying');
  const [message, setMessage] = useState<string>('');
  // Verification is one-shot; guard against React StrictMode's double effect invoke.
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    if (!token) {
      setState('error');
      setMessage('유효하지 않은 인증 링크입니다.');
      return;
    }
    void (async () => {
      try {
        await getApiClient().verifyEmail(token);
        setState('success');
      } catch (err) {
        setState('error');
        setMessage(
          err instanceof UserFacingError
            ? err.message
            : '인증에 실패했습니다. 링크가 만료되었거나 이미 사용되었을 수 있습니다.',
        );
      }
    })();
  }, [token]);

  if (state === 'verifying') {
    return (
      <p className={styles.formNotice} role="status" data-testid="verify-pending">
        이메일 인증을 처리하고 있습니다…
      </p>
    );
  }

  if (state === 'success') {
    return (
      <div className={styles.form} data-testid="verify-success">
        <p className={styles.formNotice} role="status">
          이메일 인증이 완료되었습니다. 이제 로그인할 수 있습니다.
        </p>
        <Link className={styles.linkButton} href="/login">
          로그인하러 가기
        </Link>
      </div>
    );
  }

  return (
    <div className={styles.form} data-testid="verify-error">
      <p className={styles.formError} role="alert">
        {message}
      </p>
      <Link className={styles.linkButton} href="/login">
        로그인 화면으로 이동 (인증 메일 재발송 가능)
      </Link>
    </div>
  );
}
