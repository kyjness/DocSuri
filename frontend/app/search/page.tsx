import styles from '../page.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { BottomNav } from '@/components/BottomNav';
import { SearchScreen } from '@/components/SearchScreen';

// Search route (protected, US-H1/D1). RouteGuard reflects auth client-side;
// backend 401/403 stays authoritative.
export default function SearchPage() {
  return (
    <RouteGuard redirectTo="/search">
      <div className={styles.screen}>
        <AppHeader title="DocSuri" />
        <SearchScreen />
        <BottomNav />
      </div>
    </RouteGuard>
  );
}
