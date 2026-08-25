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
const refresh = vi.fn().mockResolvedValue(undefined);
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));
vi.mock('@/components/session/SessionContext', () => ({
  useSession: () => ({ status: 'anonymous', refresh }),
}));

async function renderHero() {
  const { HeroLanding } = await import('@/components/HeroLanding');
  render(<HeroLanding />);
}

beforeEach(() => {
  replace.mockReset();
  refresh.mockClear();
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

    // **경로가 계약이다.** 계정 라우터는 `/auth`에 붙어 있어 `/api/auth`로 부르면 라우터에
    // 없는 경로가 되고 미들웨어가 401을 낸다 — 배포본에서 실제로 그랬다.
    expect(fetchMock).toHaveBeenCalledWith('/bff/auth/demo', { method: 'POST' });
    // **세션 갱신이 이동보다 먼저다.** 쿠키는 응답에 실려 오지만 컨텍스트는 아직
    // anonymous라, 그대로 이동하면 `/search` 가드가 로그인 화면으로 되돌린다 — 사용자에게는
    // "버튼을 눌렀는데 로그인 페이지로 간다"로 보인다(2026-08-25 화면에서 발견).
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/search'));
    expect(refresh).toHaveBeenCalled();
    expect(refresh.mock.invocationCallOrder[0]).toBeLessThan(
      replace.mock.invocationCallOrder[0],
    );
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
