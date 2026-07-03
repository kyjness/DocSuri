import 'server-only';
import type { Transport, TransportRequest, TransportResponse } from './transport';

// HttpTransport (LC-2, P-S1) — SERVER-ONLY.
//
// `import 'server-only'` makes a client-side import a build error: the gateway
// base URL and the httpOnly session cookie never reach the browser bundle
// (SEC-3/12). Forwards the incoming session cookie to the U6 gateway; the token
// lives only in the server<->gateway hop.
//
// Inert until the U6 gateway is deployed — the app runs on MockTransport today.
// Swapping mock -> http is a configuration change (see lib/api/index.ts).

export interface HttpTransportConfig {
  baseUrl: string;
  /** The raw Cookie header captured server-side from the inbound request. */
  cookieHeader?: string;
  /** Server->gateway hop timeout (ms). Defaults to 10000. */
  timeoutMs?: number;
}

export class HttpTransport implements Transport {
  constructor(private readonly config: HttpTransportConfig) {}

  async send(req: TransportRequest): Promise<TransportResponse> {
    const headers: Record<string, string> = {
      ...(req.body !== undefined ? { 'content-type': 'application/json' } : {}),
      ...(req.headers ?? {}),
    };
    if (this.config.cookieHeader) headers['cookie'] = this.config.cookieHeader;

    const res = await fetch(`${this.config.baseUrl}${req.path}`, {
      method: req.method,
      headers,
      body: req.body !== undefined ? JSON.stringify(req.body) : undefined,
      // Never cache personalized/authenticated responses (P-P3).
      cache: 'no-store',
      // The BFF (app/bff/[...path]/route.ts) is the sole caller and never sets req.signal, so
      // this server->gateway hop needs its own timeout: ApiClient's timeout only covers the
      // browser->BFF hop, and without this a gateway hang would pin BFF sockets for ~300s and
      // take down the whole FE (BR-U5-10, NFR-U5-R2).
      signal: AbortSignal.timeout(this.config.timeoutMs ?? 10000),
    });

    let body: unknown = null;
    const text = await res.text();
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
    }
    // Capture Set-Cookie (e.g. the login session cookie) so the BFF can relay it
    // to the browser. getSetCookie() is the spec way to read multiple values.
    const setCookies =
      typeof res.headers.getSetCookie === 'function' ? res.headers.getSetCookie() : [];
    return { status: res.status, body, setCookies };
  }
}
