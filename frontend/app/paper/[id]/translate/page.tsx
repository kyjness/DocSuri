import screen from '../../../page.module.css';
import page from '../reading.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { FullTranslationIsland } from '@/components/FullTranslationIsland';

// Full-text translation route /paper/[id]/translate (FR-13, scope=full) — a full-screen in-app
// route reached from the detail page's 본문 번역 action. The header's ← goes to a FIXED
// destination (the detail page), not history back, mirroring the 본문 route. protected
// (RouteGuard). version defaults to 1 (Q8=A).
export default async function TranslatePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const version = Number(Array.isArray(sp.version) ? sp.version[0] : sp.version) || 1;

  return (
    <RouteGuard redirectTo={`/paper/${id}/translate`}>
      <div className={screen.screen}>
        <AppHeader title="본문 번역" backHref={`/paper/${id}`} />
        <main className={page.page}>
          <FullTranslationIsland paperId={id} version={version} />
        </main>
      </div>
    </RouteGuard>
  );
}
