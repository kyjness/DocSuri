import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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

beforeEach(() => {
  mockLogin('mypage-library-test@example.com');
  resetMypageFixtures();
});

describe('MyPageLibraryScreen (U10)', () => {
  it('renders the 관심 논문/최근 tabs with the interest tab active by default, plus a link out to saved searches', async () => {
    render(<MyPageLibraryScreen active="interest" />);
    expect(await screen.findByTestId('mypage-library-tab-interest')).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByTestId('mypage-library-tab-interest')).toHaveTextContent('관심 논문');
    expect(screen.getByTestId('mypage-library-tab-recent')).not.toHaveAttribute('aria-current');
    expect(screen.getByTestId('mypage-library-saved-history')).toHaveAttribute(
      'href',
      '/library/saved',
    );
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
