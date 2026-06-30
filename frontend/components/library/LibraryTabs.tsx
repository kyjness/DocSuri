import Link from 'next/link';
import styles from './Library.module.css';

// LibraryTabs — sub-navigation across the three personal-data screens (US-L1/2/3).
type Tab = 'library' | 'saved' | 'history';

const TABS: { key: Tab; href: string; label: string; testid: string }[] = [
  { key: 'saved', href: '/library/saved', label: '저장한 검색', testid: 'tab-saved' },
  { key: 'history', href: '/library/history', label: '검색 이력', testid: 'tab-history' },
];

export function LibraryTabs({ active }: { active: Tab }) {
  return (
    <nav className={styles.tabs} aria-label="라이브러리 메뉴">
      {TABS.map((t) => (
        <Link
          key={t.key}
          href={t.href}
          className={`${styles.tab} ${t.key === active ? styles.tabActive : ''}`}
          aria-current={t.key === active ? 'page' : undefined}
          data-testid={t.testid}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
