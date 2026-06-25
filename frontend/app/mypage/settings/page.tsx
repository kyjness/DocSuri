import styles from '../../page.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { BottomNav } from '@/components/BottomNav';
import { MyPageSettingsScreen } from '@/components/mypage/MyPageSettingsScreen';

// 설정 (U10) — 동의 철회 / 로그아웃 / 회원탈퇴.
export default function MyPageSettingsPage() {
  return (
    <RouteGuard redirectTo="/mypage/settings">
      <div className={styles.screen}>
        <AppHeader title="설정" backHref="/mypage" />
        <MyPageSettingsScreen />
      </div>
      <BottomNav />
    </RouteGuard>
  );
}
