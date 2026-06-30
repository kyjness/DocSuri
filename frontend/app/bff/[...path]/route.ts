import { NextResponse, type NextRequest } from 'next/server';
import { HttpTransport } from '@/lib/api/httpTransport';
import { MockTransport } from '@/lib/api/mockTransport';
import type { Transport, TransportMethod } from '@/lib/api/transport';

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

function buildTransport(req: NextRequest): Transport {
  const baseUrl = process.env.DOCSURI_GATEWAY_URL;
  if (baseUrl) {
    return new HttpTransport({ baseUrl, cookieHeader: req.headers.get('cookie') ?? undefined });
  }
  return new MockTransport();
}

function forwardedHeaders(req: NextRequest): Record<string, string> | undefined {
  const recaptchaToken = req.headers.get('x-recaptcha-token');
  return recaptchaToken ? { 'X-Recaptcha-Token': recaptchaToken } : undefined;
}

async function proxy(req: NextRequest, path: string[]): Promise<NextResponse> {
  const method = req.method as TransportMethod;
  const upstreamPath = `/${path.join('/')}${req.nextUrl.search}`;

  let body: unknown;
  if (method !== 'GET' && method !== 'DELETE') {
    const text = await req.text();
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        return NextResponse.json({ message: '잘못된 요청 형식입니다.' }, { status: 400 });
      }
    }
  }

  const res = await buildTransport(req).send({
    method,
    path: upstreamPath,
    body,
    headers: forwardedHeaders(req),
    idempotent: method === 'GET',
  });

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
export async function PATCH(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return proxy(req, (await ctx.params).path);
}
export async function DELETE(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return proxy(req, (await ctx.params).path);
}
