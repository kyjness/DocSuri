import styles from '../../../page.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { BottomNav } from '@/components/BottomNav';
import { MyPageLibraryScreen } from '@/components/mypage/MyPageLibraryScreen';

// 최근 본 논문 탭 (U10, mock until U9's paper_opened 이벤트가 머지됨).
export default function MyPageRecentPage() {
  return (
    <RouteGuard redirectTo="/mypage/library/recent">
      <div className={styles.screen}>
        <AppHeader title="관심 논문 · 최근 본" backHref="/mypage" />
        <MyPageLibraryScreen active="recent" />
      </div>
      <BottomNav />
    </RouteGuard>
  );
}
