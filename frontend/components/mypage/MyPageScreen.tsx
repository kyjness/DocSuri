'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { getApiClient } from '@/lib/api';
import { StateView } from '../StateView';
import styles from './MyPageScreen.module.css';
import type { SubscriptionDTO } from '@/types/generated';
import type { AccountProfileVM, OrcidProfileVM } from '@/types/mypage';

// MyPageScreen (U10) — top-level menu over the mypage sub-screens. 계정/ORCID는 정보성이라
// 여기 그대로 두고, 관심논문·최근 본 / 내 구독 / 설정은 한 단계 더 들어가는 메뉴 카드로만
// 노출한다(각 상세는 MyPageLibraryScreen/MyPageSubscriptionScreen/MyPageSettingsScreen).

const LOGIN_PROVIDER_LABEL: Record<string, string> = {
  GOOGLE: 'Google',
  ORCID: 'ORCID',
  EMAIL: '이메일',
};

const SUBSCRIPTION_LABEL: Record<string, string> = {
  NONE: '구독 없음',
  ACTIVE: '구독 중 (PREMIUM)',
  CANCELED: '해지 예약',
};

interface LoadedState {
  profile: AccountProfileVM;
  orcid: OrcidProfileVM | null;
  subscription: SubscriptionDTO;
}

export function MyPageScreen() {
  const [data, setData] = useState<LoadedState | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');

  const load = useCallback(async () => {
    setStatus('loading');
    try {
      const client = getApiClient();
      const [profile, subscription] = await Promise.all([
        client.getAccountProfile(),
        client.getSubscription(),
      ]);
      const orcid = profile.loginProvider === 'ORCID' ? await client.getOrcidProfile() : null;
      setData({ profile, orcid, subscription });
      setStatus('ready');
    } catch {
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (status === 'loading') return <StateView kind="loading" title="마이페이지를 불러오는 중…" />;
  if (status === 'error' || !data) return <StateView kind="error" onRetry={() => void load()} />;

  const { profile, orcid, subscription } = data;

  return (
    <section className={styles.screen} data-testid="mypage-screen">
      <section className={styles.card} data-testid="mypage-profile">
        <h2 className={styles.cardTitle}>계정</h2>
        <p>
          로그인 경로:{' '}
          <strong>{LOGIN_PROVIDER_LABEL[profile.loginProvider] ?? profile.loginProvider}</strong>
        </p>
        <p className={styles.muted}>가입일: {new Date(profile.createdAt).toLocaleDateString('ko-KR')}</p>
      </section>

      {orcid ? (
        <section className={styles.card} data-testid="mypage-orcid">
          <h2 className={styles.cardTitle}>ORCID</h2>
          <p>
            {orcid.name}
            {orcid.affiliation ? ` · ${orcid.affiliation}` : ''}
          </p>
          <p className={styles.muted}>{orcid.orcidId}</p>
          {orcid.works.length > 0 ? (
            <ul className={styles.plainList}>
              {orcid.works.map((work) => (
                <li key={work.title}>
                  {work.title}
                  {work.year ? ` (${work.year})` : ''}
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      <Link href="/mypage/library" className={styles.menuCard} data-testid="mypage-menu-library">
        <span>
          <span className={styles.cardTitle}>관심 논문 · 최근 본</span>
          <span className={styles.muted}>저장한 논문과 최근에 본 논문을 모아 봅니다.</span>
        </span>
        <span className={styles.menuArrow} aria-hidden="true">
          ›
        </span>
      </Link>

      <Link
        href="/mypage/subscription"
        className={styles.menuCard}
        data-testid="mypage-menu-subscription"
      >
        <span>
          <span className={styles.cardTitle}>내 구독</span>
          <span className={styles.muted}>
            {SUBSCRIPTION_LABEL[subscription.status] ?? subscription.status}
          </span>
        </span>
        <span className={styles.menuArrow} aria-hidden="true">
          ›
        </span>
      </Link>

      <Link href="/mypage/settings" className={styles.menuCard} data-testid="mypage-menu-settings">
        <span>
          <span className={styles.cardTitle}>설정</span>
          <span className={styles.muted}>동의 항목, 로그아웃, 회원탈퇴</span>
        </span>
        <span className={styles.menuArrow} aria-hidden="true">
          ›
        </span>
      </Link>
    </section>
  );
}
