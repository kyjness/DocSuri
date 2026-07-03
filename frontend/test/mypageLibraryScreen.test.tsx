import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MyPageLibraryScreen } from '@/components/mypage/MyPageLibraryScreen';
import { mockLogin } from '@/mocks/accountFixtures';
import { resetMypageFixtures } from '@/mocks/mypageFixtures';

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
// InterestTab/SavedSearchScreen/HistoryScreen all use usePaginatedList, which now reads
// useRouter/usePathname (E1/E2 mid-session-401 redirect) — neither exists in this jsdom render
// without a Next.js app-router context, so it needs mocking like the other screen tests do.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/mypage/library',
}));

beforeEach(() => {
  mockLogin('mypage-library-test@example.com');
  resetMypageFixtures();
});

describe('MyPageLibraryScreen (U10)', () => {
  it('renders all library tabs and switches saved searches/history in-page', async () => {
    const user = userEvent.setup();
    render(<MyPageLibraryScreen active="interest" />);
    expect(await screen.findByTestId('mypage-library-tab-interest')).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByTestId('mypage-library-tab-interest')).toHaveTextContent('관심 논문');
    expect(screen.getByTestId('mypage-library-tab-recent')).not.toHaveAttribute('aria-current');
    expect(screen.getByTestId('mypage-library-tab-saved')).toHaveTextContent('저장한 검색');
    expect(screen.getByTestId('mypage-library-tab-history')).toHaveTextContent('검색 이력');

    await user.click(screen.getByTestId('mypage-library-tab-saved'));
    expect(await screen.findByTestId('saved-screen')).toBeInTheDocument();
    expect(screen.queryByTestId('tab-saved')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('mypage-library-tab-history'));
    expect(await screen.findByTestId('history-screen')).toBeInTheDocument();
    expect(screen.queryByTestId('tab-history')).not.toBeInTheDocument();
  });

  it('renders the recently-viewed list on the recent tab', async () => {
    render(<MyPageLibraryScreen active="recent" />);
    expect(await screen.findByTestId('mypage-library-tab-recent')).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(await screen.findByTestId('mypage-recent-list')).toBeInTheDocument();
    expect(screen.getAllByTestId('mypage-recent-item').length).toBeGreaterThan(0);
  });
});
