'use client';

import { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import styles from './AuthForm.module.css';
import { getApiClient, UserFacingError } from '@/lib/api';
import { useSession } from './session/SessionContext';
import { validateEmail, validateRequiredPassword } from '@/lib/api/validate';
import { AuthField } from './AuthField';

// LoginForm (LC-1, US-A2, BR-U5-16) — generalized auth errors (credential
// existence not disclosed). On success, refresh the session and return to the
// preserved destination.

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useSession();
  const redirectTo = params.get('redirect') ?? '/search';

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Recourse when login fails on an unverified (PENDING) account: resend the
  // verification email. Shown only after a failed attempt, when an email is present.
  const [resendMsg, setResendMsg] = useState<string | null>(null);
  const [resending, setResending] = useState(false);

  const onResend = async () => {
    if (resending) return;
    const emailRes = validateEmail(email);
    if (!emailRes.ok) {
      setFieldErrors((prev) => ({ ...prev, email: emailRes.message }));
      return;
    }
    setResending(true);
    setResendMsg(null);
    try {
      await getApiClient().resendVerification(email.trim());
      setResendMsg('인증 메일을 다시 보냈습니다. 메일함(스팸함 포함)을 확인해 주세요.');
    } catch {
      // Generic — never reveal whether the address exists / is verifiable.
      setResendMsg('인증 메일을 다시 보냈습니다. 메일함(스팸함 포함)을 확인해 주세요.');
    } finally {
      setResending(false);
    }
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    const emailRes = validateEmail(email);
    const pwRes = validateRequiredPassword(password);
    const errs = {
      email: emailRes.ok ? undefined : emailRes.message,
      password: pwRes.ok ? undefined : pwRes.message,
    };
    setFieldErrors(errs);
    if (errs.email || errs.password) return;

    setFormError(null);
    setResendMsg(null);
    setSubmitting(true);
    try {
      await getApiClient().login({ email: email.trim(), password });
      await refresh();
      router.push(redirectTo);
    } catch (err) {
      setFormError(
        err instanceof UserFacingError ? err.message : '로그인에 실패했습니다. 다시 시도해 주세요.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className={styles.form} onSubmit={onSubmit} data-testid="login-form">
      {params.get('signup') ? (
        <p className={styles.formError} role="status" data-testid="login-signup-notice">
          가입이 완료되었습니다. 로그인해 주세요.
        </p>
      ) : null}
      {formError ? (
        <>
          <p className={styles.formError} role="alert" data-testid="login-form-error">
            {formError}
          </p>
          <button
            type="button"
            className={styles.linkButton}
            onClick={onResend}
            disabled={resending}
            data-testid="login-resend"
          >
            인증 메일 재발송
          </button>
        </>
      ) : null}
      {resendMsg ? (
        <p className={styles.formNotice} role="status" data-testid="login-resend-notice">
          {resendMsg}
        </p>
      ) : null}
      <AuthField
        id="login-email"
        label="이메일"
        type="email"
        autoComplete="email"
        value={email}
        onChange={setEmail}
        error={fieldErrors.email}
        testId="login-email"
      />
      <AuthField
        id="login-password"
        label="비밀번호"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={setPassword}
        error={fieldErrors.password}
        testId="login-password"
      />
      <button
        type="submit"
        className={styles.submit}
        disabled={submitting}
        data-testid="login-submit"
      >
        로그인
      </button>
    </form>
  );
}
