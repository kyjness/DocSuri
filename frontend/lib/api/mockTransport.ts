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
  withWeakOverlay,
} from '@/mocks/summarizeFixtures';
import { mockPaperMeta } from '@/mocks/paperFixtures';
import { mockSignup, mockLogin, mockLogout, mockCurrentSession } from '@/mocks/accountFixtures';
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
import {
  mockDeleteAgentSession,
  mockListAgentSessions,
  mockLoadAgentSession,
  mockSendAgentMessage,
} from '@/mocks/agentFixtures';
import type { SavedSearchCreateDTO, LibraryItemCreateDTO } from '@/types/generated';
import type { CitationNode } from '@/types/citationGraph';
import type { BehaviorEventCreate } from '@/types/personalization';
import type {
  AgentAttachment,
  AgentMessage,
  AgentSessionSnapshot,
  AgentSessionSummary,
  AgentTimelineEvent,
} from '@/lib/agentChat/types';

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

    const agentRes = this.routeAgent(req, path);
    if (agentRes) return agentRes;

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
          body:
            body.scope === 'full'
              ? withWeakOverlay(fullTranslationResponse) // reflect applied 원어 유지 terms in dev
              : abstractTranslationResponse,
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
      const body = (req.body ?? {}) as {
        termFrom?: unknown;
        termTo?: unknown;
        promptEnforced?: unknown;
      };
      const termFrom = String(body.termFrom ?? '').trim();
      const termTo = String(body.termTo ?? '').trim();
      const promptEnforced = body.promptEnforced === true; // strict boolean (mirror the backend)
      if (!termFrom || !termTo) return { status: 400, body: { message: '용어를 입력해 주세요.' } };
      return { status: 201, body: mockUpsertGlossaryTerm(termFrom, termTo, promptEnforced) };
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

    // U3 auth recourse/lifecycle endpoints (BR-U5-19 mock-first parity) — the real backend
    // returns a generic/enumeration-safe success for all of these, so the mock mirrors that
    // shape rather than modeling token validity. `path` is already query-stripped (see the
    // top of `send`), so verify-email's `?token=...` doesn't need separate handling here.
    if (path === '/auth/verify-email' && req.method === 'GET') {
      return { status: 200, body: null };
    }
    if (path === '/auth/resend-verification' && req.method === 'POST') {
      return { status: 200, body: null };
    }
    if (path === '/auth/password-reset/request' && req.method === 'POST') {
      return { status: 200, body: null };
    }
    if (path === '/auth/password-reset/confirm' && req.method === 'POST') {
      return { status: 200, body: null };
    }
    if (path === '/auth/change-password' && req.method === 'POST') {
      return { status: 200, body: null };
    }
    if (path === '/auth/email-change/request' && req.method === 'POST') {
      return { status: 200, body: null };
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

  private routeAgent(req: TransportRequest, path: string): TransportResponse | null {
    if (path === '/api/research/jobs' && req.method === 'GET') {
      return { status: 200, body: { jobs: mockListAgentSessions('evidence').map(researchJob) } };
    }
    if (path === '/api/novelty/jobs' && req.method === 'GET') {
      return { status: 200, body: { jobs: mockListAgentSessions('novelty').map(noveltyJob) } };
    }
    if (path === '/api/research/jobs' && req.method === 'POST') {
      const body = req.body as { content?: string; attachments?: AgentAttachment[] };
      const result = mockSendAgentMessage(`agent-evidence-${Date.now()}`, {
        content: String(body.content ?? ''),
        mode: 'evidence',
        attachments: body.attachments,
      });
      return { status: 201, body: { jobId: result.session.id, state: 'active' } };
    }
    if (path === '/api/novelty/jobs' && req.method === 'POST') {
      const body = req.body as {
        topic?: string;
      };
      const result = mockSendAgentMessage(`agent-novelty-${Date.now()}`, {
        content: String(body.topic ?? ''),
        mode: 'novelty',
      });
      return { status: 201, body: { jobId: result.session.id, state: 'queued' } };
    }
    const research = path.match(/^\/api\/research\/jobs\/([^/]+)$/);
    if (research && req.method === 'GET') {
      const snapshot = mockLoadAgentSession(decodeURIComponent(research[1]));
      return snapshot
        ? {
            status: 200,
            body: {
              job: researchJob(snapshot.session),
              messages: snapshot.messages.map(backendMessage),
            },
          }
        : { status: 404, body: null };
    }
    if (research && req.method === 'DELETE') {
      return mockDeleteAgentSession(decodeURIComponent(research[1]))
        ? { status: 204, body: null }
        : { status: 404, body: null };
    }
    const researchMessage = path.match(/^\/api\/research\/jobs\/([^/]+)\/messages$/);
    if (researchMessage && req.method === 'POST') {
      const body = req.body as { content?: string; attachments?: AgentAttachment[] };
      const result = mockSendAgentMessage(decodeURIComponent(researchMessage[1]), {
        content: String(body.content ?? ''),
        mode: 'evidence',
        attachments: body.attachments,
      });
      return { status: 201, body: backendMessage(result.messages.at(-1)!) };
    }
    const novelty = path.match(/^\/api\/novelty\/jobs\/([^/]+)$/);
    if (novelty && req.method === 'GET') {
      const snapshot = mockLoadAgentSession(decodeURIComponent(novelty[1]));
      return snapshot
        ? {
            status: 200,
            body: {
              job: noveltyJob(snapshot.session),
              events: snapshot.events.map(noveltyEvent),
            },
          }
        : { status: 404, body: null };
    }
    if (novelty && req.method === 'DELETE') {
      return mockDeleteAgentSession(decodeURIComponent(novelty[1]))
        ? { status: 204, body: null }
        : { status: 404, body: null };
    }
    const noveltyResult = path.match(/^\/api\/novelty\/jobs\/([^/]+)\/result$/);
    if (noveltyResult && req.method === 'GET') {
      const snapshot = mockLoadAgentSession(decodeURIComponent(noveltyResult[1]));
      return {
        status: snapshot ? 200 : 404,
        body: snapshot
          ? {
              job: noveltyJob(snapshot.session),
              artifacts: noveltyArtifacts(snapshot),
            }
          : null,
      };
    }
    const noveltyMessages = path.match(/^\/api\/novelty\/jobs\/([^/]+)\/messages$/);
    if (noveltyMessages && req.method === 'GET') {
      const snapshot = mockLoadAgentSession(decodeURIComponent(noveltyMessages[1]));
      return {
        status: snapshot ? 200 : 404,
        body: snapshot ? { messages: snapshot.messages.map(backendMessage) } : null,
      };
    }
    if (noveltyMessages && req.method === 'POST') {
      const body = req.body as { content?: string; attachments?: AgentAttachment[] };
      const result = mockSendAgentMessage(decodeURIComponent(noveltyMessages[1]), {
        content: String(body.content ?? ''),
        mode: 'novelty',
        attachments: body.attachments,
      });
      return { status: 201, body: backendMessage(result.messages.at(-1)!) };
    }
    return null;
  }
}

