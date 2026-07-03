'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { AssetRef, TranslationVM } from '@/types/generated';
import { getApiClient } from '@/lib/api';
import { UserFacingError } from '@/lib/api/errors';
import { recordGlossaryUpdated } from '@/lib/personalization';
import { useGlossaryTerms } from '@/lib/useGlossaryTerms';
import { useGlossaryDraft } from '@/lib/useGlossaryDraft';
import { GlossaryTermBadge } from './GlossaryTermBadge';
import { DocModelBody } from './DocModelViewer';
import styles from './TranslationView.module.css';

// TranslationView (US-S2, BR-SF-9 / BR-S18) — Korean translation rendered as a "translated
// doc-model": the SAME structured rich view as the original body (sections·수식·표·그림), only the
// text is Korean. Below it, the glossary is split into two INDEPENDENT groups (BR-S4):
//   · 원어 유지 용어 — the other terms the model kept in English → weak (read-time overlay).
//   · 표준 용어 — DocSuri standard seed terms present in this paper (keep-as-is + mapping chips, the
//     latter pre-filled) → strong (prompt-enforced, needs a re-generate).
// Editing a chip does NOT hit the server; it stages the rendering into a per-paper draft
// (`useGlossaryDraft`, sessionStorage) so a pending edit — and its group's "반영" button — survive
// leaving and re-entering this page, and nothing reflects until applied. Each group has its OWN apply
// button that persists (POST) + re-generates ONLY its own pending edits (`onRegenerate`), so applying
// weak terms never triggers the expensive strong re-translation and vice-versa. External text is
// escaped by React; no anchors (translation is grounding-free). Only one editor is open at a time; a
// click outside closes it.

// Stable empty map so an abstract translation (no figures) doesn't re-create one each render.
const NO_ASSETS: Map<string, AssetRef> = new Map();

interface TranslationViewProps {
  translation: TranslationVM;
  cached?: boolean;
  /** Show the personal-glossary editor. Only the full-text translation (본문 번역) exposes it. */
  showGlossary?: boolean;
  /** Signed figure/table asset urls (by assetId) for figures inside the translated doc-model.
   * Omitted for abstract translation (no figures). */
  assetsById?: Map<string, AssetRef>;
  /** Re-run the full translation so applied overrides take effect. When provided, each group shows a
   * "반영" button that persists + re-runs its own pending edits. */
  onRegenerate?: () => void;
}

type ApplyGroup = 'weak' | 'strong';

