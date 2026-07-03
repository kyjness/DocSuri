import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { push, client, MockUserFacingError } = vi.hoisted(() => {
  class MockUserFacingError extends Error {
    readonly kind = 'auth';
    get isAuth() {
      return true;
    }
  }

  return {
    push: vi.fn(),
    MockUserFacingError,
    client: {
      listLibrary: vi.fn(),
      removeFromLibrary: vi.fn(),
      listSavedSearches: vi.fn(),
      deleteSavedSearch: vi.fn(),
      listHistory: vi.fn(),
      clearHistory: vi.fn(),
    },
  };
});

vi.mock('next/link', () => ({
  __esModule: true,
  default: ({
    children,
    href,
    ...rest
  }: { children: React.ReactNode; href: string } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => '/library',
}));

vi.mock('@/lib/api', () => ({
  getApiClient: () => client,
  UserFacingError: MockUserFacingError,
}));

import { LibraryScreen } from '@/components/library/LibraryScreen';
import { SavedSearchScreen } from '@/components/library/SavedSearchScreen';
import { HistoryScreen } from '@/components/library/HistoryScreen';

beforeEach(() => {
  push.mockReset();
  client.listLibrary.mockResolvedValue({
    items: [
      {
        id: 'lib1',
        meta: { title: 'Paper', authors: [], arxivId: '2401.00001', arxivUrl: '' },
      },
    ],
  });
  client.removeFromLibrary.mockRejectedValue(new MockUserFacingError('auth'));
  client.listSavedSearches.mockResolvedValue({
    items: [{ id: 'saved1', query: 'attention', createdAt: '2026-07-02T00:00:00Z' }],
  });
  client.deleteSavedSearch.mockRejectedValue(new MockUserFacingError('auth'));
  client.listHistory.mockResolvedValue({
    items: [
      {
        id: 'hist1',
        query: 'attention',
        executedAt: '2026-07-02T00:00:00Z',
        resultCount: 1,
      },
    ],
  });
  client.clearHistory.mockRejectedValue(new MockUserFacingError('auth'));
});

describe('protected library mutations', () => {
  it('routes to login on auth expiry instead of showing dead-end mutation errors', async () => {
    const user = userEvent.setup();

    const { unmount } = render(<LibraryScreen />);
    await screen.findByTestId('library-remove');
    await user.click(screen.getByTestId('library-remove'));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/login?redirect=%2Flibrary'));
    expect(screen.queryByTestId('library-action-error')).not.toBeInTheDocument();
    unmount();

    const saved = render(<SavedSearchScreen />);
    await screen.findByTestId('saved-delete');
    await user.click(screen.getByTestId('saved-delete'));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId('saved-action-error')).not.toBeInTheDocument();
    saved.unmount();

    render(<HistoryScreen />);
    await screen.findByTestId('history-clear');
    await user.click(screen.getByTestId('history-clear'));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(3));
    expect(screen.queryByTestId('history-action-error')).not.toBeInTheDocument();
  });
});
