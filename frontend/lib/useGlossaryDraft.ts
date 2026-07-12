'use client';

// useGlossaryDraft (개인 용어집 — 반영 대기, BR-S4) — holds the user's PENDING glossary edits for one
// paper until they press "번역에 반영하기". Nothing is sent to the server on a per-badge save; edits
// are staged here and only persisted (POST /api/glossary) + reflected (re-translate) as one batch on
// apply. Kept in `sessionStorage` (per paperId·version) so the pending edits — and the apply button —
// survive leaving and re-entering the 전문 번역 page (or an in-tab refresh); a term therefore never
// reflects just because the user navigated, only when they apply. Cleared on apply.
import { useCallback, useEffect, useRef, useState } from 'react';

export interface GlossaryDraftEntry {
  termTo: string;
  /** true = 표준 용어(마스킹 토큰 재렌더로 번역 즉시 반영 + 요약 재생성) · false = 원어 유지(후치환 오버레이). */
  strong: boolean;
}
export type GlossaryDraft = Record<string, GlossaryDraftEntry>;

const KEY_NS = 'docsuri:glossary-draft:';
const storageKey = (paperId: string, version: number) => `${KEY_NS}${paperId}:${version}`;

// Drop drafts left for OTHER versions of the same paper — a new version supersedes them, so they'd
// otherwise linger in sessionStorage until the tab closes.
function pruneStaleVersions(paperId: string, keepKey: string): void {
  try {
    const prefix = `${KEY_NS}${paperId}:`;
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const k = sessionStorage.key(i);
      if (k && k.startsWith(prefix) && k !== keepKey) sessionStorage.removeItem(k);
    }
  } catch {
    /* ignore unavailable storage */
  }
}

function readDraft(key: string): GlossaryDraft {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? (parsed as GlossaryDraft) : {};
  } catch {
    return {}; // unavailable/corrupt storage degrades to "no pending edits" (no crash)
  }
}

function writeDraft(key: string, draft: GlossaryDraft): void {
  try {
    if (Object.keys(draft).length === 0) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(draft));
  } catch {
    /* ignore quota/availability — the in-memory draft still drives this session */
  }
}

export function useGlossaryDraft(paperId: string, version: number) {
  const key = storageKey(paperId, version);
  // Empty on the server / first render; the effect hydrates from sessionStorage on the client so a
  // pending edit made before navigating away comes back with its apply button.
  const [draft, setDraft] = useState<GlossaryDraft>({});
  // Mirrors the latest draft so stage/remove can compute the next value synchronously without a stale
  // closure — and so the sessionStorage write happens OUTSIDE the setState updater. Applying an edit
  // re-runs the translation, which unmounts this view; React would drop an updater's side effect on
  // an unmounting component, so writing there could leave the draft un-cleared (button reappears).
  const draftRef = useRef<GlossaryDraft>({});

  useEffect(() => {
    pruneStaleVersions(paperId, key);
    const loaded = readDraft(key);
    draftRef.current = loaded;
    setDraft(loaded);
  }, [key, paperId]);

  // Persist synchronously, then queue the re-render — never inside the setState updater.
  const commit = useCallback(
    (next: GlossaryDraft) => {
      draftRef.current = next;
      writeDraft(key, next);
      setDraft(next);
    },
    [key],
  );

  const stage = useCallback(
    (termFrom: string, termTo: string, strong: boolean) => {
      commit({ ...draftRef.current, [termFrom]: { termTo, strong } });
    },
    [commit],
  );

  // Drop a subset once applied — the 원어 유지 / 표준 groups apply independently, so each clears only
  // its own terms and leaves the other group's pending edits (and button) untouched.
  const remove = useCallback(
    (termFroms: string[]) => {
      const next = { ...draftRef.current };
      for (const t of termFroms) delete next[t];
      commit(next);
    },
    [commit],
  );

  return { draft, stage, remove };
}
