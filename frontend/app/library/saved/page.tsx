import styles from '../../page.module.css';
import { RouteGuard } from '@/components/RouteGuard';
import { AppHeader } from '@/components/AppHeader';
import { BottomNav } from '@/components/BottomNav';
import { SavedSearchScreen } from '@/components/library/SavedSearchScreen';

// Saved-searches route (protected, US-L1).
export default function SavedSearchesPage() {
  return (
    <RouteGuard redirectTo="/library/saved">
      <div className={styles.screen}>
        <AppHeader title="DocSuri" />
        <SavedSearchScreen />
        <BottomNav />
      </div>
    </RouteGuard>
  );
}