function researchJob(session: AgentSessionSummary) {
  return {
    jobId: session.id,
    title: session.title,
    state: session.state === 'completed' || session.state === 'failed' ? session.state : 'active',
    updatedAt: session.updatedAt,
    createdAt: session.updatedAt,
  };
}

function noveltyJob(session: AgentSessionSummary) {
  return {
    jobId: session.id,
    inputType: 'natural_language',
    topic: session.title,
    state: session.state === 'idle' ? 'queued' : session.state,
    progressPercent: session.state === 'completed' || session.state === 'degraded' ? 100 : 0,
    exportStatus: 'not_requested',
    updatedAt: session.updatedAt,
    createdAt: session.updatedAt,
    completedAt: null,
  };
}

function backendMessage(message: AgentMessage) {
  return {
    messageId: message.id,
    role: message.role === 'agent' ? 'assistant' : message.role,
    content: message.content,
    attachments: message.attachments ?? [],
    createdAt: message.createdAt,
  };
}

function noveltyEvent(event: AgentTimelineEvent) {
  return {
    eventId: event.id,
    state: event.stage,
    message: event.label,
    progressPercent: event.sequence ? event.sequence * 25 : 0,
    payload: eventPayload(event),
    createdAt: '2026-07-01T00:00:00Z',
  };
}

function eventPayload(event: AgentTimelineEvent) {
  const payload: Record<string, unknown> = event.detail ? { detail: event.detail } : {};
  if (event.stage === 'corpus') {
    return { ...payload, source: 'corpus', query: 'RAG 평가 자동화', resultCount: 3 };
  }
  if (event.stage === 'external') {
    return {
      ...payload,
      source: 'github,dataset',
      query: 'RAG evaluation automation',
      resultCount: 2,
      degradedReasons: event.state === 'degraded' ? ['dataset adapter degraded'] : undefined,
    };
  }
  return payload;
}

function noveltyArtifacts(snapshot: AgentSessionSnapshot) {
  const now = snapshot.session.updatedAt;
  return [
    {
      artifactId: `${snapshot.session.id}-ideas`,
      jobId: snapshot.session.id,
      kind: 'novelty_candidates',
      title: 'Novelty candidates',
      objectKey: `mock/${snapshot.session.id}/ideas.json`,
      payload: {
        items: [
          {
            title: '도메인 지식 기반 실패 유형 분해',
            evidenceStatus: 'supported',
            sourceRefs: ['mock:corpus'],
          },
        ],
      },
      createdAt: now,
    },
    {
      artifactId: `${snapshot.session.id}-plan`,
      jobId: snapshot.session.id,
      kind: 'experiment_plan',
      title: 'Experiment plan',
      objectKey: `mock/${snapshot.session.id}/plan.json`,
      payload: {
        researchQuestion: snapshot.session.title,
        noveltyAngle: '유사 연구 대비 실패 유형을 더 세밀하게 분해한다.',
        hypotheses: ['실패 유형 분해가 RAG 평가 재현성을 높인다.'],
        baselines: ['기존 RAG 평가 벤치마크'],
        procedure: ['동일 데이터셋에서 baseline과 제안 방법을 비교한다.'],
        datasets: ['도메인별 공개 QA 데이터셋'],
        metrics: ['baseline delta', 'evidence coverage'],
        resources: ['공개 데이터셋', '평가 스크립트'],
        risks: ['dataset mismatch'],
        evidenceStatus: 'supported',
        sourceRefs: ['mock:corpus'],
      },
      createdAt: now,
    },
  ];
}
