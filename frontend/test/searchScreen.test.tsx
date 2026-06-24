import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchScreen } from '@/components/SearchScreen';

// SearchScreen drives the real MockTransport (mock-first), so these exercise the
// full state machine without a backend.

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

async function submit(query: string) {
  const user = userEvent.setup();
  await user.clear(screen.getByTestId('search-input'));
  if (query) await user.type(screen.getByTestId('search-input'), query);
  await user.click(screen.getByTestId('search-submit'));
}

describe('SearchScreen state machine', () => {
  beforeEach(() => {
    push.mockReset();
    render(<SearchScreen />);
  });

  it('blocks empty submit with an inline error (no request)', async () => {
    await submit('');
    expect(screen.getByTestId('search-inline-error')).toBeInTheDocument();
  });

  it('disables the clear (✕) button while the field is empty', () => {
    expect(screen.getByTestId('search-clear')).toBeDisabled();
  });

  it('clears the query and returns focus when ✕ is clicked', async () => {
    const user = userEvent.setup();
    const input = screen.getByTestId('search-input');
    await user.type(input, 'transformer');
    expect(input).toHaveValue('transformer');

    const clear = screen.getByTestId('search-clear');
    expect(clear).toBeEnabled();
    await user.click(clear);

    expect(input).toHaveValue('');
    expect(input).toHaveFocus();
  });

  it('renders a result list for a normal query', async () => {
    await submit('transformer attention');
    expect(await screen.findByTestId('result-list')).toBeInTheDocument();
    expect(screen.getAllByTestId('result-card').length).toBeGreaterThan(0);
  });

  it('distinguishes empty from abstain', async () => {
    await submit('없음 keyword');
    expect(await screen.findByTestId('state-view-empty')).toBeInTheDocument();

    await submit('기권 keyword');
    expect(await screen.findByTestId('state-view-abstain')).toBeInTheDocument();
  });

  it('shows a degraded banner', async () => {
    await submit('저하 keyword');
    expect(await screen.findByTestId('degraded-banner')).toBeInTheDocument();
  });

  it('surfaces a retry on server error', async () => {
    await submit('오류 keyword');
    expect(await screen.findByTestId('state-view-error')).toBeInTheDocument();
    expect(screen.getByTestId('state-view-retry')).toBeInTheDocument();
  });

  it('surfaces backend validation errors inline and sets aria-invalid', async () => {
    const input = screen.getByTestId('search-input');
    await submit('유효 keyword');
    
    // 1. Should display the validation error message inline
    const inlineError = await screen.findByTestId('search-inline-error');
    expect(inlineError).toBeInTheDocument();
    expect(inlineError).toHaveTextContent('검색어를 확인해 주세요.');
    
    // 2. Input field should have aria-invalid="true"
    expect(input).toHaveAttribute('aria-invalid', 'true');
    
    // 3. StateView for invalid should also be in the document and contain the field name as an attribute
    const stateView = await screen.findByTestId('state-view-invalid');
    expect(stateView).toBeInTheDocument();
    expect(stateView).toHaveAttribute('data-field', 'query');
  });
});
