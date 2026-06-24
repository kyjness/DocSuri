// ApiClient factory (BR-U5-19).
//
// Selects the transport by configuration. Mock-first by default (MockTransport,
// DTO-derived fixtures, runs in-browser). When NEXT_PUBLIC_DOCSURI_REAL_API is
// set, client calls route through the same-origin BFF (RouteHandlerTransport ->
// /bff/* -> server HttpTransport -> U6 gateway); the httpOnly session cookie and
// gateway URL stay server-side (SEC-3/12). Components/ApiClient are untouched —
// only the transport behind this factory changes.
import { ApiClient } from './apiClient';
import { MockTransport } from './mockTransport';
import { RouteHandlerTransport } from './routeHandlerTransport';
import type { Transport } from './transport';

export { ApiClient } from './apiClient';
export { UserFacingError } from './errors';
export type { SearchOutcome } from './classify';
export type {
  SummarizeOutcome,
  DocModelOutcome,
  AssetsOutcome,
} from './classifySummarize';
export type { Transport } from './transport';

// Public flag (inlined at build per Next): present => real BFF path, absent => mock.
// Kept distinct from the server-only DOCSURI_GATEWAY_URL so the client never reads it.
const REAL_API = Boolean(process.env.NEXT_PUBLIC_DOCSURI_REAL_API);

let mockSingleton: ApiClient | null = null;
let realSingleton: ApiClient | null = null;

/** Mock-first client (in-browser fixtures). Retained for tests and mock-only mode. */
export function getMockApiClient(): ApiClient {
  if (!mockSingleton) mockSingleton = new ApiClient(new MockTransport());
  return mockSingleton;
}

// Server-side (DOCSURI_GATEWAY_URL -> real gateway) lives ONLY in the BFF route
// handler (app/bff/[...path]/route.ts), which imports HttpTransport directly. We
// must NOT reference httpTransport from here: this module is in the client graph
// (getApiClient is imported by client components), and a `server-only` import —
// even a dynamic one — pulls it into the client bundle and fails the build.

/**
 * Resolve the active ApiClient. Pass an explicit transport in tests. Otherwise
 * the build-time flag selects the same-origin BFF (real) or in-browser mock.
 */
export function getApiClient(transport?: Transport): ApiClient {
  if (transport) return new ApiClient(transport);
  if (!REAL_API) return getMockApiClient();
  if (!realSingleton) realSingleton = new ApiClient(new RouteHandlerTransport());
  return realSingleton;
}
