import styles from '../page.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { BottomNav } from '@/components/BottomNav';
import { LibraryScreen } from '@/components/library/LibraryScreen';

// Library route (protected, US-L2). RouteGuard reflects auth client-side;
// backend 401/403 stays authoritative.
export default function LibraryPage() {
  return (
    <RouteGuard redirectTo="/library">
      <div className={styles.screen}>
        <AppHeader title="DocSuri" />
        <LibraryScreen />
      </div>
      <BottomNav />
    </RouteGuard>
  );
}
