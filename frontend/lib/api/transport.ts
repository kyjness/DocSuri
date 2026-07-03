// Transport seam (LC-2, BR-U5-19).
//
// ApiClient depends only on this interface. Today it is backed by MockTransport
// (DTO-derived fixtures). When the U6 gateway + U2 real infra land, swap in
// HttpTransport (server-only) via configuration — no component/ApiClient rewrite.

export type TransportMethod = 'GET' | 'POST' | 'DELETE' | 'PATCH';

export interface TransportRequest {
  method: TransportMethod;
  path: string;
  body?: unknown;
  headers?: Record<string, string>;
  /** Safe to retry once on a transient failure (P-R1). */
  idempotent: boolean;
  /** Whether a transient failure may be retried (P-R1). Defaults to `idempotent`.
   * Set false on idempotent-for-dedup but non-retry-safe calls (e.g. cost-bearing LLM POSTs). */
  retryable?: boolean;
  /** Abort signal for the in-flight request; ApiClient wires it to the per-attempt timeout so a
   * timed-out request is actually cancelled, not just abandoned (BR-U5-10). */
  signal?: AbortSignal;
}

export interface TransportResponse {
  status: number;
  body: unknown;
  /**
   * Upstream Set-Cookie header values, if any (e.g. the session cookie minted by
   * POST /auth/login). The server-side BFF forwards these to the browser; the
   * token itself never enters client JS (SEC-3/12). Absent on most responses.
   */
  setCookies?: string[];
}

export interface Transport {
  send(req: TransportRequest): Promise<TransportResponse>;
}
