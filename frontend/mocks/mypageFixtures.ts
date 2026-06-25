// Mock fixtures for U10 My Page (MockTransport backing). Subscription mirrors the REAL
// backend module (backend/modules/mypage) so dev/test behavior matches production (mock or
// not — Q10: no real PG/billing either way). The rest (account profile / ORCID / recently
// viewed / consents) are MOCK-ONLY placeholders for menu items whose real U3/U9 contract
// does not exist yet.
import type { SubscriptionDTO } from '@/types/generated';
import type {
  AccountProfileVM,
  ConsentSettingsVM,
  OrcidProfileVM,
  RecentlyViewedItemVM,
} from '@/types/mypage';

const BILLING_PERIOD_MS = 30 * 24 * 60 * 60 * 1000;

let subscription: SubscriptionDTO = { plan: 'FREE', status: 'NONE' };

export function mockGetSubscription(): SubscriptionDTO {
  return subscription;
}

export function mockSubscribe(): SubscriptionDTO {
  if (subscription.status === 'ACTIVE') return subscription; // idempotent — already active
  const now = new Date();
  subscription = {
    plan: 'PREMIUM',
    status: 'ACTIVE',
    startedAt: subscription.startedAt ?? now.toISOString(),
    currentPeriodEnd: new Date(now.getTime() + BILLING_PERIOD_MS).toISOString(),
  };
  return subscription;
}

export function mockCancelSubscription(): SubscriptionDTO {
  if (subscription.status !== 'ACTIVE') return subscription; // idempotent no-op
  subscription = { ...subscription, status: 'CANCELED', canceledAt: new Date().toISOString() };
  return subscription;
}

export function resetMypageFixtures(): void {
  subscription = { plan: 'FREE', status: 'NONE' };
  consents = { privacyPolicyAgreed: true, termsOfServiceAgreed: true, nightlyPushAgreed: false };
}

// 로그인 경로 + 가입날짜 (U3가 OAuth/계정 컬럼을 붙이기 전까지 mock — 고정값).
const accountProfile: AccountProfileVM = {
  loginProvider: 'ORCID',
  createdAt: '2026-03-02T00:00:00.000Z',
};

export function mockGetAccountProfile(): AccountProfileVM {
  return accountProfile;
}

// ORCID 무료 API 공개 레코드 — loginProvider === 'ORCID'일 때만 호출된다.
const orcidProfile: OrcidProfileVM = {
  orcidId: '0000-0002-1825-0097',
  name: '박지훈',
  affiliation: 'DocSuri AI Lab',
  works: [
    { title: 'Attention Is All You Need', year: 2017 },
    { title: 'Diffusion Models for Protein Structure Prediction', year: 2024 },
  ],
};

export function mockGetOrcidProfile(): OrcidProfileVM | null {
  return accountProfile.loginProvider === 'ORCID' ? orcidProfile : null;
}

// 최근 본 논문 — U9 paper_opened 이벤트 구현 전까지 mock.
const recentlyViewed: RecentlyViewedItemVM[] = [
  {
    arxivId: '1706.03762',
    title: 'Attention Is All You Need',
    viewedAt: '2026-06-23T09:00:00.000Z',
  },
  {
    arxivId: '2401.00001',
    title: 'Diffusion Models for Protein Structure Prediction',
    viewedAt: '2026-06-22T15:30:00.000Z',
  },
];

export function mockGetRecentlyViewed(): RecentlyViewedItemVM[] {
  return recentlyViewed;
}

// 동의 항목 — 개인정보처리방침/이용약관은 필수(고정 true), 야간 푸시만 선택 토글.
let consents: ConsentSettingsVM = {
  privacyPolicyAgreed: true,
  termsOfServiceAgreed: true,
  nightlyPushAgreed: false,
};

export function mockGetConsents(): ConsentSettingsVM {
  return consents;
}

export function mockUpdateConsent(nightlyPushAgreed: boolean): ConsentSettingsVM {
  consents = { ...consents, nightlyPushAgreed };
  return consents;
}
