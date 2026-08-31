import styles from '../../page.module.css';
import header from './paper.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { BottomNav } from '@/components/BottomNav';
import { PaperDetailIsland } from '@/components/PaperDetailIsland';
import { arxivVersion } from '@/lib/arxivVersion';

// Detail route /paper/[id] (Q1=A) — SSR shell (AppHeader) + client island. The header shows
// a back arrow (← to the previous screen, e.g. search) instead of the brand logo. The island
// owns the 요약/초록번역/각주트리 actions, metadata, and 본문/본문번역 access. protected (RouteGuard).
//
// paperId = arxivId; version = the arXiv revision parsed from the id (e.g. "…v6" → 6), so the
// detail page requests the doc-model / assets / translation artifact for the paper's ACTUAL
// revision rather than a hardcoded v1. NOTE: title/authors/abstract come from a PROVISIONAL
// paper-metadata endpoint (mock in dev) — see usePaperMeta.
export default async function PaperPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const version = arxivVersion(id);
  const arxivUrl = `https://arxiv.org/abs/${encodeURIComponent(id)}`;

  return (
    <RouteGuard redirectTo={`/paper/${id}`}>
      <div className={styles.screen}>
        {/* 검색 화면은 결과와 스크롤 위치를 스스로 되돌린다(searchCache) — 라우터가 맨 위로
            스크롤하면 그 복원을 덮으므로 여기서만 비켜 준다. */}
        <AppHeader backHref="/search" backRestoresScroll />
        <main className={header.main}>
          <PaperDetailIsland paperId={id} version={version} arxivUrl={arxivUrl} />
        </main>
      </div>
      <BottomNav />
    </RouteGuard>
  );
}
