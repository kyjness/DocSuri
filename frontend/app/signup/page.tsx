import styles from '../page.module.css';
import { AppHeader } from '@/components/AppHeader';
import { SignupForm } from '@/components/SignupForm';

// Signup route (US-A1).
export default function SignupPage() {
  // Back-mode header (← 가입하기) to match the in-app sub-route pattern; the header title
  // carries the screen name, so the page no longer repeats it as a separate heading.
  return (
    <div className={styles.screen}>
      <AppHeader title="가입하기" backHref="/" />
      <SignupForm />
    </div>
  );
}
