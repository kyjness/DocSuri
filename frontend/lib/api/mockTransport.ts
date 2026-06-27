// MockTransport (LC-2, BR-U5-19) — serves shared/dtos-derived fixtures so U5
// develops without the U6 gateway / real U2. Search branch is keyword-driven so
// every terminal state is demoable:
//   query contains 없음/empty     -> empty page
//                  기권/abstain    -> abstain
//                  저하/degraded   -> degraded
//                  오류/error      -> 500 (server error)
//                  네트워크/fail   -> thrown (network failure)
//   otherwise                      -> result page
import type { Transport, TransportRequest, TransportResponse } from './transport';
import {
  pageResponse,
  emptyResponse,
  abstainResponse,
  degradedResponse,
  validationErrorResponse,
} from '@/mocks/searchFixtures';
import {
  summaryResponse,
  beginnerSummaryResponse,
  abstractTranslationResponse,
  fullTranslationResponse,
  docModelResponse,
  assetsResponse,
  mockUpsertGlossaryTerm,
  mockListGlossaryTerms,
} from '@/mocks/summarizeFixtures';
import { mockPaperMeta } from '@/mocks/paperFixtures';
import {
  mockSignup,
  mockLogin,
  mockLogout,
  mockCurrentSession,
} from '@/mocks/accountFixtures';
import {
  mockListSaved,
  mockCreateSaved,
  mockDeleteSaved,
  mockListLibrary,
  mockAddLibrary,
  mockRemoveLibrary,
  mockListHistory,
  mockClearHistory,
} from '@/mocks/libraryFixtures';
import { mockCitationTree } from '@/mocks/citationGraphFixtures';
import {
  mockGetSubscription,
  mockSubscribe,
  mockCancelSubscription,
  mockGetAccountProfile,
  mockGetOrcidProfile,
  mockGetRecentlyViewed,
  mockGetConsents,
  mockUpdateConsent,
} from '@/mocks/mypageFixtures';
import type {
  SavedSearchCreateDTO,
  LibraryItemCreateDTO,
} from '@/types/generated';
import type { CitationNode } from '@/types/citationGraph';
import type { BehaviorEventCreate } from '@/types/personalization';

function matches(q: string, ...needles: string[]): boolean {
  const lower = q.toLowerCase();
  return needles.some((n) => lower.includes(n));
}

