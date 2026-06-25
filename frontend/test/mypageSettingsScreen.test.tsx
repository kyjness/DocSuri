import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MyPageSettingsScreen } from '@/components/mypage/MyPageSettingsScreen';
import { SessionProvider } from '@/components/session/SessionContext';
import { ThemeProvider } from '@/components/theme/ThemeContext';
import { mockLogin } from '@/mocks/accountFixtures';
import { resetMypageFixtures } from '@/mocks/mypageFixtures';

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

function renderScreen() {
  return render(
    <ThemeProvider>
      <SessionProvider>
        <MyPageSettingsScreen />
      </SessionProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  mockLogin('mypage-settings-test@example.com');
  resetMypageFixtures();
  push.mockClear();
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});

describe('MyPageSettingsScreen (U10)', () => {
  it('shows mandatory consents read-only and toggles the optional nightly-push consent', async () => {
    renderScreen();
    const checkbox = await screen.findByTestId('mypage-consent-nightly-push');
    expect(checkbox).not.toBeChecked();
    await userEvent.click(checkbox);
    await waitFor(() => expect(checkbox).toBeChecked());
  });

  it('toggles dark mode, applies the data-theme attribute, and persists it (per-device, no API call)', async () => {
    renderScreen();
    const toggle = await screen.findByTestId('mypage-dark-mode');
    expect(toggle).not.toBeChecked();
    expect(document.documentElement.getAttribute('data-theme')).toBeNull();

    await userEvent.click(toggle);
    await waitFor(() => expect(toggle).toBeChecked());
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(window.localStorage.getItem('docsuri-theme')).toBe('dark');

    await userEvent.click(toggle);
    await waitFor(() => expect(toggle).not.toBeChecked());
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('shows the dark-mode toggle pre-checked when the OS prefers dark and nothing is stored yet', async () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = (query: string) =>
      ({
        matches: true,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as MediaQueryList;

    renderScreen();
    const toggle = await screen.findByTestId('mypage-dark-mode');
    await waitFor(() => expect(toggle).toBeChecked());
    // Reading the OS preference is display-only — it must not get persisted/applied until
    // the user actually touches the toggle (otherwise every OS-dark visitor would silently
    // "opt in" to a stored override they never asked for).
    expect(document.documentElement.getAttribute('data-theme')).toBeNull();
    expect(window.localStorage.getItem('docsuri-theme')).toBeNull();

    window.matchMedia = originalMatchMedia;
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
