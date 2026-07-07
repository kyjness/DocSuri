import { NextResponse, type NextRequest } from 'next/server';
import { HttpTransport } from '@/lib/api/httpTransport';
import { MockTransport } from '@/lib/api/mockTransport';
import { binaryBody, type Transport, type TransportMethod } from '@/lib/api/transport';

// BFF (Backend-for-Frontend) — the server-side seam between the browser and the
// U6 gateway (LC-2, P-S1, SEC-3/12).
//
// Client components call the same-origin RouteHandlerTransport (`/bff/*`), which
// reaches this catch-all. Here — and ONLY here — the gateway URL is known and the
// inbound httpOnly session cookie is forwarded to the gateway. The token never
// enters client JS. Transport is chosen by DOCSURI_GATEWAY_URL: set => the real
// gateway (HttpTransport), unset => mock (so previews work without infra). The
// gateway's Set-Cookie (e.g. the login session) is relayed back to the browser.
//
// NOTE: the assembled backend must resolve the session cookie into an authenticated
// principal (request.state.principal) for /library/* and /api/search; that gateway
// auth-injection is tracked separately (backend coordination zone, system-infra step).

const SSE_PROXY_TIMEOUT_MS = 15000;
// evidence 턴(OpenSearch 검색 + 다건 S3 DocModel 로드 + Bedrock 추출)은 동기로 30~90초
// 걸린다 — HttpTransport 기본 10초로는 백엔드가 정상 완료돼도 이 서버->게이트웨이 홉이
// 먼저 끊겨 504로 보인다(ApiClient의 90초 타임아웃과는 별개 레이어, PR #338 후속 발견).
const EVIDENCE_GATEWAY_TIMEOUT_MS = 90000;

function isEvidenceHeavyPath(upstreamPath: string): boolean {
  return (
    upstreamPath.startsWith('/api/research/jobs') || upstreamPath.startsWith('/api/evidence/turns')
  );
}

function buildTransport(req: NextRequest, upstreamPath: string): Transport | null {
  const baseUrl = process.env.DOCSURI_GATEWAY_URL;
  if (baseUrl) {
    return new HttpTransport({
      baseUrl,
      cookieHeader: req.headers.get('cookie') ?? undefined,
      timeoutMs: isEvidenceHeavyPath(upstreamPath) ? EVIDENCE_GATEWAY_TIMEOUT_MS : undefined,
    });
  }
  if (process.env.NODE_ENV === 'production' && process.env.DOCSURI_BFF_ALLOW_MOCK !== '1') {
    return null;
  }
  return new MockTransport();
}

function forwardedHeaders(req: NextRequest): Record<string, string> | undefined {
  const recaptchaToken = req.headers.get('x-recaptcha-token');
  return recaptchaToken ? { 'X-Recaptcha-Token': recaptchaToken } : undefined;
}

function isNoveltyEventStream(method: TransportMethod, path: string[]): boolean {
  return (
    method === 'GET' &&
    path.length === 5 &&
    path[0] === 'api' &&
    path[1] === 'novelty' &&
    path[2] === 'jobs' &&
    path[4] === 'events'
  );
}

function isPdfBody(req: NextRequest): boolean {
  return (
    req.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase() === 'application/pdf'
  );
}

async function proxyEventStream(req: NextRequest, upstreamPath: string): Promise<NextResponse> {
  const baseUrl = process.env.DOCSURI_GATEWAY_URL;
  if (!baseUrl) {
    if (process.env.NODE_ENV === 'production' && process.env.DOCSURI_BFF_ALLOW_MOCK !== '1') {
      return NextResponse.json(
        { message: '일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.' },
        { status: 503 },
      );
    }
    return new NextResponse(null, {
      status: 204,
      headers: {
        'cache-control': 'no-store',
        'content-type': 'text/event-stream',
      },
    });
  }

  const headers = new Headers({ accept: 'text/event-stream' });
  const cookie = req.headers.get('cookie');
  if (cookie) headers.set('cookie', cookie);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SSE_PROXY_TIMEOUT_MS);
  try {
    const res = await fetch(`${baseUrl}${upstreamPath}`, {
      method: 'GET',
      headers,
      cache: 'no-store',
      signal: controller.signal,
    });
    const out = new NextResponse(res.body, {
      status: res.status,
      headers: {
        'cache-control': 'no-store',
        'content-type': res.headers.get('content-type') ?? 'text/event-stream',
      },
    });
    const getSetCookie = (res.headers as Headers & { getSetCookie?: () => string[] }).getSetCookie;
    const cookies = getSetCookie?.call(res.headers) ?? [];
    const fallbackCookie = res.headers.get('set-cookie');
    for (const setCookie of cookies.length ? cookies : fallbackCookie ? [fallbackCookie] : []) {
      out.headers.append('set-cookie', setCookie);
    }
    return out;
  } catch {
    return NextResponse.json(
      { message: '일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.' },
      { status: 502 },
    );
  } finally {
    clearTimeout(timer);
  }
}

async function proxy(req: NextRequest, path: string[]): Promise<NextResponse> {
  const method = req.method as TransportMethod;
  const upstreamPath = `/${path.join('/')}${req.nextUrl.search}`;

  if (isNoveltyEventStream(method, path)) {
    return proxyEventStream(req, upstreamPath);
  }

  let body: unknown;
  if (method !== 'GET' && method !== 'DELETE') {
    if (isPdfBody(req)) {
      body = binaryBody(new Uint8Array(await req.arrayBuffer()), 'application/pdf');
    } else {
      const text = await req.text();
      if (text) {
        try {
          body = JSON.parse(text);
        } catch {
          return NextResponse.json({ message: '잘못된 요청 형식입니다.' }, { status: 400 });
        }
      }
    }
  }

  const transport = buildTransport(req, upstreamPath);
  if (!transport) {
    return NextResponse.json(
      { message: '일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.' },
      { status: 503 },
    );
  }

  let res;
  try {
    res = await transport.send({
      method,
      path: upstreamPath,
      body,
      headers: forwardedHeaders(req),
      idempotent: method === 'GET',
    });
  } catch {
    // Gateway hang/timeout (HttpTransport AbortSignal.timeout) — fail fast so a slow
    // upstream can't pin BFF sockets into an FE-wide outage (BR-U5-10, NFR-U5-R2).
    return NextResponse.json(
      { message: '요청 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.' },
      { status: 504 },
    );
  }

  // 204 No Content / 304 Not Modified must not carry a body — NextResponse.json() always
  // attaches one, and the Response constructor then throws ("Invalid response status code
  // 204"), turning a successful upstream DELETE (un-bookmark, delete saved search, clear
  // history) into a 500. Relay those status-only, still forwarding any Set-Cookie.
  const out =
    res.status === 204 || res.status === 304
      ? new NextResponse(null, { status: res.status })
      : NextResponse.json(res.body ?? null, { status: res.status });
  for (const cookie of res.setCookies ?? []) out.headers.append('set-cookie', cookie);
  return out;
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return proxy(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return proxy(req, (await ctx.params).path);
}
export async function PUT(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return proxy(req, (await ctx.params).path);
}
export async function PATCH(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return proxy(req, (await ctx.params).path);
}
export async function DELETE(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return proxy(req, (await ctx.params).path);
}
