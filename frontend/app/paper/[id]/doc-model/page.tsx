import screen from '../../../page.module.css';
import page from '../reading.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { DocModelViewer } from '@/components/DocModelViewer';
import type { AnchorVM } from '@/types/generated';

// Doc-model rich-view route /paper/[id]/doc-model (D4, FD §2.10) — a full-screen in-app route
// reached from the detail page's 본문 action. The header's ← goes to a FIXED destination (the
// detail page), not history back, so it is robust against an interleaved login redirect or a
// deep link. protected (RouteGuard). A summary source anchor is carried via ?anchorLabel (and
// optional ?anchorSpan) so the page scrolls to the matching block. version defaults to 1 (Q8=A).
export default async function DocModelPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const version = Number(Array.isArray(sp.version) ? sp.version[0] : sp.version) || 1;
  const arxivUrl = `https://arxiv.org/abs/${encodeURIComponent(id)}`;

  const label = typeof sp.anchorLabel === 'string' ? sp.anchorLabel : undefined;
  const span = typeof sp.anchorSpan === 'string' ? sp.anchorSpan : '';
  const anchor: AnchorVM | null = label ? { field: '', target: 'section', span, label } : null;

  return (
    <RouteGuard redirectTo={`/paper/${id}/doc-model`}>
      <div className={screen.screen}>
        <AppHeader title="전문" backHref={`/paper/${id}`} />
        <main className={page.page}>
          <DocModelViewer paperId={id} version={version} anchor={anchor} arxivUrl={arxivUrl} />
        </main>
      </div>
    </RouteGuard>
  );
}
