import { Suspense } from 'react';
import styles from '../page.module.css';
import { AppHeader } from '@/components/AppHeader';
import { VerifyEmail } from '@/components/VerifyEmail';

// Email-verification route (US-A1, BR-A5). The emailed activation link lands here;
// VerifyEmail reads ?token= (search params), so it sits under Suspense.
export default function VerifyEmailPage() {
  return (
    <div className={styles.screen}>
      <AppHeader title="DocSuri" />
      <h2 className={styles.heading}>이메일 인증</h2>
      <Suspense fallback={null}>
        <VerifyEmail />
      </Suspense>
    </div>
  );
}
