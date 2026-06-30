import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouteGuard } from '@/components/RouteGuard';
import { SessionProvider, useSession } from '@/components/session/SessionContext';
import { mockLogin, mockLogout } from '@/mocks/accountFixtures';

const replace = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace }),
}));

function LogoutButton() {
  const { signOut } = useSession();
  return (
    <button type="button" onClick={() => void signOut()}>
      로그아웃
    </button>
  );
}

beforeEach(() => {
  mockLogout();
  replace.mockClear();
});

describe('RouteGuard', () => {
  it('uses neutral loading copy while checking a protected route', () => {
    render(
      <SessionProvider>
        <RouteGuard redirectTo="/search">
          <p>protected</p>
        </RouteGuard>
      </SessionProvider>,
    );

    expect(screen.getByText('페이지를 불러오는 중…')).toBeInTheDocument();
    expect(screen.queryByText('검색 중…')).not.toBeInTheDocument();
  });

  it('shows logout-specific loading copy while signing out', async () => {
    mockLogin('route-guard-test@example.com');

    render(
      <SessionProvider>
        <RouteGuard redirectTo="/search">
          <LogoutButton />
        </RouteGuard>
      </SessionProvider>,
    );

    await userEvent.click(await screen.findByRole('button', { name: '로그아웃' }));

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: '로그아웃' })).not.toBeInTheDocument(),
    );
    expect(screen.getByText('로그아웃 중…')).toBeInTheDocument();
    expect(screen.queryByText('검색 중…')).not.toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