export class MockTransport implements Transport {
  async send(req: TransportRequest): Promise<TransportResponse> {
    // Small latency so loading states are observable.
    await new Promise((r) => setTimeout(r, 120));

    // Split the (possibly query-bearing) path: collections paginate via ?limit&cursor.
    const qIdx = req.path.indexOf('?');
    const path = qIdx >= 0 ? req.path.slice(0, qIdx) : req.path;
    const sp = new URLSearchParams(qIdx >= 0 ? req.path.slice(qIdx + 1) : '');
    const limit = Number(sp.get('limit') ?? '20') || 20;
    const cursor = sp.get('cursor') ?? undefined;

    const libraryRes = this.routeLibrary(req, path, limit, cursor);
    if (libraryRes) return libraryRes;

    const mypageRes = this.routeMypage(req, path);
    if (mypageRes) return mypageRes;

    if (path === '/api/personalization/events' && req.method === 'POST') {
      void (req.body as BehaviorEventCreate);
      return { status: 200, body: { recorded: true, duplicate: false, reason: 'recorded' } };
    }
    if (path === '/api/personalization/settings' && req.method === 'GET') {
      return {
        status: 200,
        body: {
          userId: 'mock-user',
          enabled: true,
          rawEventsDeletedAt: null,
          profileResetAt: null,
          updatedAt: '2026-06-25T00:00:00Z',
        },
      };
    }
    if (path === '/api/personalization/settings' && req.method === 'PATCH') {
      const body = (req.body ?? {}) as { enabled?: unknown };
      return {
        status: 200,
        body: {
          userId: 'mock-user',
          enabled: Boolean(body.enabled),
          rawEventsDeletedAt: null,
          profileResetAt: null,
          updatedAt: '2026-06-25T00:00:00Z',
        },
      };
    }
    if (path === '/api/personalization/delete-events' && req.method === 'POST') {
      return { status: 200, body: { deletedEvents: 0 } };
    }
    if (path === '/api/personalization/reset-profile' && req.method === 'POST') {
      return { status: 200, body: { status: 'reset' } };
    }

    if (req.path === '/api/search' && req.method === 'POST') {
      const query = String((req.body as { query?: unknown })?.query ?? '');
      if (matches(query, '네트워크', 'fail')) throw new Error('mock network failure');
      if (matches(query, '오류', 'error')) return { status: 500, body: null };
      if (matches(query, '없음', 'empty')) return { status: 200, body: emptyResponse };
      if (matches(query, '기권', 'abstain')) return { status: 200, body: abstainResponse };
      if (matches(query, '저하', 'degraded')) return { status: 200, body: degradedResponse };
      if (matches(query, '유효', 'invalid')) return { status: 400, body: validationErrorResponse };
      return { status: 200, body: pageResponse };
    }

    // U7 summarize/translate (dev preview only) ------------------------------
    if (req.path === '/api/summarize' && req.method === 'POST') {
      const body = (req.body ?? {}) as { task?: string; scope?: string; persona?: string };
      if (body.task === 'translate') {
        return {
          status: 200,
          body: body.scope === 'full' ? fullTranslationResponse : abstractTranslationResponse,
        };
      }
      return {
        status: 200,
        body: body.persona === 'beginner' ? beginnerSummaryResponse : summaryResponse,
      };
    }
    if (req.path === '/api/glossary' && req.method === 'GET') {
      return { status: 200, body: { status: 'ok', terms: mockListGlossaryTerms() } };
    }
    if (req.path === '/api/glossary' && req.method === 'POST') {
      const body = (req.body ?? {}) as { termFrom?: unknown; termTo?: unknown };
      const termFrom = String(body.termFrom ?? '').trim();
      const termTo = String(body.termTo ?? '').trim();
      if (!termFrom || !termTo) return { status: 400, body: { message: '용어를 입력해 주세요.' } };
      return { status: 201, body: mockUpsertGlossaryTerm(termFrom, termTo) };
    }
    if (/^\/api\/papers\/[^/]+\/assets$/.test(path) && req.method === 'GET') {
      return { status: 200, body: assetsResponse };
    }
    if (/^\/api\/papers\/[^/]+\/doc-model$/.test(path) && req.method === 'GET') {
      return { status: 200, body: docModelResponse };
    }
    const citationTree = path.match(/^\/api\/papers\/([^/]+)\/citation-tree$/);
    if (citationTree && req.method === 'GET') {
      return {
        status: 200,
        body: mockCitationTree(
          decodeURIComponent(citationTree[1]),
          sp.get('expandNodeId') ?? undefined,
        ),
      };
    }
    const citationSave = path.match(/^\/api\/papers\/([^/]+)\/citation-tree\/save$/);
    if (citationSave && req.method === 'POST') {
      const node = ((req.body ?? {}) as { node?: CitationNode }).node;
      if (!node?.saveable || !node.arxivId) {
        return { status: 422, body: { message: '저장할 수 없는 인용입니다.' } };
      }
      return {
        status: 201,
        body: mockAddLibrary({
          arXivId: node.arxivId,
          meta: {
            title: node.title,
            authors: [],
            year: node.year ?? null,
            arxivId: node.arxivId,
            abstractSnippet: null,
            arxivUrl: node.url ?? null,
          },
        }),
      };
    }
    const metaMatch = path.match(/^\/api\/papers\/([^/]+)$/);
    if (metaMatch && req.method === 'GET') {
      return { status: 200, body: mockPaperMeta(decodeURIComponent(metaMatch[1])) };
    }

    if (req.path === '/auth/signup' && req.method === 'POST') {
      return { status: 201, body: mockSignup() };
    }
    if (req.path === '/auth/login' && req.method === 'POST') {
      // Mirror the real backend: set the (mock) session and return {status,message}
      // only — the SessionInfo is read back via GET /auth/session (SEC-12).
      const email = String((req.body as { email?: unknown })?.email ?? 'mock@docsuri.dev');
      mockLogin(email);
      return { status: 200, body: { status: 'success', message: '로그인에 성공했습니다.' } };
    }
    if (req.path === '/auth/logout' && req.method === 'POST') {
      mockLogout();
      return { status: 204, body: null };
    }
    if (req.path === '/auth/account/delete' && req.method === 'POST') {
      // REAL U3 soft-delete (withdrawAccount) — mock clears the session like a logout.
      mockLogout();
      return { status: 204, body: null };
    }
    if (req.path === '/auth/session' && req.method === 'GET') {
      const session = mockCurrentSession();
      return session ? { status: 200, body: session } : { status: 401, body: null };
    }

    return { status: 404, body: null };
  }

