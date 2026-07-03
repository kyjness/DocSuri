import screen from '../../../page.module.css';
import page from '../reading.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { DocModelViewer } from '@/components/DocModelViewer';
import { arxivVersion } from '@/lib/arxivVersion';
import type { AnchorVM } from '@/types/generated';

// Doc-model rich-view route /paper/[id]/doc-model (D4, FD §2.10) — a full-screen in-app route
// reached from the detail page's 본문 action. The header's ← goes to a FIXED destination (the
// detail page), not history back, so it is robust against an interleaved login redirect or a
// deep link. protected (RouteGuard). A summary source anchor is carried via ?anchorLabel (and
// optional ?anchorSpan) so the page scrolls to the matching block. version comes from the
// ?version link, falling back to the id's arXiv revision.
export default async function DocModelPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  // Prefer the explicit ?version from the detail-page link; on a deep link with no query, fall
  // back to the revision in the id itself rather than a hardcoded v1 (which would show a stale
  // or perpetually-"building" body for any later-revision paper).
  const version =
    Number(Array.isArray(sp.version) ? sp.version[0] : sp.version) || arxivVersion(id);
  const arxivUrl = `https://arxiv.org/abs/${encodeURIComponent(id)}`;

  const label = typeof sp.anchorLabel === 'string' ? sp.anchorLabel : undefined;
  const span = typeof sp.anchorSpan === 'string' ? sp.anchorSpan : '';
  const anchor: AnchorVM | null = label ? { field: '', target: 'section', span, label } : null;

  // Preserve ?version/?anchorLabel/?anchorSpan across a login round-trip (E6, BR-U5-15) — a
  // query-less redirectTo used to drop them, landing the user back on the doc-model page but
  // no longer scrolled to the summary anchor they came from.
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(sp)) {
    if (Array.isArray(value)) value.forEach((v) => query.append(key, v));
    else if (value !== undefined) query.append(key, value);
  }
  const redirectTo = query.toString()
    ? `/paper/${id}/doc-model?${query.toString()}`
    : `/paper/${id}/doc-model`;

  return (
    <RouteGuard redirectTo={redirectTo}>
      <div className={screen.screen}>
        <AppHeader title="전문" backHref={`/paper/${id}`} />
        <main className={page.page}>
          <DocModelViewer paperId={id} version={version} anchor={anchor} arxivUrl={arxivUrl} />
        </main>
      </div>
    </RouteGuard>
  );
}
