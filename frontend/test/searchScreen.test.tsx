import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchScreen } from '@/components/SearchScreen';
import { clearSearchSnapshot, getSearchSnapshot } from '@/lib/search/searchCache';

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
    clearSearchSnapshot(); // isolate the module-level search cache between cases
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

  it('shows the 내 관심 주제 반영 indicator with an off entry point when meta.personalized=true (US-P4)', async () => {
    await submit('맞춤 transformer');
    expect(await screen.findByTestId('result-list')).toBeInTheDocument();

    const indicator = screen.getByTestId('personalized-indicator');
    expect(indicator).toHaveTextContent('내 관심 주제 반영');
    // Off entry point reuses the existing 맞춤 서비스 kill-switch in settings — no new toggle.
    expect(screen.getByTestId('personalized-off-link')).toHaveAttribute('href', '/mypage/settings');
  });

  it('hides the personalization indicator when meta.personalized is absent', async () => {
    await submit('transformer attention');
    expect(await screen.findByTestId('result-list')).toBeInTheDocument();
    expect(screen.queryByTestId('personalized-indicator')).not.toBeInTheDocument();
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

describe('SearchScreen result persistence (back-navigation)', () => {
  beforeEach(() => {
    push.mockReset();
    clearSearchSnapshot();
  });

  it('restores the previous results on remount and ✕ drops them', async () => {
    const first = render(<SearchScreen />);
    await submit('transformer attention');
    expect(await screen.findByTestId('result-list')).toBeInTheDocument();
    first.unmount();

    // Remount (as if returning from a paper detail) → results + input restored, no re-search.
    const second = render(<SearchScreen />);
    expect(screen.getByTestId('result-list')).toBeInTheDocument();
    expect(screen.getByTestId('search-input')).toHaveValue('transformer attention');

    // ✕ dismisses the whole search; the snapshot is dropped so a later remount starts blank.
    await userEvent.setup().click(screen.getByTestId('search-clear'));
    expect(screen.queryByTestId('result-list')).not.toBeInTheDocument();
    second.unmount();

    render(<SearchScreen />);
    expect(screen.queryByTestId('result-list')).not.toBeInTheDocument();
    expect(screen.getByTestId('search-input')).toHaveValue('');
  });

  // 목록만 되살리고 스크롤을 빼면 화면은 복원되는데 매번 맨 위로 올라간다 — 스무 번째
  // 카드를 눌렀다 돌아온 사람이 그때마다 다시 내려와야 한다.
  it('returns to the position the list was left at', async () => {
    const first = render(<SearchScreen />);
    await submit('transformer attention');
    expect(await screen.findByTestId('result-list')).toBeInTheDocument();

    // 스크롤 → 카드 진입(언마운트). 위치는 스크롤 이벤트로 적히므로 언마운트 타이밍과 무관하다.
    window.scrollY = 640;
    window.dispatchEvent(new Event('scroll'));
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
    expect(getSearchSnapshot()?.scrollY).toBe(640);
    first.unmount();

    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    render(<SearchScreen />);
    expect(scrollTo).toHaveBeenCalledWith(0, 640);
    scrollTo.mockRestore();
  });

  // 링크를 누르면 전환 과정에서 브라우저가 스크롤을 0으로 되돌리는데, 그 이벤트가 언마운트보다
  // 먼저 도착한다. 그것을 그대로 적으면 복원할 값이 사라진다 — 배포본에서 "됐다 안 됐다"로 났고,
  // 경합이라 그 모양이 된다. e2e(search-scroll-restore.spec.ts)가 실제 브라우저로 잡지만
  // CI의 frontend lane은 e2e를 안 돌리므로 같은 불변식을 여기서도 고정한다.
  it('keeps the position a link click captured, not the transition reset that follows', async () => {
    render(<SearchScreen />);
    await submit('transformer attention');
    expect(await screen.findByTestId('result-list')).toBeInTheDocument();

    window.scrollY = 640;
    window.dispatchEvent(new Event('scroll'));
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
    expect(getSearchSnapshot()?.scrollY).toBe(640);

    // 카드 링크 클릭 — jsdom이 href를 따라가지 않게 기본 동작만 막고 이벤트는 그대로 흘린다.
    const card = screen.getAllByTestId('result-card-title')[0];
    const swallow = (e: Event) => e.preventDefault();
    document.addEventListener('click', swallow);
    card.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    document.removeEventListener('click', swallow);

    // 전환이 스크롤을 0으로 되돌린다.
    window.scrollY = 0;
    window.dispatchEvent(new Event('scroll'));
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));

    expect(getSearchSnapshot()?.scrollY).toBe(640);
  });

  it('starts a new search at the top instead of the old position', async () => {
    render(<SearchScreen />);
    await submit('transformer attention');
    expect(await screen.findByTestId('result-list')).toBeInTheDocument();

    window.scrollY = 640;
    window.dispatchEvent(new Event('scroll'));
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
    expect(getSearchSnapshot()?.scrollY).toBe(640);

    await submit('graph neural network');
    expect(await screen.findByTestId('result-list')).toBeInTheDocument();
    expect(getSearchSnapshot()?.scrollY).toBe(0);
  });
});
