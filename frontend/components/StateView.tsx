import styles from './StateView.module.css';

// StateView (LC-6, FR-11, US-D7) — non-technical empty/abstain/degraded/loading/
// error/invalid surface. Abstain and empty are DISTINCT messages (BR-U5-9). No
// stack traces or internal identifiers (SEC-15, BR-U5-11).

export type StateViewKind =
  | 'loading'
  | 'empty'
  | 'abstain'
  | 'invalid'
  | 'error'
  // U7 summarization additions (BR-SF-7/11):
  | 'degraded'
  | 'sourceUnavailable'
  | 'licenseUnavailable';

interface StateViewProps {
  kind: StateViewKind;
  /** Optional title override (e.g. U7 reuses `loading` with a summarize-specific title). */
  title?: string;
  message?: string;
  onRetry?: () => void;
  field?: string;
}

const COPY: Record<StateViewKind, { title: string; body: string }> = {
  loading: { title: '검색 중…', body: '결과를 불러오고 있어요.' },
  empty: { title: '검색 결과가 없습니다', body: '다른 검색어로 다시 시도해 보세요.' },
  abstain: {
    title: '확실한 근거를 찾지 못했습니다',
    body: '신뢰할 만한 결과가 없어 표시하지 않았어요. 검색어를 바꿔 다시 시도해 보세요.',
  },
  invalid: { title: '입력을 확인해 주세요', body: '검색어를 다시 확인해 주세요.' },
  error: { title: '문제가 발생했습니다', body: '잠시 후 다시 시도해 주세요.' },
  // 비용 게이트(일시 중단) — 재시도 가능.
  degraded: { title: 'AI 요약이 일시 중단됐어요', body: '잠시 후 다시 시도해 주세요.' },
  // 원문 부재 — 처리 불가(정상 동작, 자동 재시도 없음).
  sourceUnavailable: {
    title: '원문을 가져올 수 없어요',
    body: '이 논문은 원문을 불러올 수 없어 요약/번역을 만들지 못했어요.',
  },
  // OA 라이선스 미허용 — 앱 내 전문 보기 불가, arXiv 안내.
  licenseUnavailable: {
    title: '원문은 arXiv에서 볼 수 있어요',
    body: '이 논문은 앱에서 전문 보기를 제공하지 않아요. arXiv 원문을 확인해 주세요.',
  },
};

const RETRYABLE: ReadonlySet<StateViewKind> = new Set(['error', 'degraded']);

export function StateView({ kind, title, message, onRetry, field }: StateViewProps) {
  const copy = COPY[kind];
  return (
    <div
      className={styles.root}
      role="status"
      aria-live="polite"
      aria-busy={kind === 'loading'}
      data-testid={`state-view-${kind}`}
      data-field={field}
    >
      {kind === 'loading' ? (
        <div className={styles.spinner} aria-hidden="true" />
      ) : null}
      <p className={styles.title}>{title ?? copy.title}</p>
      <p className={styles.body}>{message ?? copy.body}</p>
      {onRetry && RETRYABLE.has(kind) ? (
        <button type="button" className={styles.retry} onClick={onRetry} data-testid="state-view-retry">
          다시 시도
        </button>
      ) : null}
    </div>
  );
}
