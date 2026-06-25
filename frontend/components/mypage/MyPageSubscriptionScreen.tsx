'use client';

import { useCallback, useEffect, useState } from 'react';
import { getApiClient } from '@/lib/api';
import { StateView } from '../StateView';
import styles from './MyPageScreen.module.css';
import type { SubscriptionDTO } from '@/types/generated';

// MyPageSubscriptionScreen (U10) — 구독 상세 + PREMIUM 혜택 안내. subscribe/cancel은 REAL
// (backend/modules/mypage, mock billing — see apiClient.ts mypage section).

const SUBSCRIPTION_LABEL: Record<string, string> = {
  NONE: '구독 없음',
  ACTIVE: '구독 중 (PREMIUM)',
  CANCELED: '해지 예약',
};

const PREMIUM_BENEFITS = ['논문 AI 요약 · 번역 무제한 이용', '관심 논문 신규 등재 시 우선 알림'];

// 결제(PG) 미연동 — subscribe/cancel은 mock 빌링이라 실제 결제가 일어나지 않는다. 프로덕션
// (실 API)에서는 가짜 결제 플로우를 노출하지 않도록 버튼을 '결제 준비중'으로 비활성화한다
// (감사 N1). mock 모드(로컬/테스트)에서는 기존 동작 유지 → 구독 플로우 테스트가 그대로 통과한다.
const BILLING_COMING_SOON = Boolean(process.env.NEXT_PUBLIC_DOCSURI_REAL_API);

type BusyKey = 'subscribe' | 'cancel' | null;

export function MyPageSubscriptionScreen() {
  const [subscription, setSubscription] = useState<SubscriptionDTO | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [busy, setBusy] = useState<BusyKey>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus('loading');
    try {
      const result = await getApiClient().getSubscription();
      setSubscription(result);
      setStatus('ready');
    } catch {
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onSubscribe = async () => {
    setBusy('subscribe');
    setActionError(null);
    try {
      setSubscription(await getApiClient().subscribe());
    } catch {
      setActionError('처리하지 못했습니다. 다시 시도해 주세요.');
    } finally {
      setBusy(null);
    }
  };

  const onCancelSubscription = async () => {
    setBusy('cancel');
    setActionError(null);
    try {
      setSubscription(await getApiClient().cancelSubscription());
    } catch {
      setActionError('처리하지 못했습니다. 다시 시도해 주세요.');
    } finally {
      setBusy(null);
    }
  };

  if (status === 'loading') return <StateView kind="loading" title="구독 정보를 불러오는 중…" />;
  if (status === 'error' || !subscription) {
    return <StateView kind="error" onRetry={() => void load()} />;
  }

  return (
    <section className={styles.screen} data-testid="mypage-subscription-screen">
      {actionError ? (
        <p className={styles.error} role="alert" data-testid="mypage-action-error">
          {actionError}
        </p>
      ) : null}

      <section className={styles.card} data-testid="mypage-subscription">
        <h2 className={styles.cardTitle}>내 구독</h2>
        <p>
          상태:{' '}
          <strong data-testid="mypage-subscription-status">
            {SUBSCRIPTION_LABEL[subscription.status] ?? subscription.status}
          </strong>
        </p>
        {subscription.currentPeriodEnd ? (
          <p className={styles.muted}>
            {subscription.status === 'CANCELED' ? '혜택 유지 기한' : '다음 결제일'}:{' '}
            {new Date(subscription.currentPeriodEnd).toLocaleDateString('ko-KR')}
          </p>
        ) : null}
        {BILLING_COMING_SOON ? (
          <button
            type="button"
            className={styles.action}
            disabled
            aria-disabled="true"
            data-testid="mypage-subscription-coming-soon"
          >
            결제 준비중 (출시 예정)
          </button>
        ) : subscription.status === 'ACTIVE' ? (
          <button
            type="button"
            className={styles.action}
            disabled={busy === 'cancel'}
            onClick={() => void onCancelSubscription()}
            data-testid="mypage-subscription-cancel"
          >
            구독 해지
          </button>
        ) : (
          <button
            type="button"
            className={styles.action}
            disabled={busy === 'subscribe'}
            onClick={() => void onSubscribe()}
            data-testid="mypage-subscription-subscribe"
          >
            프리미엄 구독하기
          </button>
        )}
      </section>

      <section className={styles.card} data-testid="mypage-subscription-benefits">
        <h2 className={styles.cardTitle}>PREMIUM 혜택</h2>
        <ul className={styles.plainList}>
          {PREMIUM_BENEFITS.map((benefit) => (
            <li key={benefit}>{benefit}</li>
          ))}
        </ul>
      </section>
    </section>
  );
}
