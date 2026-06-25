import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ResetPasswordForm } from '@/components/ResetPasswordForm';

// FR-26/BR-A8 — request mode (no ?token=) vs confirm mode (?token= present).
const push = vi.fn();
let token: string | null = null;
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => ({ get: (k: string) => (k === 'token' ? token : null) }),
}));

beforeEach(() => {
  push.mockClear();
  token = null;
});

describe('ResetPasswordForm (FR-26)', () => {
  it('request mode: submitting an email shows the enumeration-safe notice', async () => {
    render(<ResetPasswordForm />);
    await userEvent.type(screen.getByTestId('reset-email'), 'user@docsuri.org');
    await userEvent.click(screen.getByTestId('reset-request-submit'));
    // 성공/실패와 무관하게 동일한 일반 안내(계정 열거 방지)를 보여준다.
    expect(await screen.findByTestId('reset-request-done')).toBeInTheDocument();
  });

  it('confirm mode (token present): renders the new-password form', () => {
    token = 'tok-123';
    render(<ResetPasswordForm />);
    expect(screen.getByTestId('reset-confirm-form')).toBeInTheDocument();
    expect(screen.getByTestId('reset-new-password')).toBeInTheDocument();
    expect(screen.getByTestId('reset-confirm-password')).toBeInTheDocument();
  });
});
