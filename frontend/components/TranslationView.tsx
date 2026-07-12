'use client';

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { AssetRef, TranslationVM } from '@/types/generated';
import { getApiClient } from '@/lib/api';
import { UserFacingError } from '@/lib/api/errors';
import { recordGlossaryUpdated } from '@/lib/personalization';
import { useGlossaryTerms } from '@/lib/useGlossaryTerms';
import { useGlossaryDraft } from '@/lib/useGlossaryDraft';
import { GlossaryTermBadge } from './GlossaryTermBadge';
import { GlossaryTermEditor } from './GlossaryTermEditor';
import { CollapsibleTerms } from './CollapsibleTerms';
import { DocModelBody } from './DocModelViewer';
import styles from './TranslationView.module.css';

// TranslationView (US-S2, BR-SF-9 / BR-S18) — Korean translation rendered as a "translated
// doc-model": the SAME structured rich view as the original body (sections·수식·표·그림), only the
// text is Korean. Below it, the glossary is split into two INDEPENDENT groups (BR-S4):
//   · 원어 유지 용어 — the other terms the model kept in English → weak (read-time overlay).
//   · 표준 용어 — DocSuri standard seed terms present in this paper (keep-as-is + mapping chips, the
//     latter pre-filled) → strong. Standard terms are masked into ⟦N⟧ tokens at generation and
//     RENDERED on read, so editing one reflects in the TRANSLATION immediately by re-rendering the
//     shared base (no re-translation, no cache fork); it still rides into the SUMMARY prompt (no
//     masking there), so the summary cache invalidates and updates lazily on next open — the hint
//     tells the reader so the summary refreshing later isn't a surprise.
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
  // The open chip's term and its DOM node — the editor floats below that node (chips don't reflow).
  const [openTerm, setOpenTerm] = useState<string | null>(null);
  const [openAnchor, setOpenAnchor] = useState<HTMLButtonElement | null>(null);
  const [applying, setApplying] = useState<ApplyGroup | null>(null);
  const [applyError, setApplyError] = useState<{ group: ApplyGroup; message: string } | null>(null);
  const termsRef = useRef<HTMLDivElement | null>(null);
  const weakGroupRef = useRef<HTMLDivElement | null>(null);
  const strongGroupRef = useRef<HTMLDivElement | null>(null);
  const weakEditorId = useId();
  const strongEditorId = useId();

  const { paperId, version } = translation.docModel.meta;
  const { terms: savedTerms } = useGlossaryTerms(); // previously applied (server) renderings
  const { draft, stage, remove } = useGlossaryDraft(paperId, version); // pending edits (this paper)

  // Stable so the editor's auto-dismiss timer isn't reset by unrelated parent re-renders.
  const closeEditor = useCallback(() => {
    setOpenTerm(null);
    setOpenAnchor(null);
  }, []);
  const openEditor = useCallback((term: string, anchor: HTMLButtonElement) => {
    setOpenTerm(term);
    setOpenAnchor(anchor);
  }, []);

  // Close the open editor on any pointer-down outside the glossary section (the editor lives inside
  // it, so taps on the editor don't dismiss it). `pointerdown` covers both mouse and touch (a plain
  // `mousedown` may not fire on a real phone), and fires before click so a tap elsewhere dismisses
  // before it activates anything.
  useEffect(() => {
    if (openTerm === null) return;
    const onPointerDown = (e: PointerEvent) => {
      if (termsRef.current && !termsRef.current.contains(e.target as Node)) {
        closeEditor();
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [openTerm, closeEditor]);

  // Split the glossary: standard keep-as-is (→ strong) and standard mappings (→ strong, pre-filled)
  // both go under 표준 용어; the remaining kept terms (→ weak) go under 원어 유지 용어. `nonStandardKept`
  // excludes EVERY standard term — keep-as-is AND mapping — so a kept term the model also mapped can't
  // render twice (two editors for one term). Terms are compared case-insensitively.
  const standardGlossary = translation.standardGlossary ?? [];
  const standardKeepAsIs = standardGlossary.filter((g) => !g.translated);
  const standardMappings = standardGlossary.filter((g) => g.translated);
  // Key on BOTH the English term_from and its Korean rendering: the model can echo a mapping's
  // Korean (어텐션) into keptTerms, which must be absorbed by 표준 (backend already strips these;
  // this is defense-in-depth so no standard rendering ever renders as a 원어 유지 chip). NFC-
  // normalize both sides so composed/decomposed Hangul compare equal.
  const norm = (s: string) => s.normalize('NFC').toLowerCase();
  const standardTerms = new Set(
    standardGlossary.flatMap((g) =>
      [g.term, g.translated].filter(Boolean).map((s) => norm(s as string)),
    ),
  );
  const nonStandardKept = translation.keptTerms.filter((t) => !standardTerms.has(norm(t)));
  const hasStandard = standardKeepAsIs.length > 0 || standardMappings.length > 0;
  const hasGlossary = showGlossary && (hasStandard || nonStandardKept.length > 0);

  // Which group the open chip belongs to → which group floats the editor. The open term's standard
  // entry (if any) carries the mapping's pre-fill value (e.g. attention → 어텐션).
  const weakOpen = openTerm !== null && nonStandardKept.includes(openTerm);
  const openStandard = openTerm === null ? undefined : standardGlossary.find((g) => g.term === openTerm);
  const strongOpen = openStandard !== undefined;

  // The rendering to show/pre-fill for a term: a pending draft edit wins over a previously applied one.
  const effective = (term: string) => draft[term]?.termTo ?? savedTerms[term];
  const pendingKeys = (strong: boolean) =>
    Object.keys(draft).filter((k) => draft[k].strong === strong);

  // Stage an edit and clear any stale apply error for that group (a new edit supersedes it).
  const stageTerm = (term: string, termTo: string, strong: boolean) => {
    stage(term, termTo, strong);
    const group: ApplyGroup = strong ? 'strong' : 'weak';
    setApplyError((prev) => (prev?.group === group ? null : prev));
  };
  // Un-stage a pending edit (지우기) and close its editor.
  const clearTerm = (term: string) => {
    remove([term]);
    closeEditor();
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
            ? `바꾼 표준 용어 ${keys.length}개 · 누르면 번역에 바로 반영되고 요약에도 적용돼요(요약은 다음에 열 때 갱신)`
            : `바꾼 용어 ${keys.length}개 · 누르면 번역에 반영해요`}
        </span>
        <button
          type="button"
          className={styles.applyButton}
          onClick={() => void applyGroup(isStrong)}
          disabled={busy}
          data-testid={isStrong ? 'glossary-apply-strong' : 'glossary-apply-weak'}
        >
          {busy ? '반영 중…' : '번역에 반영하기'}
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
            <div className={styles.group} ref={weakGroupRef}>
              <h3 className={styles.glossaryTitle}>원어 유지 용어</h3>
              <p className={styles.glossaryHint}>
                번역에서 원어로 남은 용어예요. 내 번역어를 지정하고 아래 버튼으로 반영해요.
              </p>
              <CollapsibleTerms label="원어 유지 용어">
                {nonStandardKept.map((t) => (
                  <GlossaryTermBadge
                    key={`kept-${t}`}
                    term={t}
                    open={openTerm === t}
                    controlsId={weakEditorId}
                    onOpen={(el) => openEditor(t, el)}
                    onClose={closeEditor}
                    saved={effective(t)}
                  />
                ))}
              </CollapsibleTerms>
              {weakOpen ? (
                <GlossaryTermEditor
                  id={weakEditorId}
                  term={openTerm!}
                  saved={effective(openTerm!)}
                  pending={Boolean(draft[openTerm!])}
                  anchor={openAnchor}
                  container={weakGroupRef.current}
                  onSave={(termTo) => stageTerm(openTerm!, termTo, false)}
                  onClear={() => clearTerm(openTerm!)}
                  onClose={closeEditor}
                />
              ) : null}
              {renderApplyBar(false)}
            </div>
          ) : null}

          {hasStandard ? (
            <div className={styles.group} ref={strongGroupRef}>
              <h3 className={styles.glossaryTitle}>표준 용어</h3>
              <p className={styles.glossaryHint}>
                DocSuri가 표준으로 정한 용어예요. 바꾼 뒤 아래 버튼을 누르면 번역에 바로 반영되고,
                이 용어는 요약에도 함께 적용돼요(다음에 요약을 열 때 갱신).
              </p>
              <CollapsibleTerms label="표준 용어">
                {standardKeepAsIs.map((g) => (
                  <GlossaryTermBadge
                    key={`std-${g.term}`}
                    term={g.term}
                    open={openTerm === g.term}
                    controlsId={strongEditorId}
                    onOpen={(el) => openEditor(g.term, el)}
                    onClose={closeEditor}
                    saved={effective(g.term)}
                  />
                ))}
                {standardMappings.map((g) => (
                  <GlossaryTermBadge
                    key={`map-${g.term}`}
                    term={g.term}
                    open={openTerm === g.term}
                    controlsId={strongEditorId}
                    onOpen={(el) => openEditor(g.term, el)}
                    onClose={closeEditor}
                    saved={effective(g.term)}
                  />
                ))}
              </CollapsibleTerms>
              {strongOpen ? (
                <GlossaryTermEditor
                  id={strongEditorId}
                  term={openTerm!}
                  defaultValue={openStandard?.translated}
                  saved={effective(openTerm!)}
                  pending={Boolean(draft[openTerm!])}
                  anchor={openAnchor}
                  container={strongGroupRef.current}
                  onSave={(termTo) => stageTerm(openTerm!, termTo, true)}
                  onClear={() => clearTerm(openTerm!)}
                  onClose={closeEditor}
                />
              ) : null}
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
