import type { Metadata } from 'next';
import styles from '../legal.module.css';
import { AppHeader } from '@/components/AppHeader';

// 서비스 이용약관 (Terms of Service) — static server route at /terms.
// Linked from the landing footer and offered on the OAuth consent screen.
// ponytail: static JSX. Operator facts (법인명·관할·연락처) are filled;
// legal should still confirm before this is treated as final.

export const metadata: Metadata = {
  title: '서비스 이용약관 — DocSuri',
  description: 'DocSuri 서비스 이용약관',
};

export default function TermsPage() {
  return (
    <div className={styles.screen}>
      <AppHeader backHref="/" />
      <h1 className={styles.title}>서비스 이용약관</h1>
      <p className={styles.updated}>시행일: 2026년 7월 8일</p>

      <h2 className={styles.h2}>제1조 (목적)</h2>
      <p className={styles.body}>
        본 약관은 DocSuri(이하 “회사”)이 제공하는 DocSuri(이하 “서비스”)의 이용 조건 및 절차, 회사와
        이용자의 권리·의무를 정함을 목적으로 합니다.
      </p>

      <h2 className={styles.h2}>제2조 (정의)</h2>
      <ul className={styles.list}>
        <li>
          “서비스”란 AI·머신러닝 분야 arXiv 논문을 검색·요약·번역하고 근거를 제시하는 웹 서비스를
          말합니다.
        </li>
        <li>“이용자”란 본 약관에 따라 서비스를 이용하는 회원을 말합니다.</li>
      </ul>

      <h2 className={styles.h2}>제3조 (약관의 효력 및 변경)</h2>
      <p className={styles.body}>
        본 약관은 서비스 화면에 게시함으로써 효력이 발생합니다. 회사는 관련 법령을 위배하지 않는
        범위에서 약관을 변경할 수 있으며, 변경 시 시행일 및 사유를 명시하여 사전 공지합니다.
      </p>

      <h2 className={styles.h2}>제4조 (서비스의 내용)</h2>
      <p className={styles.body}>
        회사는 논문 검색, 핵심 요약, 번역, 근거(grounding) 표시, 라이브러리 저장, 개인화 추천 등의
        기능을 제공합니다. 서비스의 구체적 내용은 회사의 정책에 따라 변경될 수 있습니다.
      </p>

      <h2 className={styles.h2}>제5조 (회원가입 및 계정)</h2>
      <p className={styles.body}>
        이용자는 이메일 또는 소셜 로그인(Google, ORCID)을 통해 회원가입할 수 있습니다. 이용자는 계정
        정보의 정확성을 유지하고 비밀번호 등 인증 정보를 안전하게 관리할 책임이 있습니다.
      </p>

      <h2 className={styles.h2}>제6조 (이용자의 의무)</h2>
      <ul className={styles.list}>
        <li>타인의 계정·정보를 도용하거나 부정하게 이용하지 않습니다.</li>
        <li>서비스의 정상적 운영을 방해하는 행위를 하지 않습니다.</li>
        <li>관련 법령 및 본 약관을 준수합니다.</li>
      </ul>

      <h2 className={styles.h2}>제7조 (콘텐츠 및 지식재산권)</h2>
      <p className={styles.body}>
        서비스가 제공하는 논문 원문의 저작권은 arXiv 및 원저작자 등 정당한 권리자에게 귀속되며,
        서비스는 이를 학술적 참고 목적으로 제공합니다. 서비스 자체의 상표·디자인·소프트웨어에 대한
        권리는 회사에 귀속됩니다.
      </p>

      <h2 className={styles.h2}>제8조 (면책)</h2>
      <p className={styles.body}>
        AI가 생성하는 요약·번역·근거 표시는 참고용이며 정확성·완전성을 보증하지 않습니다. 이용자는
        학술적 판단 시 반드시 원문을 확인해야 하며, 회사는 이를 신뢰하여 발생한 결과에 대해 책임을
        지지 않습니다.
      </p>

      <h2 className={styles.h2}>제9조 (서비스의 중단·변경)</h2>
      <p className={styles.body}>
        회사는 시스템 점검, 장애, 불가항력 등의 사유로 서비스의 전부 또는 일부를 일시 중단하거나
        변경할 수 있으며, 가능한 경우 사전에 공지합니다.
      </p>

      <h2 className={styles.h2}>제10조 (회원 탈퇴 및 이용제한)</h2>
      <p className={styles.body}>
        이용자는 마이페이지에서 언제든지 회원 탈퇴를 할 수 있습니다. 회사는 이용자가 본 약관을
        위반한 경우 서비스 이용을 제한하거나 계약을 해지할 수 있습니다.
      </p>

      <h2 className={styles.h2}>제11조 (준거법 및 관할)</h2>
      <p className={styles.body}>
        본 약관은 대한민국 법에 따라 규율되며, 서비스와 관련하여 발생한 분쟁에 대해서는 「민사소송법」이
        정한 관할 법원에 소를 제기합니다.
      </p>

      <h2 className={styles.h2}>제12조 (문의)</h2>
      <p className={styles.body}>서비스 이용 관련 문의: corpseonthemission@icloud.com</p>
    </div>
  );
}
