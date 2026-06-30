# tech-stack-decisions.md — U3 Accounts 기술 스택 결정서 (ADR)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U3 Accounts · **일자**: 2026-06-16
**근거(SSOT)**: `construction/plans/u3-accounts-nfr-requirements-plan.md` (Q1~Q6 답변 반영), `tech-stack-decisions.md` [U1 Ingestion] 상속 규칙

---

## TD-U3-1 [상속] — 언어 및 런타임: **Python 3.12+**
- **결정**: 모듈형 모놀리스 API 배포 단위(①)의 전체 결정에 따라 Python을 백엔드 언어로 상속하여 사용합니다.
- **근거**: U1/U2/U6와의 아키텍처적 일관성 유지 및 모듈 간 의존성 결선 unblocked.

---

## TD-U3-2 — 비밀번호 해싱 라이브러리: **`argon2-cffi`**
- **결정**: 사용자의 자격증명 해싱 및 상수시간 연산 검증을 위해 Python 라이브러리 `argon2-cffi`를 사용합니다 (Q2 답변 반영).
- **근거**:
  - Argon2 공식 C 구현체를 가장 고성능 및 저지연으로 바인딩하여 백엔드 CPU/메모리 연산 오버헤드를 극소화합니다.
  - 최신 OWASP 암호학 표준인 Argon2id KDF 포맷을 제공하며, GPU 병렬 무차별 대입 공격에 강한 저항성을 제공합니다 (SEC-12).
- **대안**: `passlib` (두꺼운 추상화 계층으로 인해 해싱 연산 오버헤드가 발생하고 종속성이 무거움).

---

## TD-U3-3 — 영속성 스토리지 스택: **Amazon RDS(PostgreSQL) + Amazon ElastiCache(Redis)**
- **결정**: 사용자 자격증명 영속화는 **Amazon RDS (PostgreSQL)**로 처리하고, 활성 세션 보관은 **Amazon ElastiCache (Redis)** 복합 구성을 적용합니다 (Q4 답변 반영).
- **근거**:
  - **자격증명 (RDS PostgreSQL)**: 이메일 고유성(Unique Index) 강제 및 사용자 계정 데이터의 엄격한 ACID 트랜잭션, 관계형 도메인 정규화 구조를 완벽하게 보장합니다 (SEC-8).
  - **세션 (ElastiCache Redis)**: 세션 검증 레이턴시 예산(P50 < 5ms, NFR-P1)을 충족하기 위한 초고속 인메모리 조회 및 자동 만료(TTL) 필드를 기본 지원하며, Multi-AZ 복제 클러스터를 통해 유실 방지 가용성을 제공합니다 (Q3=A).
- **대안**: Amazon DynamoDB (데이터 모델은 단순해지나 세션 검증 성능 예산 만족 및 Sliding Expiration 갱신 시의 DB 비용 오버헤드가 발생함).

---

## TD-U3-4 — 봇 차단 CAPTCHA 서비스: **Google reCAPTCHA v3**
- **결정**: 비정상 로그인 및 봇 남용 방어를 위해 **Google reCAPTCHA v3**를 연동합니다 (Q5 답변 반영).
- **근거**:
  - 사용자에게 수동으로 글자를 맞추거나 그림을 고르도록 강제하여 UX를 깨뜨리는 대신, 행동 기반의 점수(Score, 0.0 ~ 1.0)를 백엔드로 전달받아 유연한 비즈니스 로직 제어가 가능합니다.
  - 로그인 10회 연속 실패 시에만 도메인 레이어에서 CAPTCHA 인증 검증을 요구하는 Functional Design 규칙(BR-A4)을 유연하게 구현할 수 있습니다 (SEC-11).
- **대안**: AWS WAF CAPTCHA (네트워크/인프라 계층에서 강제 차단하므로 비즈니스 논리 기반의 점진적 지연 백오프 제어가 불가능함).

---

## TD-U3-5 — 이메일 발송 인프라: **Amazon SES (Simple Email Service)**
- **결정**: PENDING 계정의 이메일 본인 인증 토큰 링크 발송을 위해 **Amazon SES**를 연동합니다 (Q6 답변 반영).
- **근거**:
  - AWS 환경에 네이티브하게 통합되며 높은 도메인 신뢰도와 발송 속도를 제공합니다.
  - **로컬 스위칭 설계**: 로컬 개발 및 테스트 환경에서는 실제 메일이 발송되지 않도록 환경 변수에 따라 `MockEmailHandler`가 콘솔 터미널에 인증 링크 및 토큰 값을 출력하도록 추상화 인터페이스를 설계합니다.
