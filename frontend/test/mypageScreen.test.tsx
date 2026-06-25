import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MyPageScreen } from '@/components/mypage/MyPageScreen';
import { SessionProvider } from '@/components/session/SessionContext';
import { mockLogin } from '@/mocks/accountFixtures';
import { resetMypageFixtures } from '@/mocks/mypageFixtures';

// Drives the real MockTransport + mypage fixtures (mock-first), so it exercises the U10 menu
// screen end-to-end without a backend. Subscription/settings/library detail behavior is
// covered by mypageLibraryScreen/mypageSettingsScreen/mypageSubscriptionScreen tests — this
// screen only renders account info + the three menu entries (BR: 한 단계 더 들어가는 메뉴).

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

function renderScreen() {
  return render(
    <SessionProvider>
      <MyPageScreen />
    </SessionProvider>,
  );
}

beforeEach(() => {
  mockLogin('mypage-test@example.com');
  resetMypageFixtures();
});

describe('MyPageScreen (U10)', () => {
  it('renders account info and the three menu entries, with ORCID shown for the mock ORCID login provider', async () => {
    renderScreen();
    expect(await screen.findByTestId('mypage-profile')).toBeInTheDocument();
    expect(screen.getByTestId('mypage-orcid')).toBeInTheDocument();
    expect(screen.getByTestId('mypage-menu-library')).toHaveAttribute('href', '/mypage/library');
    expect(screen.getByTestId('mypage-menu-subscription')).toHaveAttribute(
      'href',
      '/mypage/subscription',
    );
    expect(screen.getByTestId('mypage-menu-settings')).toHaveAttribute('href', '/mypage/settings');
  });

  it('shows the current subscription status as the subscription menu preview', async () => {
    renderScreen();
    const menu = await screen.findByTestId('mypage-menu-subscription');
    expect(menu).toHaveTextContent('구독 없음');
  });
});
