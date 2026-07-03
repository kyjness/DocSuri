'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import styles from './AuthForm.module.css';
import { getApiClient, UserFacingError } from '@/lib/api';
import { useSession } from './session/SessionContext';
import { validateEmail, validateRequiredPassword } from '@/lib/api/validate';
import { AuthField } from './AuthField';
import { ORCID_LOGIN_ENABLED } from '@/lib/socialLogin';
import { safeRedirect } from '@/lib/redirect';

// LoginForm (LC-1, US-A2, BR-U5-16) — generalized auth errors (credential
// existence not disclosed). On success, refresh the session and return to the
// preserved destination.

type RecaptchaApi = {
  ready(callback: () => void): void;
  execute(siteKey: string, options: { action: string }): Promise<string>;
};

declare global {
  interface Window {
    grecaptcha?: RecaptchaApi;
  }
}

let recaptchaScriptLoad: Promise<void> | null = null;

function recaptchaSiteKey(): string | undefined {
  const value = process.env.NEXT_PUBLIC_RECAPTCHA_SITE_KEY?.trim();
  return value || undefined;
}

function loadRecaptcha(siteKey: string): Promise<void> {
  if (typeof window === 'undefined' || window.grecaptcha) return Promise.resolve();
  if (recaptchaScriptLoad) return recaptchaScriptLoad;

  recaptchaScriptLoad = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = `https://www.google.com/recaptcha/api.js?render=${encodeURIComponent(siteKey)}`;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('recaptcha-load-failed'));
    document.head.appendChild(script);
  });
  return recaptchaScriptLoad;
}

async function recaptchaToken(action: string): Promise<string | undefined> {
  const siteKey = recaptchaSiteKey();
  if (!siteKey) return undefined;
  await loadRecaptcha(siteKey);
  if (!window.grecaptcha) throw new Error('recaptcha-unavailable');
  return new Promise((resolve, reject) => {
    window.grecaptcha?.ready(() => {
      window.grecaptcha?.execute(siteKey, { action }).then(resolve, reject);
    });
  });
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useSession();
  const redirectTo = safeRedirect(params.get('redirect'));

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
      const token = await recaptchaToken('login');
      await getApiClient().login({ email: email.trim(), password }, token);
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
      {params.get('reset') ? (
        <p className={styles.formNotice} role="status" data-testid="login-reset-notice">
          비밀번호가 재설정되었습니다. 새 비밀번호로 로그인해 주세요.
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
      <div className={styles.linkRow}>
        <Link href="/reset-password" className={styles.linkButton} data-testid="login-reset-link">
          비밀번호를 잊으셨나요?
        </Link>
      </div>
      <div className={styles.divider}>또는</div>
      {/* 소셜 로그인은 전체 페이지 리다이렉트(OIDC) — 엣지에서 백엔드 오리진으로 라우팅되는
          /auth/social/google/start로 직접 이동한다(BFF JSON 프록시 경유 아님). */}
      <a
        className={styles.socialButton}
        href="/auth/social/google/start"
        data-testid="login-google"
      >
        Google로 계속하기
      </a>
      {ORCID_LOGIN_ENABLED ? (
        <a
          className={styles.socialButton}
          href="/auth/social/orcid/start"
          data-testid="login-orcid"
        >
          ORCID로 계속하기
        </a>
      ) : null}
    </form>
  );
}
