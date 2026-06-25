// UserFacingError — normalized, fail-closed error surface (P-R1, SEC-15).
//
// Transport/HTTP failures are normalized into a small set of user-facing kinds.
// Messages are non-technical and never include stack traces or internal
// identifiers (SEC-15). Credential existence is not disclosed (SEC-12).

export type UserFacingErrorKind =
  | 'auth' // 401 — session missing/expired
  | 'forbidden' // 403
  | 'rateLimited' // 429
  | 'server' // 5xx
  | 'network' // transport failure / timeout
  | 'unknown';

const DEFAULT_MESSAGES: Record<UserFacingErrorKind, string> = {
  auth: '로그인이 필요합니다. 다시 로그인해 주세요.',
  forbidden: '접근 권한이 없습니다.',
  rateLimited: '요청이 많아 잠시 후 다시 시도해 주세요.',
  server: '일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.',
  network: '네트워크 연결을 확인하고 다시 시도해 주세요.',
  unknown: '문제가 발생했습니다. 다시 시도해 주세요.',
};

export class UserFacingError extends Error {
  readonly kind: UserFacingErrorKind;

  constructor(kind: UserFacingErrorKind, message?: string) {
    super(message ?? DEFAULT_MESSAGES[kind]);
    this.name = 'UserFacingError';
    this.kind = kind;
  }

  /** Whether this error should route the user to re-authenticate. */
  get isAuth(): boolean {
    return this.kind === 'auth';
  }
}

/** Map an HTTP status to a fail-closed UserFacingError (no internals leak). */
export function normalizeHttpError(status: number, serverMessage?: unknown): UserFacingError {
  const safe =
    typeof serverMessage === 'string' && serverMessage.length <= 200 ? serverMessage : undefined;
  if (status === 401) return new UserFacingError('auth', safe);
  if (status === 403) return new UserFacingError('forbidden', safe);
  if (status === 429) return new UserFacingError('rateLimited', safe);
  if (status >= 500) return new UserFacingError('server');
  // FR-29/BR-A12: a 422 here means the request shape didn't match (often a stale
  // client bundle). Its body is FastAPI's {detail:[...]} array — not a string — so
  // `safe` is undefined and it would otherwise collapse into the opaque `unknown`
  // dead-end. Surface a clear, actionable message that nudges a refresh.
  if (status === 422)
    return new UserFacingError(
      'unknown',
      '입력 형식이 올바르지 않습니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.',
    );
  return new UserFacingError('unknown', safe);
}
