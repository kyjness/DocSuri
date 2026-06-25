import styles from '../page.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { BottomNav } from '@/components/BottomNav';
import { MyPageScreen } from '@/components/mypage/MyPageScreen';

// My Page route (U10, protected). RouteGuard reflects auth client-side; backend 401/403
// stays authoritative. BottomNav's "마이페이지" tab points here (see BottomNav.tsx).
export default function MyPagePage() {
  return (
    <RouteGuard redirectTo="/mypage">
      <div className={styles.screen}>
        <AppHeader title="DocSuri" />
        <MyPageScreen />
      </div>
      <BottomNav />
    </RouteGuard>
  );
}
