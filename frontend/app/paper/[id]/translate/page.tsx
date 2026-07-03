import screen from '../../../page.module.css';
import page from '../reading.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { FullTranslationIsland } from '@/components/FullTranslationIsland';
import { arxivVersion } from '@/lib/arxivVersion';

// Full-text translation route /paper/[id]/translate (FR-13, scope=full) — a full-screen in-app
// route reached from the detail page's 본문 번역 action. The header's ← goes to a FIXED
// destination (the detail page), not history back, mirroring the 본문 route. protected
// (RouteGuard). version comes from the ?version link, falling back to the id's arXiv revision.
export default async function TranslatePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  // Explicit ?version from the detail-page link wins; a deep link with no query falls back to
  // the revision parsed from the id rather than a hardcoded v1.
  const version =
    Number(Array.isArray(sp.version) ? sp.version[0] : sp.version) || arxivVersion(id);

  // Preserve ?version (and any other query) across a login round-trip (E6, BR-U5-15) — a
  // query-less redirectTo used to drop it, landing the user back on the wrong revision.
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(sp)) {
    if (Array.isArray(value)) value.forEach((v) => query.append(key, v));
    else if (value !== undefined) query.append(key, value);
  }
  const redirectTo = query.toString()
    ? `/paper/${id}/translate?${query.toString()}`
    : `/paper/${id}/translate`;

  return (
    <RouteGuard redirectTo={redirectTo}>
      <div className={screen.screen}>
        <AppHeader title="전문 번역" backHref={`/paper/${id}`} />
        <main className={page.page}>
          <FullTranslationIsland paperId={id} version={version} />
        </main>
      </div>
    </RouteGuard>
  );
}
