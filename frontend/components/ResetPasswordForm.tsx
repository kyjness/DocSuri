'use client';

import { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import styles from './AuthForm.module.css';
import { getApiClient, UserFacingError } from '@/lib/api';
import { validateEmail, validateRequiredPassword } from '@/lib/api/validate';
import { AuthField } from './AuthField';

// ResetPasswordForm (FR-26/BR-A8). Two modes selected by the ?token= query param:
//  - no token → request: enter email; backend emails a reset link. The response is identical
//    whether or not the address exists (enumeration-safe), so we always show the same notice.
//  - token   → confirm: choose a new password; on success route to login.

function RequestForm() {
  const [email, setEmail] = useState('');
  const [fieldErr, setFieldErr] = useState<string | undefined>();
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    const r = validateEmail(email);
    if (!r.ok) {
      setFieldErr(r.message);
      return;
    }
    setFieldErr(undefined);
    setSubmitting(true);
    try {
      await getApiClient().requestPasswordReset(email.trim());
    } catch {
      // Enumeration-safe: show the same generic notice regardless of success/failure.
    } finally {
      setSubmitting(false);
      setDone(true);
    }
  };

  if (done) {
    return (
      <p className={styles.formNotice} role="status" data-testid="reset-request-done">
        해당 이메일로 가입된 활성 계정이 있다면 비밀번호 재설정 링크를 보냈습니다. 메일함(스팸함
        포함)을 확인해 주세요.
      </p>
    );
  }

  return (
    <form className={styles.form} onSubmit={onSubmit} data-testid="reset-request-form">
      <p className={styles.formNotice}>
        가입한 이메일을 입력하면 비밀번호 재설정 링크를 보내드립니다.
      </p>
      <AuthField
        id="reset-email"
        label="이메일"
        type="email"
        autoComplete="email"
        value={email}
        onChange={setEmail}
        error={fieldErr}
        testId="reset-email"
      />
      <button
        type="submit"
        className={styles.submit}
        disabled={submitting}
        data-testid="reset-request-submit"
      >
        재설정 링크 받기
      </button>
    </form>
  );
}

function ConfirmForm({ token }: { token: string }) {
  const router = useRouter();
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [errs, setErrs] = useState<{ pw?: string; pw2?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    const pwRes = validateRequiredPassword(pw);
    const next: { pw?: string; pw2?: string } = { pw: pwRes.ok ? undefined : pwRes.message };
    if (pw !== pw2) next.pw2 = '비밀번호가 일치하지 않습니다.';
    setErrs(next);
    if (next.pw || next.pw2) return;
    setFormError(null);
    setSubmitting(true);
    try {
      await getApiClient().confirmPasswordReset(token, pw);
      router.push('/login?reset=1');
    } catch (err) {
      setFormError(
        err instanceof UserFacingError
          ? err.message
          : '비밀번호 재설정에 실패했습니다. 링크가 만료되었을 수 있어요. 다시 요청해 주세요.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className={styles.form} onSubmit={onSubmit} data-testid="reset-confirm-form">
      {formError ? (
        <p className={styles.formError} role="alert" data-testid="reset-confirm-error">
          {formError}
        </p>
      ) : null}
      <AuthField
        id="reset-new-password"
        label="새 비밀번호"
        type="password"
        autoComplete="new-password"
        value={pw}
        onChange={setPw}
        error={errs.pw}
        testId="reset-new-password"
      />
      <AuthField
        id="reset-confirm-password"
        label="새 비밀번호 확인"
        type="password"
        autoComplete="new-password"
        value={pw2}
        onChange={setPw2}
        error={errs.pw2}
        testId="reset-confirm-password"
      />
      <button
        type="submit"
        className={styles.submit}
        disabled={submitting}
        data-testid="reset-confirm-submit"
      >
        비밀번호 재설정
      </button>
    </form>
  );
}

export function ResetPasswordForm() {
  const token = useSearchParams().get('token');
  return token ? <ConfirmForm token={token} /> : <RequestForm />;
}