  // U4 saved-search / library / history routes. Returns null when `path` is not a
  // library route so the caller falls through to the auth/search branches.
  private routeLibrary(
    req: TransportRequest,
    path: string,
    limit: number,
    cursor?: string,
  ): TransportResponse | null {
    // Saved searches ----------------------------------------------------------
    if (path === '/library/saved-searches') {
      if (req.method === 'GET') return { status: 200, body: mockListSaved(limit, cursor) };
      if (req.method === 'POST') {
        return { status: 201, body: mockCreateSaved(req.body as SavedSearchCreateDTO) };
      }
    }
    const savedRerun = path.match(/^\/library\/saved-searches\/([^/]+)\/rerun$/);
    if (savedRerun && req.method === 'POST') return { status: 200, body: pageResponse };
    const savedId = path.match(/^\/library\/saved-searches\/([^/]+)$/);
    if (savedId && req.method === 'DELETE') {
      return mockDeleteSaved(decodeURIComponent(savedId[1]))
        ? { status: 204, body: null }
        : { status: 404, body: null };
    }

    // Library -----------------------------------------------------------------
    if (path === '/library/items') {
      if (req.method === 'GET') return { status: 200, body: mockListLibrary(limit, cursor) };
      if (req.method === 'POST') {
        return { status: 201, body: mockAddLibrary(req.body as LibraryItemCreateDTO) };
      }
    }
    const libId = path.match(/^\/library\/items\/([^/]+)$/);
    if (libId && req.method === 'DELETE') {
      return mockRemoveLibrary(decodeURIComponent(libId[1]))
        ? { status: 204, body: null }
        : { status: 404, body: null };
    }

    // History -----------------------------------------------------------------
    if (path === '/library/history') {
      if (req.method === 'GET') return { status: 200, body: mockListHistory(limit, cursor) };
      if (req.method === 'DELETE') {
        mockClearHistory();
        return { status: 204, body: null };
      }
    }
    const histRerun = path.match(/^\/library\/history\/([^/]+)\/rerun$/);
    if (histRerun && req.method === 'POST') return { status: 200, body: pageResponse };

    return null;
  }

  // U10 my-page routes. Subscription mirrors the REAL backend module (mock-only, no PG/
  // billing). account-profile/orcid-profile/recently-viewed/consents are MOCK-ONLY placeholders
  // for menu items whose real U3/U9 contract does not exist yet. Withdrawal is NOT here — it
  // calls the REAL U3 POST /auth/account/delete (handled in the auth branch above).
  private routeMypage(req: TransportRequest, path: string): TransportResponse | null {
    if (path === '/mypage/subscription') {
      if (req.method === 'GET') return { status: 200, body: mockGetSubscription() };
      if (req.method === 'POST') return { status: 201, body: mockSubscribe() };
    }
    if (path === '/mypage/subscription/cancel' && req.method === 'POST') {
      return { status: 200, body: mockCancelSubscription() };
    }
    if (path === '/mypage/account-profile' && req.method === 'GET') {
      return { status: 200, body: mockGetAccountProfile() };
    }
    if (path === '/mypage/orcid-profile' && req.method === 'GET') {
      const profile = mockGetOrcidProfile();
      return profile ? { status: 200, body: profile } : { status: 404, body: null };
    }
    if (path === '/mypage/recently-viewed' && req.method === 'GET') {
      return { status: 200, body: { items: mockGetRecentlyViewed() } };
    }
    if (path === '/mypage/consents') {
      if (req.method === 'GET') return { status: 200, body: mockGetConsents() };
      if (req.method === 'POST') {
        const body = (req.body ?? {}) as { nightlyPushAgreed?: unknown };
        return { status: 200, body: mockUpdateConsent(Boolean(body.nightlyPushAgreed)) };
      }
    }
    return null;
  }
}
