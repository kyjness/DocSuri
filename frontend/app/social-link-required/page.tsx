import Link from 'next/link';
import pageStyles from '../page.module.css';
import formStyles from '@/components/AuthForm.module.css';
import { AppHeader } from '@/components/AppHeader';

// /social-link-required (FR-27/BR-A9 H1). The OIDC callback redirects here when the Google email
// matches an EXISTING password account — auto-merge is refused (account-takeover guard). The user
// proves ownership by logging in with their password; the pending social identity is then confirmed
// (POST /auth/social/link) on that password login.
export default function SocialLinkRequiredPage() {
  return (
    <div className={pageStyles.screen}>
      <AppHeader title="소셜 계정 연결" backHref="/login" />
      <div className={formStyles.form}>
        <p className={formStyles.formNotice} data-testid="social-link-required-notice">
          이 Google 계정의 이메일과 동일한 주소로 이미 가입된 계정이 있어요. 보안을 위해 자동으로
          연결하지 않습니다. 기존 비밀번호로 로그인하시면 Google 계정이 자동으로 연결됩니다.
        </p>
        <Link
          href="/login"
          className={formStyles.socialButton}
          data-testid="social-link-required-login"
        >
          비밀번호로 로그인
        </Link>
      </div>
    </div>
  );
}
