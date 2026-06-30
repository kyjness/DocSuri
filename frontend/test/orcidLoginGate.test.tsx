import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));

async function renderSignup() {
  const { SignupForm } = await import('@/components/SignupForm');
  render(<SignupForm />);
}

afterEach(() => {
  delete process.env.NEXT_PUBLIC_ORCID_LOGIN_ENABLED;
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
});
