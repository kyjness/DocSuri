'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import styles from './AuthForm.module.css';
import { getApiClient, UserFacingError } from '@/lib/api';
import { validateEmail, validateRequiredPassword } from '@/lib/api/validate';
import { AuthField } from './AuthField';
import { ORCID_LOGIN_ENABLED } from '@/lib/socialLogin';

// SignupForm (LC-1, US-A1, BR-U5-2/13) — client validation mirrors
// accounts.schema.json (presence/format). Password is input-only (SEC-12/3);
// complexity/blacklist policy messages come from the backend response.

export function SignupForm() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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
    setSubmitting(true);
    try {
      await getApiClient().signup({ email: email.trim(), password });
      router.push('/login?signup=1');
    } catch (err) {
      setFormError(
        err instanceof UserFacingError ? err.message : '가입에 실패했습니다. 다시 시도해 주세요.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className={styles.form} onSubmit={onSubmit} data-testid="signup-form">
      {formError ? (
        <p className={styles.formError} role="alert" data-testid="signup-form-error">
          {formError}
        </p>
      ) : null}
      <AuthField
        id="signup-email"
        label="이메일"
        type="email"
        autoComplete="email"
        value={email}
        onChange={setEmail}
        error={fieldErrors.email}
        testId="signup-email"
      />
      <AuthField
        id="signup-password"
        label="비밀번호"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={setPassword}
        error={fieldErrors.password}
        testId="signup-password"
      />
      <button
        type="submit"
        className={styles.submit}
        disabled={submitting}
        data-testid="signup-submit"
      >
        가입하기
      </button>
      <div className={styles.divider}>또는</div>
      {/* 소셜 가입/로그인 — 전체 페이지 OIDC 리다이렉트(/auth/social/google/start). */}
      <a
        className={styles.socialButton}
        href="/auth/social/google/start"
        target="_top"
        data-testid="signup-google"
      >
        Google로 계속하기
      </a>
      {ORCID_LOGIN_ENABLED ? (
        <a
          className={styles.socialButton}
          href="/auth/social/orcid/start"
          target="_top"
          data-testid="signup-orcid"
        >
          ORCID로 계속하기
        </a>
      ) : null}
    </form>
  );
}
