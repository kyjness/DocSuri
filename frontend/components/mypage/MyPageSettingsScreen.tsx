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
import type { PersonalizationSettings } from '@/types/personalization';
import type { NotionConnectionStatusVM } from '@/lib/api/apiClient';

// MyPageSettingsScreen (U10) — 동의 철회(야간 푸시만 토글, 필수 동의는 읽기 전용) + 비밀번호 변경
// + 이메일 변경(FR-28/BR-A10) + 로그아웃 + 회원탈퇴. 비밀번호 변경·탈퇴·이메일 변경은 현재
// 비밀번호 재인증을 요구한다(감사 H7). 비밀번호 변경 성공 시 백엔드가 전 세션을 무효화하므로
// 로그아웃 후 재로그인 화면으로 보낸다.

type BusyKey =
  | 'consent'
  | 'personalization'
  | 'deletePersonalizationEvents'
  | 'resetPersonalizationProfile'
  | 'notionSave'
  | 'notionDisconnect'
  | 'logout'
  | 'withdraw'
  | 'password'
  | 'email'
  | null;

export function MyPageSettingsScreen() {
  const { signOut } = useSession();
  const { effectiveTheme, setTheme } = useTheme();
  const router = useRouter();
  const [consents, setConsents] = useState<ConsentSettingsVM | null>(null);
  const [personalization, setPersonalization] = useState<PersonalizationSettings | null>(null);
  const [notion, setNotion] = useState<NotionConnectionStatusVM | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [busy, setBusy] = useState<BusyKey>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  // 비밀번호 변경 폼
  const [curPw, setCurPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [pwError, setPwError] = useState<string | null>(null);
  // 이메일 변경 폼
  const [emailCurPw, setEmailCurPw] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [emailError, setEmailError] = useState<string | null>(null);
  const [emailNotice, setEmailNotice] = useState<string | null>(null);
  // Notion 연결 폼
  const [notionToken, setNotionToken] = useState('');
  const [notionParentPageId, setNotionParentPageId] = useState('');
  const [notionError, setNotionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus('loading');
    try {
      const api = getApiClient();
      const consentResult = await api.getConsents();
      setConsents(consentResult);
      try {
        setPersonalization(await api.getPersonalizationSettings());
      } catch {
        setPersonalization(null);
      }
      try {
        const connection = await api.getNotionConnection();
        setNotion(connection);
        setNotionParentPageId(connection.parentPageId ?? '');
      } catch {
        setNotion(null);
      }
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
    setActionNotice(null);
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

  const onTogglePersonalization = (checked: boolean) =>
    withBusy('personalization', async () => {
      const result = await getApiClient().updatePersonalizationEnabled(checked);
      setPersonalization(result);
    });

  const onDeletePersonalizationEvents = () => {
    if (!window.confirm('개인맞춤 행동 로그를 삭제할까요? 이 작업은 되돌릴 수 없습니다.')) return;
    void withBusy('deletePersonalizationEvents', async () => {
      const result = await getApiClient().deletePersonalizationEvents();
      setActionNotice(`개인맞춤 행동 로그 ${result.deletedEvents}건을 삭제했습니다.`);
    });
  };

  const onResetPersonalizationProfile = () => {
    if (!window.confirm('개인맞춤 프로필과 기본값을 초기화할까요?')) return;
    void withBusy('resetPersonalizationProfile', async () => {
      await getApiClient().resetPersonalizationProfile();
      setActionNotice('개인맞춤 프로필을 초기화했습니다.');
    });
  };

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

  const onSaveNotionConnection = (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const token = notionToken.trim();
    const parentPageId = notionParentPageId.trim();
    setNotionError(null);
    if (token.length < 16) {
      setNotionError('Notion 연동 토큰을 입력해 주세요.');
      return;
    }
    if (!/^[0-9a-fA-F-]{32,36}$/.test(parentPageId)) {
      setNotionError('상위 페이지 ID를 등록해야 Notion에 페이지를 만들 수 있습니다.');
      return;
    }
    setBusy('notionSave');
    setActionError(null);
    setActionNotice(null);
    void (async () => {
      try {
        const saved = await getApiClient().saveNotionConnection(token, parentPageId);
        setNotion(saved);
        setNotionToken('');
        setNotionParentPageId(saved.parentPageId ?? parentPageId);
        setActionNotice('Notion 연결을 저장했습니다.');
      } catch (err) {
        setNotionError(
          err instanceof UserFacingError
            ? err.message
            : 'Notion 연결을 저장하지 못했습니다. 다시 시도해 주세요.',
        );
      } finally {
        setBusy(null);
      }
    })();
  };

  const onDisconnectNotion = () => {
    if (!window.confirm('Notion 연결을 해제할까요? 저장된 토큰이 삭제됩니다.')) return;
    setNotionError(null);
    setBusy('notionDisconnect');
    setActionError(null);
    setActionNotice(null);
    void (async () => {
      try {
        await getApiClient().deleteNotionConnection();
        setNotion({ connected: false });
        setNotionToken('');
        setNotionParentPageId('');
        setActionNotice('Notion 연결을 해제했습니다.');
      } catch (err) {
        setNotionError(
          err instanceof UserFacingError
            ? err.message
            : 'Notion 연결을 해제하지 못했습니다. 다시 시도해 주세요.',
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
      {actionNotice ? (
        <p className={styles.notice} role="status" data-testid="mypage-action-notice">
          {actionNotice}
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

      <section className={styles.card} data-testid="mypage-personalization-data">
        <h2 className={styles.cardTitle}>맞춤 서비스</h2>
        <label className={styles.toggleRow}>
          <span>맞춤 서비스 사용</span>
          <input
            type="checkbox"
            checked={personalization?.enabled ?? false}
            disabled={!personalization || busy === 'personalization'}
            onChange={(e) => void onTogglePersonalization(e.target.checked)}
            data-testid="mypage-personalization-enabled"
          />
        </label>
        {!personalization ? (
          <p className={styles.muted} role="status" data-testid="mypage-personalization-unavailable">
            맞춤 서비스 설정을 불러오지 못했습니다.
          </p>
        ) : null}
        <p className={styles.muted}>
          행동 로그 삭제는 원천 기록을 지우고, 프로필 초기화는 분석된 관심사와 기본값을 지웁니다.
        </p>
        <button
          type="button"
          className={styles.danger}
          disabled={!personalization || busy === 'deletePersonalizationEvents'}
          onClick={() => void onDeletePersonalizationEvents()}
          data-testid="mypage-personalization-delete-events"
        >
          행동 로그 삭제
        </button>
        <button
          type="button"
          className={styles.action}
          disabled={!personalization || busy === 'resetPersonalizationProfile'}
          onClick={() => void onResetPersonalizationProfile()}
          data-testid="mypage-personalization-reset-profile"
        >
          개인맞춤 프로필 초기화
        </button>
      </section>

      <section className={styles.card} data-testid="mypage-notion-connection">
        <h2 className={styles.cardTitle}>Notion 연결</h2>
        <p className={styles.muted} data-testid="mypage-notion-status">
          {notion?.connected
            ? `연결됨 · 상위 페이지 ${notion.parentPageId}`
            : '연결된 Notion이 없습니다.'}
        </p>
        <form
          className={authStyles.form}
          onSubmit={onSaveNotionConnection}
          data-testid="mypage-notion-form"
        >
          {notionError ? (
            <p className={authStyles.formError} role="alert" data-testid="mypage-notion-error">
              {notionError}
            </p>
          ) : null}
          <AuthField
            id="mypage-notion-token"
            label={notion?.connected ? '새 Notion 연동 토큰' : 'Notion 연동 토큰'}
            type="password"
            autoComplete="off"
            value={notionToken}
            onChange={setNotionToken}
            testId="mypage-notion-token"
          />
          <AuthField
            id="mypage-notion-parent-page-id"
            label="상위 페이지 ID"
            type="text"
            autoComplete="off"
            value={notionParentPageId}
            onChange={setNotionParentPageId}
            testId="mypage-notion-parent-page-id"
          />
          <button
            type="submit"
            className={authStyles.submit}
            disabled={busy === 'notionSave'}
            data-testid="mypage-notion-save"
          >
            {notion?.connected ? 'Notion 연결 갱신' : 'Notion 연결 저장'}
          </button>
        </form>
        <button
          type="button"
          className={styles.danger}
          disabled={!notion?.connected || busy === 'notionDisconnect'}
          onClick={() => void onDisconnectNotion()}
          data-testid="mypage-notion-disconnect"
        >
          Notion 연결 해제
        </button>
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
