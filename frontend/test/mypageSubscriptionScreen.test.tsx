import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MyPageSubscriptionScreen } from '@/components/mypage/MyPageSubscriptionScreen';
import { mockLogin } from '@/mocks/accountFixtures';
import { resetMypageFixtures } from '@/mocks/mypageFixtures';

function renderScreen() {
  return render(<MyPageSubscriptionScreen />);
}

beforeEach(() => {
  mockLogin('mypage-subscription-test@example.com');
  resetMypageFixtures();
});

describe('MyPageSubscriptionScreen (U10)', () => {
  it('renders the PREMIUM benefits list alongside the subscription status', async () => {
    renderScreen();
    expect(await screen.findByTestId('mypage-subscription-status')).toHaveTextContent('구독 없음');
    expect(screen.getByTestId('mypage-subscription-benefits')).toBeInTheDocument();
  });

  it('subscribes then cancels — benefit retained (status flips to 해지 예약, not gone)', async () => {
    renderScreen();
    await screen.findByTestId('mypage-subscription');
    await userEvent.click(screen.getByTestId('mypage-subscription-subscribe'));
    await waitFor(() =>
      expect(screen.getByTestId('mypage-subscription-status')).toHaveTextContent('구독 중'),
    );
    await userEvent.click(screen.getByTestId('mypage-subscription-cancel'));
    await waitFor(() =>
      expect(screen.getByTestId('mypage-subscription-status')).toHaveTextContent('해지 예약'),
    );
  });
});
