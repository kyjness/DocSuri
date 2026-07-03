import type { SummaryVM, AnchorVM } from '@/types/generated';
import { renderInlineRich, renderRichText } from '@/lib/renderMath';
import styles from './SummaryView.module.css';

// SummaryView (+AnchorChip) — renders the 6 structured §3 fields with per-claim
// "출처 보기" anchor chips. External text is escaped by React (BR-SF-9). Display is
// not post-processed — only grounded backend output is shown (BR-SF-10). Anchor
// click → full-text viewer highlight (Q5=C, BR-SF-8) via onAnchor.
//
// Formatting: summary fields carry lightweight markdown (**bold**, `-` bullets, blank-line
// paragraphs) and LaTeX math ($…$ / \(…\)). The longer fields (method/results/limitations) render
// through renderRichText (block: paragraphs, bullet lists, bold, math) so a dense results section
// reads as a structured list; short fields (tldr, contributions items, reproducibility) use the
// inline variant. KaTeX escapes its own input; surrounding prose is React-escaped.

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

export function SummaryView({ summary, onAnchor }: SummaryViewProps) {
  const { anchors } = summary;
  return (
    <div className={styles.root} data-testid="summary-view">
      <section className={styles.field}>
        <h4 className={styles.label}>한 줄 요약</h4>
        <p className={styles.body}>{renderInlineRich(summary.tldr)}</p>
        <AnchorChips field="tldr" anchors={anchors} onAnchor={onAnchor} />
      </section>

      <section className={styles.field}>
        <h4 className={styles.label}>핵심 기여</h4>
        <ul className={styles.list}>
          {summary.contributions.map((c, i) => (
            <li key={i}>{renderInlineRich(c)}</li>
          ))}
        </ul>
        <AnchorChips field="contributions" anchors={anchors} onAnchor={onAnchor} />
      </section>

      <section className={styles.field}>
        <h4 className={styles.label}>연구 방법</h4>
        <div className={styles.body}>{renderRichText(summary.method)}</div>
        <AnchorChips field="method" anchors={anchors} onAnchor={onAnchor} />
      </section>

      <section className={styles.field}>
        <h4 className={styles.label}>주요 결과</h4>
        <div className={styles.body}>{renderRichText(summary.results)}</div>
        <AnchorChips field="results" anchors={anchors} onAnchor={onAnchor} />
      </section>

      <section className={styles.field}>
        <h4 className={styles.label}>한계</h4>
        <div className={styles.body}>{renderRichText(summary.limitations)}</div>
        <AnchorChips field="limitations" anchors={anchors} onAnchor={onAnchor} />
      </section>

      <section className={styles.field}>
        <h4 className={styles.label}>재현성</h4>
        <p className={styles.body}>
          <span className={styles.repLabel}>코드</span> {renderInlineRich(summary.reproducibility.code)}
        </p>
        <p className={styles.body}>
          <span className={styles.repLabel}>데이터</span> {renderInlineRich(summary.reproducibility.data)}
        </p>
        <AnchorChips field="reproducibility" anchors={anchors} onAnchor={onAnchor} />
      </section>
    </div>
  );
}