- **대안**: 자체 SMTP 서버 구축 (운영 부담 및 스팸 메일 분류 위험 높음).

---

## TD-U3-6 [상속] — PBT 및 테스트 도구: **Hypothesis**
- **결정**: 자격증명 강도 검증 및 해싱 멱등성 검사(PBT-U3-1/2)를 위해 Python의 `Hypothesis` PBT 프레임워크를 상속하여 테스트를 작성합니다.
- **근거**: U1/U2와의 일관성 유지 및 강력한 속성 기반 수축(Shrinking) 테스트 지원.

---

## TD-U3-7 — 이메일 발송 인프라 정정: **Resend** (TD-U3-5 SES 대체 · 2026-06-24)
- **결정**: SES 프로덕션 액세스 지연으로 **Resend**를 라이브 발송 채널로 확정(`EMAIL_PROVIDER=resend`). 가입 인증·**비밀번호 재설정(FR-26)**·**이메일 변경(FR-28)** 메일 모두 Resend 경유. TD-U3-5의 `MockEmailHandler` 로컬 스위칭 추상화는 유지.
- **근거**: SES 샌드박스/프로덕션 승인 병목 우회, 발신 도메인 신뢰도 확보.

## TD-U3-8 — 소셜 로그인(OIDC) 라이브러리: **httpx + python-jose(JWKS)** (Authlib 미채택) — FR-27
- **결정**: Google OIDC Authorization Code 흐름을 `httpx`(기존 reCAPTCHA 아웃바운드 패턴 재사용) + `python-jose`(또는 PyJWT, **JWKS로 `id_token` 서명 검증**)로 구현. **Authlib 등 중량 프레임워크 미채택**(제로-신규-중량-의존 원칙).
- **근거**: 기존 스택 일관성·의존 표면 최소화. `id_token`(서명·`nonce`·`aud`·`iss`) 검증에만 JWT/JWKS 필요.
- **시크릿**: Google `client_id`/`client_secret` = ECS env 주입(기존 시크릿 패턴, 비로깅·SEC-3).
- **ORCID 분기 *(2026-06-30, FR-27 ORCID)***: ORCID는 **tokeninfo 엔드포인트가 없어** Google 검증기(`_fetch_tokeninfo`)를 재사용할 수 없음 → **로컬 JWKS/RS256 검증이 필수**(`jwks_uri=https://orcid.org/oauth/jwks`, `iss=https://orcid.org`). 본 TD가 이미 선정한 `python-jose` 경로로 구현(`oidc.py` docstring의 이연 JWKS 모드를 ORCID에 대해 실현). ORCID OIDC는 `scope=openid`만 지원(이메일·프로필 클레임 없음) → **이름/소속은 ORCID Public API**(`https://pub.orcid.org/v3.0/{id}/record`, 무료·인증 불요)로 별도 취득해 `social_identity.orcid_*`에 캐시(BR-A13·마이페이지). 시크릿 = `ORCID_OIDC_CLIENT_ID`(plain env)·`ORCID_OIDC_CLIENT_SECRET`(Secrets Manager)·`ORCID_OIDC_REDIRECT_URI`(env)·`ORCID_OIDC_ENV`(prod|sandbox 토글).

## TD-U3-9 — 신규 영속 스키마 + state/nonce 스토어 — FR-26~28
- **결정**: RDS PostgreSQL에 `password_reset_token`(token_hash·expires_at·used_at)·`email_change_request`·`social_identity`(provider·provider_subject·account_id, **unique**) 테이블 추가 + `account.status`에 `DEACTIVATED` + `account_deletion`(purge_after) 추가. **DB 마이그레이션**은 기존 SQL 러너 패턴. OIDC `state`/`nonce`는 **ElastiCache Redis 단명 키**(콜백 1회용·짧은 TTL).
- **근거**: 재설정/소셜 신원은 영속·해시 저장, `state`/`nonce`는 단명 → 스토어 분리(영속 vs 캐시).

## TD-U3-10 — 계정 삭제 캐스케이드: **EventBridge `AccountDeleted` + 유예 파기 잡** — FR-28
- **결정**: 삭제 시 U3가 `AccountDeleted` 이벤트를 기존 이벤트 백본(**EventBridge**)으로 발행 → U4/U2 구독자가 각자 owner-scoped 파기(직접 호출 아님 — **DAG 비순환**). 유예 파기는 **스케줄드 잡**(기존 마이그레이션/배치 러너 패턴), 멱등·재시도·**DLQ**.
- **근거**: 의존성 역전으로 순환 회피; 기존 EventBridge/SQS 패턴 재사용(신규 인프라 최소).
