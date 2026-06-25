import styles from '../../page.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { BottomNav } from '@/components/BottomNav';
import { MyPageLibraryScreen } from '@/components/mypage/MyPageLibraryScreen';

// 관심 논문 탭 (U10). RouteGuard reflects auth client-side; backend 401/403 stays authoritative.
export default function MyPageLibraryPage() {
  return (
    <RouteGuard redirectTo="/mypage/library">
      <div className={styles.screen}>
        <AppHeader title="관심 논문 · 최근 본" backHref="/mypage" />
        <MyPageLibraryScreen active="interest" />
      </div>
      <BottomNav />
    </RouteGuard>
  );
}
