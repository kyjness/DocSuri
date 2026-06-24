import styles from '../../page.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { BottomNav } from '@/components/BottomNav';
import { HistoryScreen } from '@/components/library/HistoryScreen';

// Search-history route (protected, US-L3).
export default function HistoryPage() {
  return (
    <RouteGuard redirectTo="/library/history">
      <div className={styles.screen}>
        <AppHeader title="DocSuri" />
        <HistoryScreen />
        <BottomNav />
      </div>
    </RouteGuard>
  );
}
