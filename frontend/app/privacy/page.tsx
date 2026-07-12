import type { Metadata } from 'next';
import styles from '../legal.module.css';
import { AppHeader } from '@/components/AppHeader';

// 개인정보처리방침 (Privacy Policy) — static server route at /privacy.
// Primary driver: Google/social OAuth consent-screen verification requires a
// publicly reachable privacy policy URL that accurately discloses how Google
// user data is used. The data-practice sections below reflect the real system
// (accounts, Google/ORCID OIDC, personalization events, AWS/Cohere subprocessors).
// Entity/contact facts (operator, DPO, Seoul region, retention) are filled; legal
// should still review before this is treated as final.
// ponytail: static JSX, no CMS/markdown pipeline — legal text barely changes. Add a
// content pipeline only if legal starts requiring versioned revisions.

export const metadata: Metadata = {
  title: '개인정보처리방침 — DocSuri',
  description: 'DocSuri 개인정보처리방침',
};

export default function PrivacyPage() {
  return (
    <div className={styles.screen}>
      <AppHeader backHref="/" />
      <h1 className={styles.title}>개인정보처리방침</h1>
      <p className={styles.updated}>시행일: 2026년 7월 8일 · 최종 개정일: 2026년 7월 8일</p>

      <p className={styles.body}>
        DocSuri(이하 “회사”)은 「개인정보 보호법」 등 관련 법령을 준수하며, DocSuri(이하 “서비스”)
        이용자의 개인정보를 다음과 같이 처리합니다.
      </p>

      <h2 className={styles.h2}>1. 수집하는 개인정보 항목</h2>
      <p className={styles.body}>서비스는 다음의 개인정보를 수집합니다.</p>
      <ul className={styles.list}>
        <li>이메일 회원가입: 이메일 주소, 비밀번호(단방향 해시로만 저장)</li>
        <li>
          소셜 로그인(Google): OpenID 인증 시 <strong>openid, email</strong> 범위로 이메일 주소와
          Google 계정 식별자(sub)를 전달받습니다. 이름·프로필 사진 등 그 밖의 Google 계정 정보는
          수집하지 않습니다.
        </li>
        <li>
          소셜 로그인(ORCID): ORCID iD와 이름을 전달받습니다. ORCID는 이메일을 제공하지 않으므로
          이메일은 수집하지 않습니다.
        </li>
        <li>
          서비스 이용 과정에서 자동 생성·수집: 검색어, 조회한 논문, 라이브러리 저장 등 이용
          이벤트(개인화 제공 목적), 접속 로그, 세션 쿠키
        </li>
      </ul>

      <h2 className={styles.h2}>2. 개인정보의 수집·이용 목적</h2>
      <ul className={styles.list}>
        <li>회원 식별 및 로그인 인증</li>
        <li>논문 검색·요약·번역·라이브러리 등 서비스 제공</li>
        <li>이용 이력 기반 개인화 추천</li>
        <li>보안, 부정 이용 방지, 문의 응대</li>
      </ul>

      <h2 className={styles.h2}>3. 보유 및 이용 기간</h2>
      <p className={styles.body}>
        회원 탈퇴 시 계정을 비활성화(소프트 삭제)하여 30일간 보관하며, 이 기간 내에는 재로그인으로
        복구할 수 있습니다. 30일이 지나면 계정 정보와 서비스 이용 기록(라이브러리·검색 이력·이용
        이벤트 등)을 지체 없이 일괄 파기하며, 별도의 백업 사본을 보관하지 않습니다.
      </p>
      <p className={styles.body}>
        서비스 이용 중 수집한 개인화용 행동 이벤트는 최근 90일분만 보관하고 이후 자동 삭제합니다.
      </p>

      <h2 className={styles.h2}>4. 개인정보의 제3자 제공</h2>
      <p className={styles.body}>
        회사는 이용자의 개인정보를 원칙적으로 외부에 제공하지 않으며, 법령에 근거하거나 이용자의
        동의가 있는 경우에 한하여 제공합니다.
      </p>

      <h2 className={styles.h2}>5. 개인정보 처리의 위탁 및 국외 이전</h2>
      <p className={styles.body}>서비스 제공을 위해 다음 업체에 개인정보 처리를 위탁합니다.</p>
      <ul className={styles.list}>
        <li>
          Amazon Web Services, Inc. — 클라우드 인프라 운영 및 이메일(SES) 발송 (처리 리전: 대한민국
          서울, ap-northeast-2)
        </li>
        <li>Cohere Inc. — 논문 임베딩·검색 처리</li>
        <li>Google LLC — 소셜 로그인 인증</li>
      </ul>
      <p className={styles.body}>
        이 중 Cohere Inc.와 Google LLC는 미국에서 개인정보를 처리하여 국외 이전이 발생합니다. 이전
        항목은 Cohere의 경우 검색어, Google의 경우 이메일 주소 및 계정 식별자이며, 이전 목적은 각각
        임베딩·검색 처리와 로그인 인증입니다. 보유·이용 기간은 위 제3항 및 각 사의 정책에 따르며,
        이용자는 회원가입 및 소셜 로그인 과정에서 국외 이전에 동의한 것으로 봅니다.
      </p>

      <h2 className={styles.h2}>6. 정보주체의 권리 및 행사 방법</h2>
      <p className={styles.body}>
        이용자는 언제든지 개인정보 열람·정정·삭제·처리정지를 요구할 수 있으며, 마이페이지에서 동의
        철회 및 회원 탈퇴를 직접 수행할 수 있습니다.
      </p>

      <h2 className={styles.h2}>7. 개인정보의 파기 절차 및 방법</h2>
      <p className={styles.body}>
        보유 기간이 경과하거나 처리 목적이 달성된 개인정보는 지체 없이 파기합니다. 전자적 파일은
        복구가 불가능한 방법으로 삭제합니다.
      </p>

      <h2 className={styles.h2}>8. 개인정보의 안전성 확보 조치</h2>
      <ul className={styles.list}>
        <li>비밀번호 단방향 해시 저장, 전송 구간 HTTPS 암호화</li>
        <li>세션 정보는 httpOnly 보안 쿠키로 관리</li>
        <li>접근 권한 통제 및 최소 수집 원칙 적용</li>
      </ul>

      <h2 className={styles.h2}>9. 쿠키의 사용</h2>
      <p className={styles.body}>
        서비스는 로그인 세션 유지를 위해 httpOnly 세션 쿠키를 사용합니다. 이용자는 브라우저 설정을
        통해 쿠키 저장을 거부할 수 있으나, 이 경우 로그인이 제한될 수 있습니다.
      </p>

      <h2 className={styles.h2}>10. 개인정보 보호책임자</h2>
      <ul className={styles.list}>
        <li>성명: 조준희 (개인정보 보호책임자)</li>
        <li>연락처(이메일): corpseonthemission@icloud.com</li>
      </ul>

      <h2 className={styles.h2}>11. 고지의 의무</h2>
      <p className={styles.body}>
        본 방침의 내용 추가·삭제·수정이 있을 경우 시행 최소 7일 전부터 서비스 내 공지를 통해
        고지합니다.
      </p>
    </div>
  );
}
