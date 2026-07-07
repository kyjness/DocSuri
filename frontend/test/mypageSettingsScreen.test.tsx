import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MyPageSettingsScreen } from '@/components/mypage/MyPageSettingsScreen';
import { SessionProvider } from '@/components/session/SessionContext';
import { ThemeProvider } from '@/components/theme/ThemeContext';
import { mockLogin } from '@/mocks/accountFixtures';
import { resetMypageFixtures } from '@/mocks/mypageFixtures';
import { ApiClient } from '@/lib/api/apiClient';
import { resetMockNotionConnection } from '@/lib/api/mockTransport';

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
  resetMockNotionConnection();
  push.mockClear();
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('MyPageSettingsScreen (U10)', () => {
  it('shows mandatory consents read-only and toggles the optional nightly-push consent', async () => {
    renderScreen();
    const checkbox = await screen.findByTestId('mypage-consent-nightly-push');
    expect(checkbox).not.toBeChecked();
    await userEvent.click(checkbox);
    await waitFor(() => expect(checkbox).toBeChecked());
  });

  it('deletes personalization logs and resets the profile from settings', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderScreen();

    await screen.findByTestId('mypage-personalization-data');
    await userEvent.click(screen.getByTestId('mypage-personalization-delete-events'));
    await waitFor(() =>
      expect(screen.getByTestId('mypage-action-notice')).toHaveTextContent(
        '개인맞춤 행동 로그 0건을 삭제했습니다.',
      ),
    );

    await userEvent.click(screen.getByTestId('mypage-personalization-reset-profile'));
    await waitFor(() =>
      expect(screen.getByTestId('mypage-action-notice')).toHaveTextContent(
        '개인맞춤 프로필을 초기화했습니다.',
      ),
    );
  });

  it('keeps the settings page open when personalization settings are unavailable', async () => {
    vi.spyOn(ApiClient.prototype, 'getPersonalizationSettings').mockRejectedValueOnce(
      new Error('disabled'),
    );
    renderScreen();

    expect(await screen.findByTestId('mypage-settings-screen')).toBeInTheDocument();
    expect(screen.getByTestId('mypage-personalization-enabled')).toBeDisabled();
    expect(screen.getByTestId('mypage-personalization-unavailable')).toHaveTextContent(
      '맞춤 서비스 설정을 불러오지 못했습니다.',
    );
  });

  it('does not call destructive personalization actions when confirmation is dismissed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    const deleteSpy = vi.spyOn(ApiClient.prototype, 'deletePersonalizationEvents');
    renderScreen();

    await screen.findByTestId('mypage-personalization-data');
    await userEvent.click(screen.getByTestId('mypage-personalization-delete-events'));

    expect(window.confirm).toHaveBeenCalled();
    expect(deleteSpy).not.toHaveBeenCalled();
    expect(screen.queryByTestId('mypage-action-notice')).not.toBeInTheDocument();
  });

  it('toggles the personalization setting', async () => {
    renderScreen();
    const checkbox = await screen.findByTestId('mypage-personalization-enabled');
    expect(checkbox).toBeChecked();

    await userEvent.click(checkbox);

    await waitFor(() => expect(checkbox).not.toBeChecked());
  });

  it('saves and disconnects a personal Notion connection from settings', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderScreen();

    expect(await screen.findByTestId('mypage-notion-connection')).toBeInTheDocument();
    expect(screen.getByTestId('mypage-notion-status')).toHaveTextContent(
      '연결된 Notion이 없습니다.',
    );
    expect(screen.queryByTestId('mypage-notion-error')).not.toBeInTheDocument();

    await userEvent.type(
      screen.getByTestId('mypage-notion-token'),
      'not a real notion integration value',
    );
    await userEvent.click(screen.getByTestId('mypage-notion-save'));
    expect(screen.getByTestId('mypage-notion-error')).toHaveTextContent(
      '상위 페이지 ID',
    );

    await userEvent.type(screen.getByTestId('mypage-notion-parent-page-id'), '1'.repeat(32));
    await userEvent.click(screen.getByTestId('mypage-notion-save'));

    await waitFor(() =>
      expect(screen.getByTestId('mypage-action-notice')).toHaveTextContent(
        'Notion 연결을 저장했습니다.',
      ),
    );
    expect(screen.getByTestId('mypage-notion-status')).toHaveTextContent('연결됨');

    await userEvent.click(screen.getByTestId('mypage-notion-disconnect'));
    await waitFor(() =>
      expect(screen.getByTestId('mypage-action-notice')).toHaveTextContent(
        'Notion 연결을 해제했습니다.',
      ),
    );
    expect(screen.getByTestId('mypage-notion-status')).toHaveTextContent(
      '연결된 Notion이 없습니다.',
    );
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
