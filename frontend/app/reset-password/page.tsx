import { Suspense } from 'react';
import styles from '../page.module.css';
import { AppHeader } from '@/components/AppHeader';
import { ResetPasswordForm } from '@/components/ResetPasswordForm';

// Password-reset route (FR-26/BR-A8). The form reads ?token= to switch between request and
// confirm, so it sits under Suspense (useSearchParams). The emailed reset link points here.
export default function ResetPasswordPage() {
  return (
    <div className={styles.screen}>
      <AppHeader title="비밀번호 재설정" backHref="/login" />
      <Suspense fallback={null}>
        <ResetPasswordForm />
      </Suspense>
    </div>
  );
}
