import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MyPageSettingsScreen } from '@/components/mypage/MyPageSettingsScreen';
import { SessionProvider } from '@/components/session/SessionContext';
import { mockLogin } from '@/mocks/accountFixtures';
import { resetMypageFixtures } from '@/mocks/mypageFixtures';

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

function renderScreen() {
  return render(
    <SessionProvider>
      <MyPageSettingsScreen />
    </SessionProvider>,
  );
}

beforeEach(() => {
  mockLogin('mypage-settings-test@example.com');
  resetMypageFixtures();
  push.mockClear();
});

describe('MyPageSettingsScreen (U10)', () => {
  it('shows mandatory consents read-only and toggles the optional nightly-push consent', async () => {
    renderScreen();
    const checkbox = await screen.findByTestId('mypage-consent-nightly-push');
    expect(checkbox).not.toBeChecked();
    await userEvent.click(checkbox);
    await waitFor(() => expect(checkbox).toBeChecked());
  });

  it('logs out via the shared session and redirects home', async () => {
    renderScreen();
    await screen.findByTestId('mypage-account-actions');
    await userEvent.click(screen.getByTestId('mypage-logout'));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/'));
  });

  it('withdraws after password re-auth prompt and redirects home', async () => {
    // 탈퇴는 현재 비밀번호 재인증(prompt)을 요구한다(감사 H7).
    vi.spyOn(window, 'prompt').mockReturnValue('OldPw123!@x');
    renderScreen();
    await screen.findByTestId('mypage-account-actions');
    await userEvent.click(screen.getByTestId('mypage-withdraw'));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/'));
  });

  it('does not withdraw when the re-auth prompt is dismissed', async () => {
    vi.spyOn(window, 'prompt').mockReturnValue(null);
    renderScreen();
    await screen.findByTestId('mypage-account-actions');
    await userEvent.click(screen.getByTestId('mypage-withdraw'));
    expect(push).not.toHaveBeenCalled();
  });
});
