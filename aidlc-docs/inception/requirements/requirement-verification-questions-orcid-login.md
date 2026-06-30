# 소셜 로그인 — ORCID 프로바이더 추가 (U3 Accounts) — 요구사항 명확화 질문

**단계**: INCEPTION → Requirements Analysis 재진입 (기존 **FR-27 소셜 로그인** 확장) · **일자**: 2026-06-30
**대상 기능**: 현재 **Google** 단일 프로바이더로 정의된 **FR-27 소셜 로그인(OIDC)** 에 **ORCID**(연구자 영속 식별자) 프로바이더를 추가. arXiv AI/ML 연구자 사용자층에 직결.
**FR/BR 번호**: 신규 FR 없음 — **FR-27 개정**(프로바이더 목록 + 이메일-없는 프로바이더 카브아웃). **다음 BR 번호**: **BR-A13**(기존 BR-A1~A12).
**유닛 경계**: 1차 소속 **U3**(인증·계정 보안). **U10 마이페이지**와 책임이 맞닿음 — ORCID iD 프로필 노출은 U10 UI(이미 mock 존재)이며, 본 작업이 mock→real 백엔드(`GET /mypage/orcid-profile`)를 채운다.
**근거 SSOT**: `requirements.md` **FR-27**·**SEC-5/9/11/12**·**NFR-R1**; U3 Functional Design `business-rules.md` **BR-A9**(소셜 연결=검증 이메일 한정)·`domain-entities.md` **§4.2 SocialIdentity**/**§4.6 OidcProvider**; `tech-stack-decisions.md` **TD-U3-8**(httpx + python-jose JWKS); `requirement-verification-questions-u10-mypage.md` **Q6/Q8/Q9**(ORCID 노출·컬럼·언링크 결정 선기록).

**현황(코드·외부 사양 검증, 2026-06-30)**:
- **기 스캐폴딩 존재(팀 선반영)**: DB 마이그레이션 `006_add_orcid_columns_to_social_identities.sql`(`orcid_name/affiliation/synced_at`)·`_login_provider()` 우선순위 `ORCID > GOOGLE > EMAIL`·프런트 `LoginProvider` 타입·`OrcidProfileVM`·마이페이지 ORCID 카드 + mock fixture. **실 ORCID OAuth 백엔드 코드·`/mypage/orcid-profile` 엔드포인트는 부재**(프런트 MockTransport만).
- **⚑ 결정적 외부 사양**: ORCID OIDC discovery(`https://orcid.org/.well-known/openid-configuration`) 확인 결과 **`scopes_supported = ["openid"]`**, **`claims_supported = [family_name, given_name, name, auth_time, iss, sub]`** — **`email`/`email_verified` 클레임 미지원**. 서명 = **RS256**, `jwks_uri = https://orcid.org/oauth/jwks`, **tokeninfo 엔드포인트 없음**(Google과 다름). ⇒ ORCID 로그인은 **이메일을 전혀 제공하지 않으며**, id_token 검증은 **로컬 JWKS/RS256**(TD-U3-8의 python-jose 경로)으로만 가능.

**답변 상태**: ✅ 1차 답변 완료 (2026-06-30, 팀) — **Q1=A**(ORCID iD 계정·이메일 nullable) · **Q2=A**(로그인 + 마이페이지 ORCID iD 실표시). 미서피스 항목은 권장안(**Q3=A** prod+env 토글 · **Q4=A** JWKS/RS256 · **Q5=A** Public API 어피리에이션 lazy 캐시).

> ⚠️ **범위 게이트.** 본 확장은 FR-27에 ORCID 프로바이더를 편입하는 **승인 게이트**다(기존 프로바이더 확장과 동일 절차).
>
> 🎚️ **고도(Altitude) 주의 — 본 질문지는 INCEPTION만 다룬다.** 여기서 정하는 것은 **WHAT/WHY·범위·경계·NFR 프레이밍**이다. **HOW**(JWKS 캐시 전략·Public API 호출 위치·이메일 nullable 마이그레이션·UI)는 **CONSTRUCTION(Functional/NFR/Infra Design) 라운드**에서 확정한다 — **↪ HOW=Construction**.
>
> 각 질문의 **[Answer]:** 태그에 답을 적어주세요. **(권장)** 은 코드 리뷰·보안 관점의 제안일 뿐 확정이 아닙니다.

---

## 섹션 A — 신원 모델 (핵심 결정)

## Q1. ORCID가 이메일을 주지 않을 때 계정 신원 모델

_왜 중요한가:_ DocSuri 계정은 **이메일 키**(로그인 식별자·정규화 유일성·알림 수신처)다. **BR-A9** 소셜 연결은 프로바이더 **검증 이메일**에만 성립한다. 그러나 ORCID OIDC는 **이메일을 전혀 반환하지 않으므로**(위 현황), Google 패턴(검증 이메일 자동 연결/생성)이 **구조적으로 불가**하다. 신원 모델을 가르는 1순위 결정.

- **A) ORCID iD 계정 (이메일 nullable)** (권장·채택) — `(provider=ORCID, providerSubject=ORCID iD)`로 계정을 키잉하고 **`accounts.email`을 nullable**로 완화. 연구자는 이메일 없이 ORCID로 로그인. ORCID가 **이메일을 반환하면** 기존 BR-A9 경로(검증 시 자동 연결)를 그대로 적용. _↪ 이메일 nullable 마이그레이션 + 이메일-가정 코드 경로 가드 = HOW=Construction._
- **B) ORCID 후 이메일 필수** — ORCID 인증 후 "이메일 입력+검증" 1스텝을 강제해 이메일-키 불변식 유지. ORCID 사용자에게 온보딩 마찰 추가.
- **C) Google과 동일(검증 이메일 한정)** — 이메일 미반환 시 명시적 에러로 실패. ORCID는 이메일을 **결코** 주지 않으므로 사실상 항상 실패 → 기각.

[Answer]: **A** (2026-06-30) — ORCID iD 계정, `accounts.email` nullable.

## Q2. 이번 사이클 범위 — 로그인 전용 vs 프로필 노출 포함

_왜 중요한가:_ 마이페이지(U10)에 ORCID iD를 **mock**으로 노출 중이다(`requirement-verification-questions-u10-mypage.md` Q6: "ORCID로 로그인했을 때만 노출"). 본 작업이 로그인만 채울지, mock→real 프로필까지 채울지가 blast-radius를 가른다.

- **A) 로그인 + 프로필 실표시** (권장·채택) — ORCID OIDC 로그인 + U10 mock(`getOrcidProfile`/`mockGetOrcidProfile`)을 실 백엔드 `GET /mypage/orcid-profile`(id_token 이름 + ORCID Public API 어피리에이션)로 대체. `orcid_*` 컬럼(마이그레이션 006)에 캐시.
- **B) 로그인 전용** — ORCID iD는 `SocialIdentity`에 저장하되 U10 표시 와이어링은 후속.

[Answer]: **A** (2026-06-30) — 로그인 + 마이페이지 ORCID iD 실표시.

---

## 섹션 B — 보안 / 운영 프레이밍 (미서피스 — 권장안 기록)

## Q3. ORCID 환경 (prod vs sandbox)

- **A) Production(`https://orcid.org`) 기본 + env 토글로 sandbox(`https://sandbox.orcid.org`)** (권장) — Google `*_OIDC_*` env 패턴과 동형. _↪ env/시크릿 = HOW=Construction(Infra)._

[Answer]: **A** (권장 채택)

## Q4. id_token 검증 방식

_왜 중요한가:_ ORCID는 **tokeninfo 엔드포인트가 없다**. Google 검증기는 Google tokeninfo에 위임하지만 ORCID는 불가.

- **A) 로컬 JWKS/RS256 검증(python-jose) + `iss`/`aud`/`nonce`/`exp` 강제** (권장) — TD-U3-8이 이미 선정한 라이브러리. `oidc.py` docstring의 이연(deferred) JWKS 모드를 ORCID에 대해 실현. _↪ JWKS 캐시 TTL = HOW=Construction._

[Answer]: **A** (권장 채택)

## Q5. ORCID 어피리에이션(소속) 취득

_왜 중요한가:_ 마이페이지 ORCID 카드의 `orcid_affiliation`은 OIDC id_token에 없다(claims에 미포함). ORCID **Public API**(`https://pub.orcid.org/v3.0/{id}/record`) 호출이 필요.

- **A) 콜백 시 Public API 1회 호출 → `orcid_*` 컬럼에 캐시, lazy 갱신** (권장) — 추가 outbound 443 1회/로그인(저비용). 실패 시 이름만 표시(어피리에이션 None) 저하. _↪ 갱신 주기·실패 저하 = HOW=Construction._

[Answer]: **A** (권장 채택)

## Q6. 확장(Security/Resiliency Full · PBT Partial) 적용

- **A) 신규 ORCID 콜백/시작 표면에 기존 확장 구성 동일 적용**(state/nonce CSRF·콜백 레이트 리밋·프로바이더 장애 명시 에러) (권장).

[Answer]: **A** (권장 채택)

---

## §확정 답변 분석 (1차, 2026-06-30)

**확정 범위(이번 사이클)** — ORCID를 FR-27 프로바이더로 편입(Google 병행). 신원 = ORCID iD 키·이메일 nullable(Q1-A). 마이페이지 ORCID 프로필 mock→real(Q2-A). 검증 = 로컬 JWKS/RS256(Q4-A).

| 개정 | 대상 | 핵심(WHAT/WHY·NFR 프레이밍) | 출처 답변 |
|---|---|---|---|
| **FR-27 개정** | 소셜 로그인(OIDC) | 프로바이더에 **ORCID** 추가. **ORCID OIDC는 이메일 미반환** → 검증 이메일 자동 연결(BR-A9)이 불가한 프로바이더는 **`(provider, subject)` 신원으로 ACTIVE 신규 계정 생성**(이메일 nullable, 역할 USER 고정). 이메일을 반환하는 프로바이더(Google)는 BR-A9 기존 동작 유지. state/nonce CSRF 방어·동일 세션 쿠키·프로바이더 장애 명시 에러 동일. | Q1-A·Q2-A |

**신규 비즈니스 규칙(U3 FD `business-rules.md` 편입 예정)**: **BR-A13**(이메일-없는 OIDC 프로바이더 신원 규칙 — 프로바이더가 검증 이메일을 제공하지 않으면 `(provider, providerSubject)` 단독으로 신원을 성립시키고 `accounts.email`은 NULL 허용; 자동 연결/병합 없음; 역할 항상 USER; id_token은 JWKS/RS256으로 검증). **BR-A9 보강**: "검증 이메일 한정 자동 연결" 규칙은 **이메일을 제공하는 프로바이더에 한해** 적용됨을 명시(ORCID는 BR-A13 경로).

**NFR/보안(Q6=A 동일 적용)**: ORCID `/social/orcid/start`·`/callback`에 Security Baseline Full; 콜백 레이트 리밋(SEC-11); `state`(CSRF)/`nonce`(replay) + id_token `iss`/`aud`/`exp` 검증; 클라이언트 시크릿 = Secrets Manager(Google 패턴), client_id/redirect = ECS env; **NFR-C1 비용 무변**(ORCID Public API 무료·로그인당 호출 1회). 모순 점검: Q1-A(이메일 nullable)는 BR-A5(이메일 링크 PENDING/ACTIVE)와 **이메일을 가진 계정에 한해** 적용되도록 BR-A13가 경계를 그어 충돌 없음. ORCID 계정은 비밀번호 자격증명 부재(`SOCIAL_NO_PASSWORD_HASH`)로 비밀번호 로그인·재설정 경로 비해당 — BR-A1/A8 비충돌.

**경계(U3/U10)**: U3 = `/auth/social/orcid/*` + 신원 도메인 규칙 소유. U10 = 마이페이지 ORCID 카드 UI 소유, 본 작업이 채우는 `GET /mypage/orcid-profile`(U3 소셜 신원 + ORCID Public API) 호출.

**다음 단계(AIDLC)**: ① 본 게이트 승인 → `requirements.md` FR-27 개정 → ② CONSTRUCTION U3 Functional Design(`domain-entities` enum+ORCID·SocialIdentity 이메일 nullable·`business-rules` BR-A13)·NFR(TD-U3-8 ORCID JWKS 주석)·Infra(env/시크릿) **HOW 라운드** → ③ Code Generation(ORCID 검증기·라우트·reconcile 이메일-옵셔널·ORM·`/mypage/orcid-profile`·프런트 버튼·이메일 nullable 마이그레이션) → ④ Build&Test + U3 Unit Review.
