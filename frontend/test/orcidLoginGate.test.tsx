import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

const push = vi.fn();
const session = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock('@/components/session/SessionContext', () => ({
  useSession: () => session,
}));

async function renderSignup() {
  const { SignupForm } = await import('@/components/SignupForm');
  render(<SignupForm />);
}

async function renderLogin() {
  const { LoginForm } = await import('@/components/LoginForm');
  render(<LoginForm />);
}

afterEach(() => {
  delete process.env.NEXT_PUBLIC_ORCID_LOGIN_ENABLED;
  session.refresh.mockReset();
  vi.resetModules();
});

describe('ORCID login gate', () => {
  it('hides ORCID social login by default', async () => {
    delete process.env.NEXT_PUBLIC_ORCID_LOGIN_ENABLED;
    vi.resetModules();

    await renderSignup();

    expect(screen.queryByTestId('signup-orcid')).not.toBeInTheDocument();
  });

  it('shows ORCID social login when enabled at build time', async () => {
    process.env.NEXT_PUBLIC_ORCID_LOGIN_ENABLED = '1';
    vi.resetModules();

    await renderSignup();

    expect(screen.getByTestId('signup-orcid')).toHaveAttribute(
      'href',
      '/auth/social/orcid/start',
    );
  });

  it('opens social OAuth starts in the top window', async () => {
    process.env.NEXT_PUBLIC_ORCID_LOGIN_ENABLED = '1';
    vi.resetModules();

    await renderSignup();
    await renderLogin();

    expect(screen.getByTestId('signup-google')).toHaveAttribute('target', '_top');
    expect(screen.getByTestId('signup-orcid')).toHaveAttribute('target', '_top');
    expect(screen.getByTestId('login-google')).toHaveAttribute('target', '_top');
    expect(screen.getByTestId('login-orcid')).toHaveAttribute('target', '_top');
  });
});
