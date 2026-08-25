/**
 * 가입 없이 둘러보기 — 버튼은 **켰을 때만** 뜬다.
 *
 * 가입 장벽을 없애는 공개 표면이라 기본이 off여야 한다. 프론트 게이트만으로는 숨긴 것이
 * 아니므로(엔드포인트가 열려 있으면 주소만 알면 된다) 백엔드에도 같은 이름의 스위치가 있고
 * 꺼져 있으면 404다 — 그쪽은 `backend/tests/test_accounts_demo_login.py`가 본다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const replace = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));
vi.mock('@/components/session/SessionContext', () => ({
  useSession: () => ({ status: 'anonymous' }),
}));

async function renderHero() {
  const { HeroLanding } = await import('@/components/HeroLanding');
  render(<HeroLanding />);
}

beforeEach(() => {
  replace.mockReset();
});

afterEach(() => {
  delete process.env.NEXT_PUBLIC_DOCSURI_DEMO_LOGIN_ENABLED;
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe('Demo login gate', () => {
  it('hides the button by default', async () => {
    delete process.env.NEXT_PUBLIC_DOCSURI_DEMO_LOGIN_ENABLED;
    vi.resetModules();

    await renderHero();

    expect(screen.queryByTestId('hero-cta-demo')).not.toBeInTheDocument();
    // 회원가입·로그인은 남는다 — 숨기는 것은 3순위 하나다.
    expect(screen.getByTestId('hero-cta-signup')).toBeInTheDocument();
    expect(screen.getByTestId('hero-cta-login')).toBeInTheDocument();
  });

  it('starts a session and replaces history when enabled', async () => {
    process.env.NEXT_PUBLIC_DOCSURI_DEMO_LOGIN_ENABLED = '1';
    vi.resetModules();
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchMock);

    await renderHero();
    await userEvent.click(screen.getByTestId('hero-cta-demo'));

    expect(fetchMock).toHaveBeenCalledWith('/bff/api/auth/demo', { method: 'POST' });
    // `replace`여야 한다 — `push`면 뒤로 가기로 랜딩에 돌아와 계정을 또 만든다.
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/search'));
  });

  it('surfaces a failure instead of silently doing nothing', async () => {
    process.env.NEXT_PUBLIC_DOCSURI_DEMO_LOGIN_ENABLED = '1';
    vi.resetModules();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }));

    await renderHero();
    await userEvent.click(screen.getByTestId('hero-cta-demo'));

    expect(await screen.findByTestId('hero-demo-error')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    // 버튼이 다시 눌리는 상태로 돌아와야 한다 — 실패 후 영영 비활성이면 막다른 길이다.
    expect(screen.getByTestId('hero-cta-demo')).not.toBeDisabled();
  });
});