export function TranslationView({
  translation,
  showGlossary = false,
  assetsById,
  onRegenerate,
}: TranslationViewProps) {
  const [openTerm, setOpenTerm] = useState<string | null>(null);
  const [applying, setApplying] = useState<ApplyGroup | null>(null);
  const [applyError, setApplyError] = useState<{ group: ApplyGroup; message: string } | null>(null);
  const termsRef = useRef<HTMLDivElement | null>(null);

  const { paperId, version } = translation.docModel.meta;
  const { terms: savedTerms } = useGlossaryTerms(); // previously applied (server) renderings
  const { draft, stage, remove } = useGlossaryDraft(paperId, version); // pending edits (this paper)

  // Close the open editor on any pointer-down outside the glossary section. `pointerdown` covers
  // both mouse and touch (a plain `mousedown` may not fire on a real phone), and fires before click
  // so a tap elsewhere dismisses before it activates anything.
  useEffect(() => {
    if (openTerm === null) return;
    const onPointerDown = (e: PointerEvent) => {
      if (termsRef.current && !termsRef.current.contains(e.target as Node)) {
        setOpenTerm(null);
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [openTerm]);

  // Split the glossary: standard keep-as-is (→ strong) and standard mappings (→ strong, pre-filled)
  // both go under 표준 용어; the remaining kept terms (→ weak) go under 원어 유지 용어. `nonStandardKept`
  // excludes EVERY standard term — keep-as-is AND mapping — so a kept term the model also mapped can't
  // render twice (two editors for one term). Terms are compared case-insensitively.
  const standardGlossary = translation.standardGlossary ?? [];
  const standardKeepAsIs = standardGlossary.filter((g) => !g.translated);
  const standardMappings = standardGlossary.filter((g) => g.translated);
  const standardTerms = new Set(standardGlossary.map((g) => g.term.toLowerCase()));
  const nonStandardKept = translation.keptTerms.filter((t) => !standardTerms.has(t.toLowerCase()));
  const hasStandard = standardKeepAsIs.length > 0 || standardMappings.length > 0;
  const hasGlossary = showGlossary && (hasStandard || nonStandardKept.length > 0);

  // The rendering to show/pre-fill for a term: a pending draft edit wins over a previously applied one.
  const effective = (term: string) => draft[term]?.termTo ?? savedTerms[term];
  const pendingKeys = (strong: boolean) =>
    Object.keys(draft).filter((k) => draft[k].strong === strong);

  // Stable so the badge's auto-dismiss timer isn't reset by unrelated parent re-renders.
  const closeEditor = useCallback(() => setOpenTerm(null), []);

  // Stage an edit and clear any stale apply error for that group (a new edit supersedes it).
  const stageTerm = (term: string, termTo: string, strong: boolean) => {
    stage(term, termTo, strong);
    const group: ApplyGroup = strong ? 'strong' : 'weak';
    setApplyError((prev) => (prev?.group === group ? null : prev));
  };
  // Un-stage a pending edit (지우기) and close its editor.
  const clearTerm = (term: string) => {
    remove([term]);
    setOpenTerm(null);
  };

  // Apply ONE group: persist its staged edits (POST), drop them from the draft, then re-run so they
  // reflect. Errors surface inline (with retry) and keep the draft intact — no silent loss.
  const applyGroup = async (isStrong: boolean) => {
    const group: ApplyGroup = isStrong ? 'strong' : 'weak';
    const keys = pendingKeys(isStrong);
    if (keys.length === 0 || applying) return;
    setApplying(group);
    setApplyError(null);
    try {
      const client = getApiClient();
      let lastVer: number | undefined;
      for (const termFrom of keys) {
        const res = await client.upsertGlossaryTerm({
          termFrom,
          termTo: draft[termFrom].termTo,
          promptEnforced: isStrong,
        });
        lastVer = res.glossaryVer;
      }
      if (lastVer !== undefined) recordGlossaryUpdated(lastVer);
      remove(keys);
      onRegenerate?.(); // re-run reflects it (weak: cached base + overlay · strong: regenerate)
      setApplying(null);
    } catch (e) {
      const message =
        e instanceof UserFacingError ? e.message : '반영에 실패했어요. 다시 시도해 주세요.';
      setApplyError({ group, message });
      setApplying(null);
    }
  };

  const renderApplyBar = (isStrong: boolean) => {
    if (!onRegenerate) return null;
    const keys = pendingKeys(isStrong);
    if (keys.length === 0) return null;
    const group: ApplyGroup = isStrong ? 'strong' : 'weak';
    const busy = applying === group;
    const err = applyError?.group === group ? applyError.message : null;
    return (
      <div className={styles.apply}>
        <span className={styles.applyNote}>
          {isStrong
            ? `바꾼 표준 용어 ${keys.length}개 · 누르면 번역을 다시 만들어 반영해요`
            : `바꾼 용어 ${keys.length}개 · 누르면 번역에 반영해요`}
        </span>
        <button
          type="button"
          className={styles.applyButton}
          onClick={() => void applyGroup(isStrong)}
          disabled={busy}
          data-testid={isStrong ? 'glossary-apply-strong' : 'glossary-apply-weak'}
        >
          {busy ? '반영 중…' : isStrong ? '번역 다시 만들기' : '번역에 반영하기'}
        </button>
        {err ? (
          <span className={styles.applyError} role="alert">
            {err}
          </span>
        ) : null}
      </div>
    );
  };

  return (
    <div className={styles.root} data-testid="translation-view">
      {translation.docModel.meta.title ? (
        <h1 className={styles.paperTitle} data-testid="translation-title">
          {translation.docModel.meta.title}
        </h1>
      ) : null}

      {hasGlossary ? (
        <section className={styles.glossary} ref={termsRef} aria-label="용어집">
          {nonStandardKept.length > 0 ? (
            <div className={styles.group}>
              <h3 className={styles.glossaryTitle}>원어 유지 용어</h3>
              <p className={styles.glossaryHint}>
                번역에서 원어로 남은 용어예요. 내 번역어를 지정하고 아래 버튼으로 반영해요.
              </p>
              <div className={styles.terms}>
                {nonStandardKept.map((t) => (
                  <GlossaryTermBadge
                    key={`kept-${t}`}
                    term={t}
                    open={openTerm === t}
                    onOpen={() => setOpenTerm(t)}
                    onClose={closeEditor}
                    saved={effective(t)}
                    pending={Boolean(draft[t])}
                    onSave={(termTo) => stageTerm(t, termTo, false)}
                    onClear={() => clearTerm(t)}
                  />
                ))}
              </div>
              {renderApplyBar(false)}
            </div>
          ) : null}

          {hasStandard ? (
            <div className={styles.group}>
              <h3 className={styles.glossaryTitle}>표준 용어</h3>
              <p className={styles.glossaryHint}>
                DocSuri가 표준으로 정한 용어예요. 바꾼 뒤 아래 버튼을 누르면 번역을 다시 만들어
                반영해요.
              </p>
              <div className={styles.terms}>
                {standardKeepAsIs.map((g) => (
                  <GlossaryTermBadge
                    key={`std-${g.term}`}
                    term={g.term}
                    strong
                    open={openTerm === g.term}
                    onOpen={() => setOpenTerm(g.term)}
                    onClose={closeEditor}
                    saved={effective(g.term)}
                    pending={Boolean(draft[g.term])}
                    onSave={(termTo) => stageTerm(g.term, termTo, true)}
                    onClear={() => clearTerm(g.term)}
                  />
                ))}
                {standardMappings.map((g) => (
                  <GlossaryTermBadge
                    key={`map-${g.term}`}
                    term={g.term}
                    strong
                    defaultValue={g.translated}
                    open={openTerm === g.term}
                    onOpen={() => setOpenTerm(g.term)}
                    onClose={closeEditor}
                    saved={effective(g.term)}
                    pending={Boolean(draft[g.term])}
                    onSave={(termTo) => stageTerm(g.term, termTo, true)}
                    onClear={() => clearTerm(g.term)}
                  />
                ))}
              </div>
              {renderApplyBar(true)}
            </div>
          ) : null}
        </section>
      ) : null}

      <div className={styles.text}>
        <DocModelBody docModel={translation.docModel} assetsById={assetsById ?? NO_ASSETS} />
      </div>
    </div>
  );
}
