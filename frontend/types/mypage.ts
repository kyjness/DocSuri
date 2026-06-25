/* Mock-only view models for U10 My Page menu items that are NOT yet backed by a real U3/U9
 * contract — the user is implementing U3's OAuth/profile/consent/withdrawal columns
 * separately. Hand-authored (NOT generated; no shared/dtos schema exists for these yet,
 * mirrors the paperMeta.ts/glossary.ts/citationGraph.ts provisional-type pattern). Served by
 * MockTransport (frontend/mocks/mypageFixtures.ts) until U3 ships the real endpoints. */

export type LoginProvider = 'GOOGLE' | 'ORCID' | 'EMAIL';

/** 로그인 경로 + 가입날짜. */
export interface AccountProfileVM {
  loginProvider: LoginProvider;
  createdAt: string;
}

export interface OrcidWorkVM {
  title: string;
  year: number | null;
}

/** ORCID 무료 API 공개 레코드 (이름/소속/저작물). loginProvider !== 'ORCID'면 호출하지 않는다. */
export interface OrcidProfileVM {
  orcidId: string;
  name: string;
  affiliation: string | null;
  works: OrcidWorkVM[];
}

/** 최근 본 논문. U9 paper_opened 이벤트가 구현되기 전까지 mock. */
export interface RecentlyViewedItemVM {
  arxivId: string;
  title: string;
  viewedAt: string;
}

/** 동의 항목. privacyPolicy/termsOfService는 가입 시 필수 동의(철회 불가) — nightlyPush만
 * 선택 동의로 토글 가능. 알림은 이메일 발송, 내용은 최신/관심 논문 등재 알림. */
export interface ConsentSettingsVM {
  privacyPolicyAgreed: boolean;
  termsOfServiceAgreed: boolean;
  nightlyPushAgreed: boolean;
}
