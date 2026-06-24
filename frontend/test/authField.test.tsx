import { describe, it, expect } from 'vitest';
import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthField } from '@/components/AuthField';

// Exercises the input affordances: password show/hide toggle and the email
// clear (✕) — including its inert/disabled state while the field is empty.

function Harness({ type, initial = '' }: { type: 'email' | 'password'; initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <AuthField
      id={`f-${type}`}
      label={type === 'email' ? '이메일' : '비밀번호'}
      type={type}
      value={value}
      onChange={setValue}
      autoComplete="off"
      testId={`f-${type}`}
    />
  );
}

describe('AuthField', () => {
  it('toggles password visibility via the reveal button', async () => {
    const user = userEvent.setup();
    render(<Harness type="password" initial="secret" />);
    const input = screen.getByTestId('f-password');
    const reveal = screen.getByTestId('f-password-reveal');

    expect(input).toHaveAttribute('type', 'password');
    expect(reveal).toHaveAttribute('aria-pressed', 'false');

    await user.click(reveal);
    expect(input).toHaveAttribute('type', 'text');
    expect(reveal).toHaveAttribute('aria-pressed', 'true');

    await user.click(reveal);
    expect(input).toHaveAttribute('type', 'password');
  });

  it('disables the email clear (✕) button while the field is empty', () => {
    render(<Harness type="email" />);
    expect(screen.getByTestId('f-email-clear')).toBeDisabled();
  });

  it('clears the email and returns focus when ✕ is clicked', async () => {
    const user = userEvent.setup();
    render(<Harness type="email" />);
    const input = screen.getByTestId('f-email');
    await user.type(input, 'a@b.com');
    expect(input).toHaveValue('a@b.com');

    const clear = screen.getByTestId('f-email-clear');
    expect(clear).toBeEnabled();
    await user.click(clear);

    expect(input).toHaveValue('');
    expect(input).toHaveFocus();
  });
});
