import {
  isBinaryTransportBody,
  type Transport,
  type TransportRequest,
  type TransportResponse,
} from './transport';

// RouteHandlerTransport (LC-2, P-S1) — CLIENT-SAFE.
//
// Client components must never hold the gateway URL or read the httpOnly session
// cookie. So every call is routed through the same-origin Next.js BFF (`/bff/*`,
// app/bff/[...path]/route.ts): the browser auto-attaches the httpOnly cookie for
// the same-origin request, and the BFF forwards it to the U6 gateway server-side
// (SEC-3/12). Mock<->real is decided inside the BFF (by DOCSURI_GATEWAY_URL), so
// this transport is identical in both modes.

export class RouteHandlerTransport implements Transport {
  constructor(private readonly basePath: string = '/bff') {}

  async send(req: TransportRequest): Promise<TransportResponse> {
    const requestBody = req.body;
    const hasBody = requestBody !== undefined;
    const binary = isBinaryTransportBody(requestBody);
    const res = await fetch(`${this.basePath}${req.path}`, {
      method: req.method,
      headers: {
        ...(hasBody
          ? { 'content-type': binary ? requestBody.contentType : 'application/json' }
          : {}),
        ...(req.headers ?? {}),
      },
      body: hasBody ? (binary ? requestBody.data : JSON.stringify(requestBody)) : undefined,
      // Same-origin so the httpOnly session cookie rides along; never cache
      // authenticated/personalized responses (P-P3).
      credentials: 'same-origin',
      cache: 'no-store',
      signal: req.signal,
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
    // The BFF already relayed any Set-Cookie to the browser; the client transport
    // does not need (and must not expose) cookie material.
    return { status: res.status, body };
  }
}
