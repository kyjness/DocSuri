import type { SummaryVM, AnchorVM } from '@/types/generated';
import styles from './SummaryView.module.css';

// SummaryView (+AnchorChip) — renders the 6 structured §3 fields with per-claim
// "출처 보기" anchor chips. External text is escaped by React (BR-SF-9). Display is
// not post-processed — only grounded backend output is shown (BR-SF-10). Anchor
// click → full-text viewer highlight (Q5=C, BR-SF-8) via onAnchor.

interface SummaryViewProps {
  summary: SummaryVM;
  cached?: boolean;
  onAnchor?: (anchor: AnchorVM) => void;
}

function AnchorChips({
  field,
  anchors,
  onAnchor,
}: {
  field: string;
  anchors: AnchorVM[];
  onAnchor?: (a: AnchorVM) => void;
}) {
  const forField = anchors.filter((a) => a.field === field);
  if (forField.length === 0) return null;
  return (
    <div className={styles.anchors}>
      {forField.map((a, i) => (
        <button
          key={`${a.target}-${a.label}-${i}`}
          type="button"
          className={styles.anchor}
          title={a.span}
          onClick={onAnchor ? () => onAnchor(a) : undefined}
          disabled={!onAnchor}
          data-testid="summary-anchor"
        >
          출처: {a.label}
        </button>
      ))}
    </div>
  );
}

export function SummaryView({ summary, cached, onAnchor }: SummaryViewProps) {
  const { anchors } = summary;
  return (
    <div className={styles.root} data-testid="summary-view">
      {cached ? (
        <p className={styles.cached} data-testid="summary-cached">
          저장된 결과
        </p>
      ) : null}

      <section className={styles.field}>
        <h4 className={styles.label}>한 줄 요약</h4>
        <p className={styles.body}>{summary.tldr}</p>
        <AnchorChips field="tldr" anchors={anchors} onAnchor={onAnchor} />
      </section>

      <section className={styles.field}>
        <h4 className={styles.label}>핵심 기여</h4>
        <ul className={styles.list}>
          {summary.contributions.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
        <AnchorChips field="contributions" anchors={anchors} onAnchor={onAnchor} />
      </section>

      <section className={styles.field}>
        <h4 className={styles.label}>연구 방법</h4>
        <p className={styles.body}>{summary.method}</p>
        <AnchorChips field="method" anchors={anchors} onAnchor={onAnchor} />
      </section>

      <section className={styles.field}>
        <h4 className={styles.label}>주요 결과</h4>
        <p className={styles.body}>{summary.results}</p>
        <AnchorChips field="results" anchors={anchors} onAnchor={onAnchor} />
      </section>

      <section className={styles.field}>
        <h4 className={styles.label}>한계</h4>
        <p className={styles.body}>{summary.limitations}</p>
        <AnchorChips field="limitations" anchors={anchors} onAnchor={onAnchor} />
      </section>

      <section className={styles.field}>
        <h4 className={styles.label}>재현성</h4>
        <p className={styles.body}>
          <span className={styles.repLabel}>코드</span> {summary.reproducibility.code}
        </p>
        <p className={styles.body}>
          <span className={styles.repLabel}>데이터</span> {summary.reproducibility.data}
        </p>
        <AnchorChips field="reproducibility" anchors={anchors} onAnchor={onAnchor} />
      </section>
    </div>
  );
}
