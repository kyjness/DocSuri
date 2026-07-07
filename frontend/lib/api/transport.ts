// Transport seam (LC-2, BR-U5-19).
//
// ApiClient depends only on this interface. Today it is backed by MockTransport
// (DTO-derived fixtures). When the U6 gateway + U2 real infra land, swap in
// HttpTransport (server-only) via configuration — no component/ApiClient rewrite.

export type TransportMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';

export type BinaryTransportData = Blob | ArrayBuffer | Uint8Array;

export interface BinaryTransportBody {
  kind: 'binary';
  data: BinaryTransportData;
  contentType: string;
}

export function binaryBody(data: BinaryTransportData, contentType: string): BinaryTransportBody {
  return { kind: 'binary', data, contentType };
}

export function isBinaryTransportBody(body: unknown): body is BinaryTransportBody {
  if (!body || typeof body !== 'object') return false;
  const record = body as Record<string, unknown>;
  return record.kind === 'binary' && typeof record.contentType === 'string' && 'data' in record;
}

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
  /** Per-request override for ApiClient's default timeout — long-running LLM pipelines
   * (research/evidence turns) need more than the 8s default (PR #338 후속 발견). */
  timeoutMs?: number;
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
