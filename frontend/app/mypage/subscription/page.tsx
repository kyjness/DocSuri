import styles from '../../page.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { BottomNav } from '@/components/BottomNav';
import { MyPageSubscriptionScreen } from '@/components/mypage/MyPageSubscriptionScreen';

// 내 구독 (U10) — 구독 상태 + PREMIUM 혜택 안내.
export default function MyPageSubscriptionPage() {
  return (
    <RouteGuard redirectTo="/mypage/subscription">
      <div className={styles.screen}>
        <AppHeader title="내 구독" backHref="/mypage" />
        <MyPageSubscriptionScreen />
      </div>
      <BottomNav />
    </RouteGuard>
  );
}
