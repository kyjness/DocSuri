'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getApiClient, UserFacingError } from '@/lib/api';
import { validateEmail, validateRequiredPassword } from '@/lib/api/validate';
import { useSession } from '../session/SessionContext';
import { useTheme } from '../theme/ThemeContext';
import { StateView } from '../StateView';
import { AuthField } from '../AuthField';
import styles from './MyPageScreen.module.css';
import authStyles from '../AuthForm.module.css';
import type { ConsentSettingsVM } from '@/types/mypage';

// MyPageSettingsScreen (U10) — 동의 철회(야간 푸시만 토글, 필수 동의는 읽기 전용) + 비밀번호 변경
// + 이메일 변경(FR-28/BR-A10) + 로그아웃 + 회원탈퇴. 비밀번호 변경·탈퇴·이메일 변경은 현재
// 비밀번호 재인증을 요구한다(감사 H7). 비밀번호 변경 성공 시 백엔드가 전 세션을 무효화하므로
// 로그아웃 후 재로그인 화면으로 보낸다.

type BusyKey = 'consent' | 'logout' | 'withdraw' | 'password' | 'email' | null;

export function MyPageSettingsScreen() {
  const { signOut } = useSession();
  const { effectiveTheme, setTheme } = useTheme();
  const router = useRouter();
  const [consents, setConsents] = useState<ConsentSettingsVM | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [busy, setBusy] = useState<BusyKey>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // 비밀번호 변경 폼
  const [curPw, setCurPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [pwError, setPwError] = useState<string | null>(null);
  // 이메일 변경 폼
  const [emailCurPw, setEmailCurPw] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [emailError, setEmailError] = useState<string | null>(null);
  const [emailNotice, setEmailNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus('loading');
    try {
      const result = await getApiClient().getConsents();
      setConsents(result);
      setStatus('ready');
    } catch {
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const withBusy = async (key: NonNullable<BusyKey>, action: () => Promise<void>) => {
    setBusy(key);
    setActionError(null);
    try {
      await action();
    } catch {
      setActionError('처리하지 못했습니다. 다시 시도해 주세요.');
    } finally {
      setBusy(null);
    }
  };

  const onToggleNightlyPush = (checked: boolean) =>
    withBusy('consent', async () => {
      const result = await getApiClient().updateNightlyPushConsent(checked);
      setConsents(result);
    });

  // 다크모드는 기기(브라우저)별 설정 — 계정에 저장하지 않으므로 API 호출이 필요 없다.
  const onToggleDarkMode = (checked: boolean) => setTheme(checked ? 'dark' : 'light');

  const onLogout = () =>
    withBusy('logout', async () => {
      await signOut();
      router.push('/');
    });

  const onWithdraw = () =>
    withBusy('withdraw', async () => {
      // ponytail: window.prompt = 최소 재인증 UX; 마스킹되는 인라인 모달은 UX가 중요해지면 올린다.
      // 소셜-only 계정은 비밀번호가 없으므로 빈 칸으로 확인하면 백엔드가 재인증을 건너뛴다(H7).
      const pw = window.prompt(
        '회원탈퇴를 진행하려면 현재 비밀번호를 입력하세요. (소셜 로그인 계정은 빈 칸으로 확인)',
      );
      if (pw === null) return; // 취소
      await getApiClient().withdrawAccount(pw || undefined);
      await signOut();
      router.push('/');
    });

  const onChangePassword = (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setPwError(null);
    const curRes = validateRequiredPassword(curPw);
    if (!curRes.ok) {
      setPwError(curRes.message);
      return;
    }
    const newRes = validateRequiredPassword(newPw);
    if (!newRes.ok) {
      setPwError(newRes.message);
      return;
    }
    setBusy('password');
    void (async () => {
      try {
        await getApiClient().changePassword(curPw, newPw);
        // 백엔드가 전 세션 무효화 → 재로그인 필요.
        await signOut();
        router.push('/login?reset=1');
      } catch (err) {
        setPwError(
          err instanceof UserFacingError
            ? err.message
            : '비밀번호를 변경하지 못했습니다. 다시 시도해 주세요.',
        );
      } finally {
        setBusy(null);
      }
    })();
  };

  const onRequestEmailChange = (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setEmailError(null);
    setEmailNotice(null);
    const emailRes = validateEmail(newEmail);
    if (!emailRes.ok) {
      setEmailError(emailRes.message);
      return;
    }
    const pwRes = validateRequiredPassword(emailCurPw);
    if (!pwRes.ok) {
      setEmailError(pwRes.message);
      return;
    }
    setBusy('email');
    void (async () => {
      try {
        await getApiClient().requestEmailChange(newEmail.trim(), emailCurPw);
        setNewEmail('');
        setEmailCurPw('');
        setEmailNotice('새 이메일 주소로 확인 링크를 보냈습니다. 메일함을 확인해 주세요.');
      } catch (err) {
        setEmailError(
          err instanceof UserFacingError
            ? err.message
            : '이메일 변경 요청에 실패했습니다. 다시 시도해 주세요.',
        );
      } finally {
        setBusy(null);
      }
    })();
  };

  if (status === 'loading') return <StateView kind="loading" title="설정을 불러오는 중…" />;
  if (status === 'error' || !consents)
    return <StateView kind="error" onRetry={() => void load()} />;

  return (
    <section className={styles.screen} data-testid="mypage-settings-screen">
      {actionError ? (
        <p className={styles.error} role="alert" data-testid="mypage-action-error">
          {actionError}
        </p>
      ) : null}

      <section className={styles.card} data-testid="mypage-display">
        <h2 className={styles.cardTitle}>화면</h2>
        <label className={styles.toggleRow}>
          <span>다크 모드 (이 기기에만 적용)</span>
          <input
            type="checkbox"
            checked={effectiveTheme === 'dark'}
            onChange={(e) => onToggleDarkMode(e.target.checked)}
            data-testid="mypage-dark-mode"
          />
        </label>
      </section>

      <section className={styles.card} data-testid="mypage-consents">
        <h2 className={styles.cardTitle}>동의 철회</h2>
        <label className={styles.toggleRow}>
          <span>개인정보처리방침 동의 (가입 시 필수, 철회 불가)</span>
          <input type="checkbox" checked={consents.privacyPolicyAgreed} disabled readOnly />
        </label>
        <label className={styles.toggleRow}>
          <span>서비스 이용약관 동의 (가입 시 필수, 철회 불가)</span>
          <input type="checkbox" checked={consents.termsOfServiceAgreed} disabled readOnly />
        </label>
        <label className={styles.toggleRow}>
          <span>야간 푸시 알림 동의 (이메일 · 최신/관심 논문 등재 알림)</span>
          <input
            type="checkbox"
            checked={consents.nightlyPushAgreed}
            disabled={busy === 'consent'}
            onChange={(e) => void onToggleNightlyPush(e.target.checked)}
            data-testid="mypage-consent-nightly-push"
          />
        </label>
      </section>

      <section className={styles.card} data-testid="mypage-change-password">
        <h2 className={styles.cardTitle}>비밀번호 변경</h2>
        <form
          className={authStyles.form}
          onSubmit={onChangePassword}
          data-testid="mypage-change-password-form"
        >
          {pwError ? (
            <p
              className={authStyles.formError}
              role="alert"
              data-testid="mypage-change-password-error"
            >
              {pwError}
            </p>
          ) : null}
          <AuthField
            id="mypage-current-password"
            label="현재 비밀번호"
            type="password"
            autoComplete="current-password"
            value={curPw}
            onChange={setCurPw}
            testId="mypage-current-password"
          />
          <AuthField
            id="mypage-new-password"
            label="새 비밀번호"
            type="password"
            autoComplete="new-password"
            value={newPw}
            onChange={setNewPw}
            testId="mypage-new-password"
          />
          <button
            type="submit"
            className={authStyles.submit}
            disabled={busy === 'password'}
            data-testid="mypage-change-password-submit"
          >
            비밀번호 변경
          </button>
        </form>
      </section>

      <section className={styles.card} data-testid="mypage-change-email">
        <h2 className={styles.cardTitle}>이메일 변경</h2>
        <form
          className={authStyles.form}
          onSubmit={onRequestEmailChange}
          data-testid="mypage-change-email-form"
        >
          {emailError ? (
            <p
              className={authStyles.formError}
              role="alert"
              data-testid="mypage-change-email-error"
            >
              {emailError}
            </p>
          ) : null}
          {emailNotice ? (
            <p
              className={authStyles.formNotice}
              role="status"
              data-testid="mypage-change-email-notice"
            >
              {emailNotice}
            </p>
          ) : null}
          <AuthField
            id="mypage-new-email"
            label="새 이메일"
            type="email"
            autoComplete="email"
            value={newEmail}
            onChange={setNewEmail}
            testId="mypage-new-email"
          />
          <AuthField
            id="mypage-email-current-password"
            label="현재 비밀번호"
            type="password"
            autoComplete="current-password"
            value={emailCurPw}
            onChange={setEmailCurPw}
            testId="mypage-email-current-password"
          />
          <button
            type="submit"
            className={authStyles.submit}
            disabled={busy === 'email'}
            data-testid="mypage-change-email-submit"
          >
            확인 링크 받기
          </button>
        </form>
      </section>

      <section className={styles.card} data-testid="mypage-account-actions">
        <h2 className={styles.cardTitle}>계정</h2>
        <button
          type="button"
          className={styles.action}
          disabled={busy === 'logout'}
          onClick={() => void onLogout()}
          data-testid="mypage-logout"
        >
          로그아웃
        </button>
        <button
          type="button"
          className={styles.danger}
          disabled={busy === 'withdraw'}
          onClick={() => void onWithdraw()}
          data-testid="mypage-withdraw"
        >
          회원탈퇴
        </button>
      </section>
    </section>
  );
}
