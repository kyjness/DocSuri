import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LibraryScreen } from '@/components/library/LibraryScreen';
import { SavedSearchScreen } from '@/components/library/SavedSearchScreen';
import { HistoryScreen } from '@/components/library/HistoryScreen';

// These drive the real MockTransport + library fixtures (mock-first), so they
// exercise the list/pagination/remove/rerun/clear paths end-to-end without a
// backend. Each screen mutates an independent fixture array.

vi.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  // usePaginatedList/SavedSearchScreen/HistoryScreen route to `/login?redirect=<pathname>` on a
  // mid-session 401 (E1/E2) — any fixed string is fine here since no test in this file exercises
  // that path.
  usePathname: () => '/library/mock',
}));

describe('LibraryScreen (US-L2)', () => {
  it('lists a cursor page and loads more', async () => {
    render(<LibraryScreen />);
    // 22 seeded items, default limit 20 → first page is 20 with a "더 보기".
    await waitFor(() => expect(screen.getAllByTestId('library-item').length).toBe(20));
    await userEvent.click(screen.getByTestId('library-more'));
    await waitFor(() => expect(screen.getAllByTestId('library-item').length).toBe(22));
  });

  it('removes an item optimistically after a 2xx', async () => {
    render(<LibraryScreen />);
    await waitFor(() => expect(screen.getAllByTestId('library-item').length).toBeGreaterThan(0));
    const before = screen.getAllByTestId('library-item').length;
    await userEvent.click(screen.getAllByTestId('library-remove')[0]);
    await waitFor(() => expect(screen.getAllByTestId('library-item').length).toBe(before - 1));
  });
});

describe('SavedSearchScreen (US-L1)', () => {
  it('lists saved searches and reruns one inline', async () => {
    render(<SavedSearchScreen />);
    expect(screen.queryByRole('link', { name: '라이브러리' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '저장한 검색' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '검색 이력' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByTestId('saved-item').length).toBeGreaterThan(0));
    await userEvent.click(screen.getAllByTestId('saved-rerun')[0]);
    expect(await screen.findByTestId('saved-rerun-result')).toBeInTheDocument();
    expect(screen.getByTestId('result-list')).toBeInTheDocument();
  });
});

describe('HistoryScreen (US-L3)', () => {
  it('lists history and clears it', async () => {
    render(<HistoryScreen />);
    expect(screen.queryByRole('link', { name: '라이브러리' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '저장한 검색' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '검색 이력' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByTestId('history-item').length).toBeGreaterThan(0));
    await userEvent.click(screen.getByTestId('history-clear'));
    expect(await screen.findByTestId('state-view-empty')).toBeInTheDocument();
  });
});
