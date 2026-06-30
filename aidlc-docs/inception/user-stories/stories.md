# DocSuri — 사용자 스토리

**단계**: INCEPTION → 사용자 스토리 · **일자**: 2026-06-15 · **깊이**: Comprehensive
**접근**: 에픽 기반, 여정 순서(PQ1) · INVEST · Given/When/Then 인수 기준(PQ3) · 얇은 슬라이스 + 단일 히어로 스토리(PQ4) · NFR 하이브리드 표현(PQ5).
**페르소나**: P1(박지훈), P2, OP — `personas.md` 참조.

> 추적(traces)은 `requirements.md`의 ID(FR/NFR/SEC/RES/QT/C)를 참조한다. (C = §9 제약)

---

## 에픽 0 — 히어로(종단 데모)

### US-H1 — 첫 검색 매직 모먼트 *(HERO)*
**As** 신규 연구자(P1/P2), **I want** 폰에서 자연어 질의로 가입하자마자 관련 arXiv 논문을 받기를, **so that** 수초 내에 문헌 디스커버리를 시작할 수 있다.
- **Given** 폰의 첫 방문자, **When** 셀프 가입 후 자연어 AI/ML 의도를 입력하면, **Then** 실재 arXiv 논문의 정렬 목록이 **< 3s(P50)** 내 표시된다.
- **Given** 결과 목록, **When** 결과 카드를 읽으면, **Then** 모든 논문이 실재하고 링크 가능한 arXiv 레코드다(날조 없음).
- **Given** 코퍼스에 관련 논문이 없는 질의, **When** 실행하면, **Then** "관련 논문 없음"을 명확히 표시하고 아무것도 날조하지 않는다.
- **Traces**: FR-7, FR-1, FR-2, FR-3, FR-4, FR-5, NFR-P1, NFR-U1, QT-1
- _비고: US-H1은 US-A1 + US-D1..D6으로 실현되는 통합(데모 인수) 슬라이스 — 독립 작업 단위가 아닌 조합으로 추정._

---

## 에픽 1 — 디스커버리(히어로 여정)

> **페이즈 2 개정(2026-06-29)**: 재인셉션 페이즈 2(U2 검색) 반영 — 멀티소스(arXiv·Semantic Scholar·OpenAlex)·DocModel(Block) 인덱스 소비, 검색 lite/full scope(#236), 소스 중립 카드·근거 링크(Q2), Grounding(Search) U6 단일권위 유지·Block 앵커 외부노출 페이즈 3·4 이월(Q3·Q4). 상세 = `../requirements/requirement-verification-questions-u2-discovery.md`.

### US-D1 — 자연어 질의 입력
**As** 연구자(P1/P2), **I want** 자유 텍스트 연구 의도를 입력하기를, **so that** 불리언 키워드 질의를 짤 필요가 없다.
- **Given** 검색 화면, **When** 자연어 500자 이내를 입력하면, **Then** 질의가 허용·검증된다.
- **Given** 길이 초과 또는 빈 질의, **When** 제출하면, **Then** 인라인 검증 메시지가 뜨고 요청은 전송되지 않는다.
- **Traces**: FR-1, SEC-5, NFR-U1

### US-D2 — 공유 AI/ML Corpus 인덱스에 대한 시맨틱 검색 *(2026-06-29 개정 — 페이즈 2: 멀티소스·scope)*
**As** 연구자(P1), **I want** 시스템이 의미로 논문을 검색하기를, **so that** 정확한 키워드 없이도 관련 연구를 찾는다.
- **Given** 유효한 질의, **When** 검색하면, **Then** 공유 AI/ML **멀티소스(arXiv·Semantic Scholar·OpenAlex) DocModel(Block) 기반** 벡터 인덱스에서 후보를 검색한다(시맨틱, 선택적으로 lexical 하이브리드).
- **Given** 도메인 특화 표현, **When** 검색되면, **Then** 정확 용어 매치뿐 아니라 의미적으로 관련된 논문도 포함된다.
- **Given** 사람 검색창(기본), **When** 검색하면, **Then** `lite` scope(제목+초록 BM25 + 초록 chunk k-NN)로 저지연(NFR-P1) 처리되고, 에이전트 심층 검색은 `full` scope(본문 chunk·고recall·비-SLA)로 분기된다.
- **Traces**: FR-2, NFR-P1

### US-D3 — 관련도순 상위 N건
**As** 연구자(P1), **I want** 관련도순 정렬 결과를, **so that** 가장 좋은 논문이 상단에 온다.
- **Given** 검색된 후보, **When** 결과가 표시되면, **Then** 상위 N건(≈20)이 문서화된 관련도 점수순으로 표시된다.
- **Given** QT-2 관련도 평가셋, **When** 검색하면, **Then** 기대 관련 논문이 상위 N건에 등장한다(문서화된 임계치; 제안: Recall@10 ≥ 0.7).
- **Given** 후보가 N건 미만, **When** 결과를 표시하면, **Then** 가용한 건수만 표시하고 별도 오류/패딩 없이 정상 처리한다.
- **Traces**: FR-3, QT-2

### US-D4 — 폰 최적화 결과 카드
**As** 폰을 쓰는 연구자(P1), **I want** 간결·가독성 높은 결과 카드를, **so that** 한 손으로 결과를 훑을 수 있다.
- **Given** 360–430px 뷰포트의 결과 목록, **When** 카드를 보면, **Then** 제목·저자·연도·식별자·초록 스니펫·관련도 신호·**소스 표기(sourceName)·소스 중립 링크**(arXiv=arXiv 링크, 비-arXiv=sourceUrl/DOI)가 가로 스크롤 없이 표시된다. *(2026-06-29 개정 — 페이즈 2/Q2)*
- **Given** 데스크톱 브라우저, **When** 앱을 열면, **Then** 폰 목업 프레임 안 중앙에 렌더링된다(데스크톱 리플로우 아님).
- **Traces**: FR-4, NFR-U1, NFR-U2, SEC-4

### US-D5 — 엄격히 근거화된 결과
**As** 연구자(P1), **I want** 노출되는 모든 논문과 AI 생성 설명이 실재하고 출처에서 도출되기를, **so that** 내가 인용할 것을 신뢰할 수 있다.
- **Given** 임의의 결과, **When** 표시되면, **Then** 해소 가능한 ID/링크를 가진 **실재 인덱스 레코드(소스 중립 — arXiv/비-arXiv)** 에 매핑된다. *(2026-06-29 개정 — 페이즈 2/Q2)*
- **Given** AI 생성 관련도 설명/요약, **When** 표시되면, **Then** 그 내용은 검색된 논문에서만 도출된다(저자/게재처/사실 날조 없음).
- **Given** 근거화 판정, **When** 결과가 확정되면, **Then** enforce는 **U6 단일권위**로 수행되고(U2는 seam 어댑팅), DocModel Block 앵커는 근거 매칭에 내부 활용하되 외부 노출하지 않는다(페이즈 3·4 이월; Q3·Q4).
- **Traces**: FR-5, QT-1, D3

### US-D6 — 날조 대신 기권
**As** 연구자(P1), **I want** 관련 결과가 없을 때 앱이 그것을 인정하기를, **so that** 논문을 절대 지어내지 않는다.
- **Given** 코퍼스 밖 또는 무매치 질의, **When** 검색하면, **Then** "관련 논문 없음" 상태를 명시하고 날조 결과는 0건.
- **Traces**: FR-5, FR-11, QT-1

### US-D7 — 빈/실패/저하 UX
**As** 연구자(P1), **I want** 문제 발생 시 명확한 상태를, **so that** 조용한 오답을 절대 보지 않는다.
- **Given** 업스트림 장애(arXiv/LLM/인덱스), **When** 검색하면, **Then** 구체적·비기술적 메시지와 (가능하면) 저하된 결과를 보고, 빈 화면·스택 트레이스는 없다.
- **Given** 저하 모드(예: LLM 리랭킹 비활성화), **When** 결과가 표시되면, **Then** 저하 상태가 표시된다.
- **Given** 처리 중 오류, **When** 응답이 반환되면, **Then** fail closed로 일반화된 비기술적 에러를 표시하고 스택 트레이스/내부 정보를 노출하지 않는다(전역 에러 핸들러).
- **Traces**: FR-11, NFR-R1, NFR-R2, SEC-9, SEC-15, QT-3

---

## 에픽 2 — 계정

### US-A1 — 공개 셀프 가입
**As** 신규 사용자(P1/P2), **I want** 스스로 가입하기를, **so that** 내 작업을 저장할 수 있다.
- **Given** 가입 화면, **When** 유효한 이메일 + 정책 준수 비밀번호로 등록하면, **Then** 계정이 생성된다(비밀번호 적응형 해싱, 로깅 금지).
- **Given** 한 출처에서의 반복 가입 시도, **When** 한도를 초과하면, **Then** 레이트 리미팅된다.
- **Traces**: FR-7, SEC-12, SEC-11, SEC-3

### US-A2 — 로그인, 로그아웃, 세션
**As** 재방문 사용자(P1/P2), **I want** 안전하게 로그인·로그아웃하기를, **so that** 저장 데이터가 비공개로 유지된다.
- **Given** 유효 자격증명, **When** 로그인하면, **Then** 안전한 세션이 수립된다(secure/httpOnly/sameSite 쿠키; 서버측 토큰 검증).
- **Given** 반복 로그인 실패, **When** 임계치에 도달하면, **Then** 무차별 대입 방어(락아웃/지연/CAPTCHA)가 작동한다.
- **Given** 로그아웃, **When** 세션이 종료되면, **Then** 서버측에서 무효화된다.
- **Traces**: FR-7, SEC-12, SEC-8

### US-A3 — 비밀번호 재설정(분실 복구) *(2026-06-24 편입)*
**As** 로그인 불가 사용자(P1/P2), **I want** 이메일로 비밀번호를 재설정하기를, **so that** 계정 접근을 스스로 복구한다.
- **Given** 재설정 요청 화면에 이메일 입력, **When** 제출하면, **Then** 가입/상태와 무관하게 **동일한 일반 응답**을 받고(열거 방지), 해당되면 **단일사용·30분 만료** 토큰 링크가 Resend로 발송된다.
- **Given** 유효한 재설정 토큰, **When** 정책 준수 새 비밀번호를 설정하면, **Then** 비밀번호가 갱신되고 해당 계정의 **전 세션이 무효화**되며 토큰은 재사용 불가가 된다.
- **Given** 만료·사용된 토큰, **When** 접근하면, **Then** 거부되고 재요청을 안내한다.
- **Traces**: FR-26, SEC-9, SEC-11, SEC-12

### US-A4 — 소셜 로그인(Google OIDC) *(2026-06-24 편입)*
**As** 신규/재방문 사용자(P1/P2), **I want** Google 계정으로 가입·로그인하기를, **so that** 별도 비밀번호 없이 빠르게 시작한다.
- **Given** "Google로 계속" 선택, **When** OIDC 인가 코드 흐름을 완료하면, **Then** **state/nonce 검증** 후 프로바이더 **검증 이메일**로 기존 계정에 연결되거나 **ACTIVE 신규 계정**이 생성되고, 기존 로그인과 동일한 secure/httpOnly/sameSite 세션이 발급된다(권한=USER).
- **Given** 프로바이더가 이메일 **미검증**을 반환, **When** 자동 연결을 시도하면, **Then** 자동 연결을 **거부**한다(계정 탈취 방어).
- **Given** 프로바이더 콜백 실패·거부, **When** 돌아오면, **Then** 명시적 에러로 표면화하고 로그인 화면으로 복귀한다.
- **Traces**: FR-27, SEC-5, SEC-12

### US-A5 — 비밀번호·이메일 변경(자가 관리) *(2026-06-24 편입)*
**As** 로그인 사용자(P1/P2), **I want** 비밀번호와 이메일을 변경하기를, **so that** 계정 자격증명을 최신·안전하게 유지한다.
- **Given** 비밀번호 변경, **When** **현재 비밀번호 재인증** 후 정책 준수 새 비번을 제출하면, **Then** 갱신되고 전 세션이 무효화되며 자격증명은 로깅되지 않는다.
- **Given** 이메일 변경, **When** 새 주소를 제출하면, **Then** 새 주소로 검증 링크가 발송되고 **검증 완료 전까지 로그인 식별자에 반영되지 않으며** 이미 사용 중 이메일은 거부된다.
- **Traces**: FR-28, SEC-8, SEC-12

### US-A6 — 계정 삭제(탈퇴) *(2026-06-24 편입)*
**As** 로그인 사용자(P1/P2), **I want** 계정을 삭제하기를, **so that** 내 데이터를 서비스에서 제거한다.
- **Given** 삭제 확인, **When** 탈퇴를 실행하면, **Then** 계정이 즉시 비활성화되고 **전 세션이 무효화**된다(소프트 삭제).
- **Given** 유예 기간(N일) 경과, **When** 파기 잡이 실행되면, **Then** **owner-scoped 데이터**(라이브러리·저장검색·이력)가 캐스케이드 파기되고 작업이 감사 로그에 남는다(멱등·재시도·DLQ).
- **Traces**: FR-28, SEC-8, SEC-14

### US-A7 — 인증 실패의 명확한 표면화 & 입력 견고화 *(2026-06-24 편입)*
**As** 사용자(P1/P2), **I want** 로그인·가입 실패 이유가 명확히 보이기를, **so that** 무엇이 잘못됐는지 알고 복구한다.
- **Given** 프런트/백 버전 스큐로 **추가 바디 필드**가 섞인 인증 요청, **When** 전송되면, **Then** 추가 필드는 무시되고 필수 필드만 검증되어 로그인이 **전면 차단되지 않는다**.
- **Given** 4xx/422 등 인증 실패, **When** 응답을 받으면, **Then** 빈 화면·원시 JSON·모호한 generic 대신 **구체·비기술적 메시지**가 표시되고 필요 시 인증 메일 재발송 경로가 제공된다.
- **Traces**: FR-29, SEC-15, NFR-R1

---

## 에픽 3 — 검색 저장 & 라이브러리

### US-L1 — 검색 저장 & 재실행
**As** 연구자(P1), **I want** 질의를 저장·재실행하기를, **so that** 주제를 시간에 따라 추적할 수 있다.
- **Given** 검색, **When** 저장하면, **Then** 내 비공개 목록에 지속되고 이후 재실행 가능하다.
- **Given** 다른 사용자, **When** 시스템에 접근하면, **Then** 내 저장 검색을 절대 볼 수 없다.
- **Traces**: FR-8, SEC-8

### US-L2 — 라이브러리 저장
**As** 연구자(P1), **I want** 논문을 개인 라이브러리에 추가하기를, **so that** 읽기 목록을 구축할 수 있다.
- **Given** 결과, **When** 저장하면, **Then** 내 비공개 라이브러리에 나타나고 삭제 가능하다.
- **Traces**: FR-9, SEC-8

### US-L3 — 검색 이력
**As** 연구자(P1), **I want** 최근 질의가 목록화되기를, **so that** 빠르게 반복할 수 있다.
- **Given** 과거 검색, **When** 이력을 열면, **Then** 최근 질의가 목록·재실행 가능하며 나에게 비공개다.
- **Traces**: FR-10, SEC-8

---

## 에픽 4 — 인제스천

### US-I1 — 멀티소스 Corpus & DocModel 인덱싱 파이프라인 *(2026-06-26 U1 Corpus 개정)*
**As** 운영자(OP), **I want** AI/ML 논문 Corpus가 멀티소스로 수집되어 DocModel 기반 인덱스로 구축되기를, **so that** 연구자가 더 넓고 근거 가능한 논문을 발견할 수 있다.
- **Given** arXiv·Semantic Scholar·OpenAlex의 OA/인덱싱 허용 AI/ML 논문, **When** 파이프라인이 실행되면, **Then** arXiv는 HTML 우선/PDF 폴백, Semantic Scholar·OpenAlex는 PDF→GROBID로 FullText를 추출한다.
- **Given** 같은 논문이 여러 소스에 존재, **When** 병합하면, **Then** DOI→arXiv id→정규화(title+1저자+연도) 순으로 dedup하고 소스 우선순위 승자를 보존한다.
- **Given** 추출된 FullText, **When** 수집이 완료되면, **Then** `(paperId, version)`별 DocModel 완성형을 eager 생성하고 DocModel Block 경계로 청크·임베딩해 OpenSearch/S3에 저장한다.
- **Given** 라이선스 미허용 또는 원시 PDF, **When** 처리하면, **Then** 검색/DocModel 저장 대상에서 제외하거나 transient 추출 입력으로만 사용하고 원시 PDF는 저장하지 않는다.
- **Traces**: FR-6, FR-18, C-1, QT-9

### US-I2 — 최신성 스케줄 갱신
**As** 연구자(P1), **I want** 새로 게재된 논문이 source별 증분 갱신으로 나타나기를, **so that** 빠르게 변하는 분야를 따라갈 수 있다.
- **Given** source별 watermark가 저장되어 있고, **When** 스케줄 갱신이 실행되면, **Then** 마지막 성공 지점 이후의 신규/변경 논문만 수집·재빌드·재색인된다.
- **Given** 논문 버전이 바뀌면, **When** 재처리되면, **Then** DocModel·청크·인덱스·S3 참조가 같은 `(paperId, version)`으로 정합된다.
- **Given** 갱신 실패, **When** 발생하면, **Then** source별 watermark 지연·단계 실패·DLQ 적체가 로깅·경보된다(OP).
- **Traces**: FR-6, FR-18, RES-7, QT-9

### US-I3 — 복원력 있는 인제스천
**As** 운영자(OP), **I want** 인제스천이 소스/GROBID/임베딩 일시 장애를 견디기를, **so that** 일시적 장애가 인덱스를 손상·정체시키지 않는다.
- **Given** arXiv·Semantic Scholar·OpenAlex·GROBID·임베딩 중 하나가 타임아웃/에러를 반환, **When** 인제스천 중이면, **Then** 명시적 타임아웃 + 재시도/백오프를 적용하고 각 소스 레이트 한도/쿼터를 준수한다.
- **Given** 재시도 한도를 넘은 논문/단계, **When** 실패하면, **Then** DLQ로 보내고 이미 성공한 인덱스 버전을 조용히 손상시키지 않는다.
- **Traces**: RES-9, RES-8, RES-7, QT-9

---

## 에픽 5 — 신뢰성 & 운영 *(페르소나 OP)*

### US-R1 — 근거화 보장 + 할루시네이션 탐지
**As** 운영자(OP), **I want** 근거화를 지속 검증하기를, **so that** 할루시네이션을 잡아낸다.
- **Given** QT-1 평가셋, **When** 시스템 대비 실행하면, **Then** 날조 논문/인용 0건과 올바른 기권 동작을 보고한다.
- **Given** 근거화 검사를 통과하지 못한 응답, **When** 탐지되면, **Then** **할루시네이션 인시던트** 신호가 발생·경보된다.
- **Traces**: FR-5, QT-1, RES-11(b)

### US-R2 — 우아한 저하 + 반쪽짜리 결과 탐지
**As** 운영자(OP), **I want** 시스템이 우아하게 저하되고 반쪽짜리 결과를 표시하기를, **so that** 사용자가 조용한 반쪽 답변을 받지 않는다.
- **Given** 의존성 장애, **When** 검색이 실행되면, **Then** 저하되었으나 표시된 결과 또는 명시적 실패를 제공한다 — 조용한 오답/반쪽 답변은 절대 아님.
- **Given** 불완전/반쪽짜리 결과, **When** 탐지되면, **Then** **반쪽짜리 결과 인시던트** 신호가 발생한다.
- **Traces**: NFR-R1, NFR-R2, RES-9, FR-11, RES-11(c), QT-3

### US-R3 — 비용 상한 서킷 브레이커 + 비용 폭발 탐지
**As** 운영자(OP), **I want** 지출이 자동으로 상한되기를, **so that** 비용이 폭주하지 않는다.
- **Given** 월 지출이 강한 상한에 근접, **When** 임계치를 넘으면, **Then** 서킷 브레이커가 상한 초과 이전에 저하한다(LLM 리랭킹 비활성화 / lexical 폴백).
- **Given** U1 eager Corpus 빌드가 예산 임계치에 접근, **When** 우선순위 밖 논문이 남아 있으면, **Then** 신규 빌드는 보류·백필/DLQ로 이월되고 기존 검색/열람은 명시적 저하 상태를 유지한다.
- **Given** 비정상 지출 급증, **When** 탐지되면, **Then** **비용 폭발 인시던트** 신호가 발생·경보된다.
- **Traces**: NFR-C1, RES-11(a), SEC-11

### US-R4 — 관측성 & AI 인시던트 경보
**As** 운영자(OP), **I want** 메트릭/로그/트레이스와 인시던트 경보를, **so that** 경량 IR + COE 프로세스에 따라 탐지·대응할 수 있다.
- **Given** 운영 중 서비스, **When** 대시보드를 열면, **Then** 지연·에러율·처리량·검색/근거화 건강도·지출·source별 watermark·DLQ 적체를 본다.
- **Given** 세 AI 인시던트 클래스(비용/할루시네이션/반쪽짜리 결과) 중 하나, **When** 신호가 발생하면, **Then** 경보가 장애 대응 프로세스로 라우팅되고 COE 후속이 따른다.
- **Traces**: NFR-O1, RES-5, RES-7, RES-11

### US-R5 — 헬스 체크
**As** 운영자(OP), **I want** 얕은 + 깊은 헬스 체크를, **so that** 비정상 인스턴스로의 라우팅을 우회한다.
- **Given** 배포된 인스턴스, **When** 건강도를 프로빙하면, **Then** 얕은 체크가 생존을 확인하고 깊은 체크가 arXiv/LLM/인덱스 연결을 검증하며; 비정상 인스턴스는 로테이션에서 제거된다.
- **Traces**: RES-6

---

## 에픽 6 — 요약 / 번역 *(U7, 2026-06-18 편입; 2026-06-29 페이즈 3 정합·Grounding 통합)*

> 결과 카드에서의 **온디맨드 보조 기능** — 검색된 *그 논문 1편*을 요약/번역(추출 경계, C-2 준수). P1의 4질문(겹치나·뭘 했나·되나·쌓을 수 있나)에 답하는 구조화 요약이 설계 프레임. 설계 입력: `../requirements/summarization-translation-pipeline.md`.
>
> **페이즈 3 갱신(2026-06-29)**: ① **전문(全文) 번역**(scope=full·DocModel(v1) 미러) 정합(US-S2), ② **Grounding Framework 통합(D3)** — 요약 grounding은 **U7 자체 결정론 Validator**(검색 U6 enforce 재사용 아님; 공유 추상 인터페이스/레지스트리 아래)(US-S3), ③ **뷰 프리셋·커뮤니티 용어집(P3) 폐기**(US-S4), ④ **QT-1 충실도 평가셋 신설**·수치 임계 재보정(US-S6). 근거 SSOT: `../requirements/requirement-verification-questions-u7-summarization.md`.

### US-S1 — AI 구조화 요약
**As** 연구자(P1), **I want** 검색한 논문의 전문을 구조화 요약으로 받기를, **so that** 초록에 안 나오는 결과 수치·한계·재현성을 빠르게 파악한다.
- **Given** 결과 카드, **When** [AI 요약]을 탭하면, **Then** 선택 논문의 **eager 생성된 DocModel(v1) 전문**을 기반으로 핵심주장·기여·방법·결과·한계·재현성 구조의 요약이 표시된다.
- **Given** 요약 내용, **When** 읽으면, **Then** 초록에 잘 안 나오는 결과 수치·한계·재현성이 본문/표에서 도출돼 포함된다(제네릭 요약 아님).
- **Given** 한 번 생성된 요약, **When** 저장되면, **Then** S3 영구저장+캐시되어 동일 키로 재사용된다(재생성·추가비용 0).
- **Traces**: FR-12, FR-5, C-2, QT-5

### US-S2 — 한국어 번역 (초록 / 전문) *(2026-06-29 개정 — 페이즈 3: 전문 번역)*
**As** 연구자(P1), **I want** 논문 초록 또는 전문을 한국어로 번역받기를, **so that** 영어 부담 없이 빠르게 핵심을 파악하거나 본문까지 정독한다.
- **Given** 결과 카드, **When** [한국어로](기본·초록)를 탭하면, **Then** 초록(Metadata Abstract)의 한국어 번역이 표시된다.
- **Given** 리치 뷰어/상세, **When** **전문 번역**(scope=full)을 요청하면, **Then** DocModel(v1)을 미러한 **동일 구조/id의 번역본 doc-model**이 같은 리치 뷰어로 표시된다(섹션·문단·캡션 번역; 표 셀·수식 LaTeX·코드·id·그림 assetRef는 원어/원본 보존).
- **Given** 전문용어(모델명·약어), **When** 번역되면, **Then** 용어집의 미번역 리스트 용어(Transformer·BERT 등)는 영어로 유지되고 용어가 일관되게 번역된다.
- **Given** 한 번 생성된 번역(초록·전문), **When** 다시 요청하면, **Then** S3 영구저장+캐시에서 동일 키로 재사용된다.
- **Traces**: FR-13, C-2

### US-S3 — 출처 보기 & 근거 부족 시 기권 *(2026-06-29 개정 — 페이즈 3: D3·앵커 입도)*
**As** 연구자(P1), **I want** 요약 각 항목의 원문 근거를 확인하고 근거가 없으면 지어내지 않기를, **so that** 재현이 어려운 논문 맥락에서도 결과를 신뢰·검증할 수 있다.
- **Given** 구조화 요약, **When** 항목의 "출처 보기"를 탭하면, **Then** 앵커(`target∈{section\|table\|figure}`·`label`)가 가리키는 원문 위치가 리치 뷰어에서 하이라이트된다(**검증 통과 앵커만** 노출; 검증 불가 앵커는 드롭).
- **Given** 원문에 근거가 없는 주장, **When** 요약/번역이 생성되면, **Then** **U7 자체 결정론 Validator**(앵커 존재 SOFT·수치 HARD·스키마·절단; LLM-judge 미사용; 검색 U6 enforce와 별개·공유 레지스트리)가 1회 재시도 후에도 실패면 날조 대신 **기권**하고 "근거 부족"을 명시한다(날조 0건, fail-closed).
- **Traces**: FR-12, FR-5, QT-5, FR-11

### US-S4 — 요약/번역 개인화 (수준·용어 선호) *(2026-06-29 개정 — 페이즈 3: 뷰 프리셋 폐기)*
**As** 연구자(P1), **I want** 요약 수준을 고르고 용어 선호를 저장하기를, **so that** 내 수준에 맞게 보고 전문용어가 일관되게 번역된다.
- **Given** 요약 생성, **When** 수준(전문가용/입문자용)을 고르면, **Then** 해당 수준 규칙이 적용된 요약이 제공된다(**요약 전용**, 논문당 최대 2벌 생성; 번역은 persona-agnostic 단일).
- **Given** 번역 용어 수정, **When** "이 번역 선호 저장"을 누르면, **Then** 개인 용어집(P2)에 반영돼 이후 일관 적용된다 — 기본은 번역 출력 위 **결정론적 덮어쓰기**(post-substitution, LLM 재호출 없음), 개인 용어집 조회 실패 시 seed(P1)-only로 저하(사용자별 비공개, 기권 안 함).
- _(뷰 프리셋(전체/3줄/관점별)·커뮤니티 공유 용어집(P3)은 폐기 — 코드 부재/미구현, FR-14·§12.)_
- **Traces**: FR-14, SEC-8

### US-S5 — 온디맨드 즉시/스트리밍 응답
**As** 연구자(P1), **I want** 이미 만든 요약은 즉시, 처음 보는 논문은 점진적으로 받기를, **so that** 기다림이 길게 느껴지지 않는다.
- **Given** 이전에 생성된 요약/번역, **When** 다시 요청하면, **Then** 캐시(Redis hot)/S3 영구저장에서 즉시 표시된다(재생성·추가비용 0).
- **Given** 처음 처리하는 논문, **When** 요약을 요청하면, **Then** 결과가 스트리밍으로 점진 렌더된다(검색 SLA NFR-P1 대상 아님).
- **Given** 초장문 전문 번역(map-only)·초장문 요약(map-reduce), **When** 요청하면, **Then** 비동기 백그라운드 잡으로 처리되고 진행(pending)·폴링 상태가 노출된다(게이트웨이 타임아웃 회피).
- **Traces**: NFR-P2, FR-12, FR-13

### US-S6 — 요약 비용 게이트 + 근거화 운영 *(페르소나 OP; 2026-06-29 개정 — 페이즈 3)*
**As** 운영자(OP), **I want** 요약 LLM 비용이 상한 안에서 통제되고 요약/번역 근거화가 지속 검증되기를, **so that** 비용 폭주·할루시네이션을 막는다.
- **Given** CostGuard spend ratio가 **0.80(=$1,280/$1,600)에 도달**, **When** 요약/번역 요청이 오면, **Then** degrade_mode≠normal로 U7이 LLM 호출을 차단해 **일시 기권**("AI 요약 일시 중단")하고 비용 폭발 신호로 잇는다(U6 단일권위, U7 재판정 없음).
- **Given** **QT-1 충실도 평가셋을 페이즈 3에서 신설**(grounded/날조 라벨 케이스 + `run_eval_set` 구현; 현재 부재), **When** 시스템 대비 실행하면, **Then** 날조 0건·올바른 기권을 보고하고 근거화 미통과 응답은 할루시네이션 인시던트로 경보되며, **수치 임계(현 0.5 추정값)를 평가셋 기반 strict 값으로 재보정**한다(matcher 정밀화 동반).
- **Traces**: NFR-C1, RES-11(a), RES-11(b), QT-5, QT-1, FR-11, SEC-11

---

## 에픽 7 — 인용 그래프 / 각주 트리 *(U8, 2026-06-19 편입)*

> 논문 상세보기 페이지의 보조 액션. 상세보기 FE 자체는 타 분기 산출물이며, U8은 각주 트리 데이터·계약·검증 책임만 가진다.

### US-CG1 — 논문 상세보기에서 각주 트리 열기
**As** 연구자(P1), **I want** 논문 상세보기에서 각주 트리를 열기를, **so that** 이 논문이 어떤 선행 연구를 기반으로 하는지 빠르게 파악한다.
- **Given** 로그인한 사용자가 논문 상세보기 페이지를 열었고, **When** 각주 트리 버튼을 탭하면, **Then** 선택 논문의 backward references가 트리로 표시된다.
- **Given** 상세보기 페이지, **When** 주요 액션을 보면, **Then** 요약·초록 번역·전문 번역·각주 트리 4개 버튼이 같은 진입 영역에 배치된다. 단, FE 구현은 본 U8 범위가 아니다.
- **Traces**: FR-15, NFR-P3, SEC-8

### US-CG2 — 제한된 깊이와 노드 메타데이터
**As** 연구자(P1), **I want** 각주 트리를 과하지 않은 깊이로 펼치기를, **so that** 폰에서도 선행 연구 흐름을 잃지 않는다.
- **Given** 각주 트리, **When** 처음 표시되면, **Then** 기본 1-hop references를 보여준다.
- **Given** 사용자가 노드를 펼치면, **When** 추가 references를 요청하면, **Then** 최대 2-hop과 화면당 50노드 상한을 넘지 않는다.
- **Given** 각 노드, **When** 표시되면, **Then** 제목·연도·인용수를 보여준다.
- **Traces**: FR-15, QT-6

### US-CG3 — 인용 근거화와 unresolved 분리
**As** 연구자(P1), **I want** 확정 가능한 인용만 노드로 보기를, **so that** 존재하지 않는 인용을 신뢰하지 않는다.
- **Given** 외부 인용 API 응답, **When** ID가 해소되는 reference가 있으면, **Then** 확정 노드로 표시된다.
- **Given** 제목 문자열만 있거나 ID가 불명확한 reference, **When** 트리를 조립하면, **Then** unresolved 항목으로 분리하고 확정 노드로 승격하지 않는다.
- **Given** 중복 또는 순환 관계, **When** 트리를 표시하면, **Then** 중복 노드는 "이미 표시됨"으로 접고 순환으로 무한 확장하지 않는다.
- **Traces**: FR-15, FR-5, QT-6

### US-CG4 — 인용 노드 라이브러리 저장
**As** 연구자(P1), **I want** 각주 트리에서 발견한 논문을 내 라이브러리에 저장하기를, **so that** 후속 읽기 목록으로 남긴다.
- **Given** 각주 트리 노드, **When** "라이브러리에 저장"을 탭하면, **Then** 해당 논문이 내 비공개 라이브러리에 저장된다.
- **Given** 저장된 노드, **When** 저장 메타데이터를 보면, **Then** U4 `LibraryItemMeta` 스냅샷과 같은 계약을 따른다.
- **Traces**: FR-16, FR-9, SEC-8

### US-CG5 — 인용 API 실패/쿼터 저하
**As** 연구자(P1), **I want** 인용 정보를 못 불러와도 논문 상세보기는 유지되기를, **so that** 장애를 빈 결과로 오해하지 않는다.
- **Given** 캐시된 citation snapshot, **When** 외부 인용 API가 실패하면, **Then** 캐시된 snapshot을 우선 표시한다.
- **Given** 캐시가 없고 외부 API가 실패하거나 쿼터를 초과하면, **When** 각주 트리를 열면, **Then** 루트 논문은 유지하고 "인용 정보를 불러올 수 없음" 상태를 표시한다.
- **Traces**: FR-16, FR-11, NFR-R2, NFR-C1, RES-9

### US-CG6 — 인용 그래프 운영 관측성 *(페르소나 OP)*
**As** 운영자(OP), **I want** 인용 그래프 조회 품질과 외부 API 상태를 관측하기를, **so that** 쿼터·오류·불명확 인용 문제를 빠르게 발견한다.
- **Given** 운영 중 서비스, **When** 대시보드를 보면, **Then** 조회 수·캐시 적중률·외부 API 오류율/429·unresolved 비율·노드 수·응답 지연을 볼 수 있다.
- **Given** QT-6 평가/속성 테스트, **When** 실행되면, **Then** 날조 인용 0건과 그래프 불변식 위반 0건을 보고한다.
- **Traces**: NFR-O1, QT-6, RES-11(b)

---

## 에픽 8 — 개인화 / 행동 인텔리전스 *(U9, 2026-06-23 편입)*

> 의미 있는 도메인 이벤트만 기록해 사용자별 관심 프로필을 만들고, 검색 결과와 요약/번역 기본값에 작게 반영한다. v1은 별도 추천 목록, 전체 클릭스트림, hover/scroll 추적, 강한 리랭크, 실시간 ML 추천 파이프라인을 제외한다.

### US-P1 — 의미 있는 행동 이벤트 기록
**As** 연구자(P1), **I want** 검색·조회·저장·요약 요청 같은 의미 있는 행동만 기록되기를, **so that** 불필요한 클릭 추적 없이 개인화가 가능하다.
- **Given** 로그인한 사용자가 검색, 논문 조회, 라이브러리 저장/해제, 요약/번역 요청, 출처 앵커 클릭, 용어집 수정을 수행하면, **When** 해당 API 또는 UI 액션이 성공하면, **Then** 사용자별 `user_behavior_events`에 최소 이벤트가 기록된다.
- **Given** 단순 hover, scroll, 임의 클릭, 페이지 체류 시간, **When** 사용자가 화면을 탐색하면, **Then** v1에서는 행동 이벤트로 기록하지 않는다.
- **Given** 행동 이벤트 기록 저장소가 실패하면, **When** 본 기능 요청이 완료되어야 할 때, **Then** 요청은 실패하지 않고 개인화 이벤트만 누락/저하 신호로 남는다.
- **Traces**: FR-18, NFR-P4, SEC-8, SEC-9, RES-9

### US-P2 — 라이브러리 저장/해제와 출처 앵커 신호
**As** 연구자(P1), **I want** 라이브러리 저장·해제와 출처 보기 행동이 관심 신호로 반영되기를, **so that** 내가 실제로 검토한 논문이 프로필에 반영된다.
- **Given** 사용자가 논문을 라이브러리에 저장하면, **When** 저장이 성공하면, **Then** `library_added` 이벤트가 논문 ID와 함께 기록된다.
- **Given** 사용자가 논문을 라이브러리에서 해제하면, **When** 삭제가 성공하면, **Then** 삭제 전 확보한 논문 ID로 `library_removed` 이벤트가 기록된다.
- **Given** 사용자가 요약/번역의 출처 보기를 탭하면, **When** 앵커 이동이 성공하면, **Then** `source_anchor_clicked` 이벤트가 기록되며 원문 내용 자체는 저장하지 않는다.
- **Traces**: FR-18, FR-9, FR-12, FR-13, SEC-8, QT-7

### US-P3 — 사용자 관심 프로필 집계
**As** 연구자(P1), **I want** 내 행동이 관심 주제 프로필로 집계되기를, **so that** 반복적으로 보는 분야가 다음 탐색에 반영된다.
- **Given** 행동 이벤트가 쌓이면, **When** 집계 작업이 실행되면, **Then** arXiv 카테고리, 키워드 가중치, 저장/반복 조회 논문, 요약 persona, 번역 범위, 용어집 버전이 `user_interest_profile`에 반영된다.
- **Given** 원시 행동 이벤트가 90일을 넘으면, **When** 보관 정책이 실행되면, **Then** 원시 이벤트는 삭제 대상이 되고 집계 프로필만 유지된다.
- **Given** 중복 이벤트나 순서가 바뀐 이벤트가 들어오면, **When** 프로필을 집계하면, **Then** 사용자별 격리와 가중치 상한 불변식이 깨지지 않는다.
- **Traces**: FR-19, QT-7, PBT-02, PBT-03, PBT-07, SEC-8

### US-P4 — 검색 결과 소폭 개인화
**As** 연구자(P1), **I want** 검색 결과가 내 관심 주제를 약하게 반영하기를, **so that** 관련성이 높은 논문을 더 빨리 본다.
- **Given** 개인화가 켜져 있고 관심 프로필이 존재하면, **When** 검색을 실행하면, **Then** 기본 검색 랭킹 위에 작은 boost/rerank만 적용된다.
- **Given** 개인화가 적용된 결과, **When** 결과 목록을 보면, **Then** "내 관심 주제 반영" 표시와 끄기 진입점이 보인다.
- **Given** 개인화 프로필 또는 저장소가 실패하면, **When** 검색을 실행하면, **Then** 기본 비개인화 검색 결과가 반환된다.
- **Traces**: FR-20, FR-2, FR-3, NFR-P4, NFR-R2, RES-9

### US-P5 — 요약/번역 기본값 개인화
**As** 연구자(P1), **I want** 최근에 쓰던 요약/번역 기본값이 기억되기를, **so that** 매번 같은 옵션을 고르지 않아도 된다.
- **Given** 사용자가 요약 수준(전문/입문), 번역 범위(초록/전문), 용어집 선호를 사용하면, **When** 다음 요약/번역을 요청하면, **Then** 최근 선호가 기본값으로 제안된다. _(뷰 프리셋은 폐기 — 페이즈 3/Q9.)_
- **Given** 개인화 기본값이 제안되면, **When** 사용자가 다른 옵션을 선택하면, **Then** 그 요청에서는 사용자 선택이 우선한다.
- **Given** 개인화가 꺼져 있거나 프로필이 없으면, **When** 요약/번역을 요청하면, **Then** 기존 기본값을 사용한다.
- **Traces**: FR-20, FR-14, FR-12, FR-13, SEC-8

### US-P6 — 개인화 제어권
**As** 연구자(P1), **I want** 개인화를 끄고 내 행동 로그와 프로필을 지울 수 있기를, **so that** 개인 데이터 사용을 직접 통제한다.
- **Given** 설정 화면, **When** 사용자가 개인화를 끄면, **Then** 이후 검색/요약/번역은 비개인화 기본 경로를 사용한다.
- **Given** 사용자가 행동 로그 삭제를 요청하면, **When** 요청이 성공하면, **Then** 사용자 원시 행동 이벤트가 삭제된다.
- **Given** 사용자가 관심 프로필 초기화를 요청하면, **When** 요청이 성공하면, **Then** 집계 프로필과 개인화 기본값이 초기화된다.
- **Traces**: FR-20, FR-19, SEC-8, SEC-14

### US-P7 — 개인화 운영 관측성과 저하
**As** 운영자(OP), **I want** 개인화 파이프라인의 실패와 저하를 관측하기를, **so that** 개인화 문제를 본 기능 장애로 확대하지 않는다.
- **Given** 운영 중 서비스, **When** 대시보드를 보면, **Then** 이벤트 기록 실패율, 프로필 집계 실패율, 개인화 적용률, 비개인화 폴백 수를 볼 수 있다.
- **Given** 개인화 저장소나 집계가 실패하면, **When** 사용자가 검색/요약/번역을 사용하면, **Then** 기본 기능은 유지되고 저하 신호만 기록된다.
- **Given** QT-7 속성 테스트, **When** 실행되면, **Then** 이벤트 DTO roundtrip, 사용자별 격리, 프로필 가중치 불변식, 중복 이벤트 안정성을 검증한다.
- **Traces**: NFR-P4, QT-7, NFR-O1, RES-9, RES-11(c)

---

## 에픽 9 — 차별화(novelty) 형성 Agent *(2026-06-29 편입)*

> 자연어 연구 의도 또는 업로드 원고를 받아 유사 연구를 정리하고, 근거 기반 차별화 후보와 실험 계획을 만든다. 문헌탐색·근거형성 Agent는 별도 유닛이며, 본 Agent는 `EvidenceFormationPort`/`SourceRef` 공유계약만 소비한다. v1 외부 탐색은 GitHub와 데이터셋으로 제한하고 뉴스 검색은 다음 사이클로 둔다.

### US-NV1 — 자연어 연구 의도에서 novelty job 시작
**As** 연구자(P1), **I want** "~~~를 연구하고 싶다" 같은 자연어로 novelty 분석을 시작하기를, **so that** 아직 원고가 없어도 유사 연구와 차별화 방향을 빠르게 본다.
- **Given** 로그인한 사용자가 자연어 연구 의도를 입력하면, **When** novelty 분석을 시작하면, **Then** 시스템은 먼저 `EvidenceFormationPort.form_evidence`를 호출해 근거 묶음을 만들고 novelty Agent는 그 결과를 소비한다.
- **Given** Evidence 결과가 부족하면, **When** novelty Agent가 후속 검색을 수행하면, **Then** U2 `full` 검색으로 내부 Corpus 유사 논문을 보강한다.
- **Traces**: FR-30, FR-31, NFR-P5

### US-NV2 — 업로드 원고에서 novelty job 시작
**As** 연구자(P1), **I want** 작성 중인 논문 문서를 올려 novelty 분석을 받기를, **so that** 내 원고와 겹치는 선행 연구와 차별화 지점을 확인한다.
- **Given** 사용자가 PDF, Markdown, TXT 중 하나를 업로드하면, **When** 분석을 시작하면, **Then** 공통 ingestion/doc-model 또는 문헌탐색·근거형성 경로가 문서를 파싱하고 novelty Agent는 파싱된 Evidence/SourceRef만 소비한다.
- **Given** 파싱에 실패하면, **When** 결과 화면을 보면, **Then** 파싱 실패 사유를 비기술 메시지로 표시하고 원본이나 내부 오류 상세를 노출하지 않는다.
- **Traces**: FR-30, SEC-5, SEC-9

### US-NV3 — 유사 연구 표 정리
**As** 연구자(P1), **I want** 내 아이디어와 유사한 선행 논문을 표로 정리해 보기를, **so that** 이미 완료된 연구와 겹치는 부분을 파악한다.
- **Given** Evidence와 U2 full 검색 결과가 있으면, **When** 유사 연구 정리를 생성하면, **Then** 논문별 문제정의, 방법, 데이터셋, 결과, 한계, 내 아이디어와 겹치는 점, SourceRef를 표로 제공한다.
- **Given** 어떤 주장에 충분한 근거가 없으면, **When** 표를 생성하면, **Then** 해당 칸은 추측하지 않고 기권 또는 근거 부족으로 표시한다.
- **Traces**: FR-31, FR-32, FR-5, QT-10

### US-NV4 — GitHub와 데이터셋 근거 보강
**As** 연구자(P1), **I want** 관련 구현체와 데이터셋 단서를 함께 보기를, **so that** 차별화 실험이 실제로 수행 가능한지 판단한다.
- **Given** novelty job이 외부 탐색 단계에 들어가면, **When** Agent-Browser가 검색하면, **Then** 서버 측 Agent Worker에서 익명화된 최소 질의로 GitHub와 데이터셋을 검색한다.
- **Given** GitHub 결과가 있으면, **When** 결과를 정규화하면, **Then** 관련 구현체, baseline/benchmark 코드, reproduction 단서, license를 추출하되 품질 점수나 재현 가능 판정은 하지 않는다.
- **Given** 데이터셋 결과가 있으면, **When** 결과를 정규화하면, **Then** 데이터셋 이름, URL, 라이선스/접근성, 태스크, metric 후보를 실험 계획 후보에 연결한다.
- **Traces**: FR-31, NFR-R3, SEC-3, SEC-9

### US-NV5 — 원고 위험 신호 표시
**As** 연구자(P1), **I want** 내 원고의 문장 유사도와 AI 어투 위험 신호를 따로 보기를, **so that** 제출 전 검토가 필요한 부분을 알 수 있다.
- **Given** 업로드 원고가 파싱되면, **When** 원고 위험 신호를 계산하면, **Then** 내부 Corpus 대비 문장/문단 유사도 경고를 법적 표절 판정이 아닌 검토 신호로 표시한다.
- **Given** AI 어투 위험 신호가 감지되면, **When** 사용자에게 표시하면, **Then** 확정 판정이나 AI 작성 확률 대신 문체 위험 신호와 false positive 가능성을 함께 보여준다.
- **Given** 위험 신호가 높아도, **When** novelty 분석을 계속하면, **Then** 실험 아이디어 추천과 실험 계획 생성을 차단하지 않는다.
- **Traces**: FR-34, QT-10

### US-NV6 — 차별화 후보와 실험 계획 생성
**As** 연구자(P1), **I want** 차별점이 추가된 실험 아이디어와 실행 계획을 받기를, **so that** 다음 실험을 구체적으로 설계한다.
- **Given** 유사 연구와 외부 보강 근거가 있으면, **When** novelty Agent가 아이디어를 제안하면, **Then** 기존 연구 한계와 코드/데이터셋 근거 안에서 bounded 실험 아이디어 후보를 제안한다.
- **Given** 사용자가 후보를 검토하면, **When** 실험 계획을 생성하면, **Then** 가설, 차별화 포인트, baseline, 데이터셋, metric, 절차, 리스크, 필요한 구현/리소스, 근거 링크를 포함한다.
- **Given** 결과를 표시할 때, **Then** "새로움 확정", novelty 점수, 논문화 가능성 판정, 코드 skeleton은 생성하지 않는다.
- **Traces**: FR-32, FR-33, C-2

### US-NV7 — 탐구 프로세스 진행상태 표시
**As** 연구자(P1), **I want** 에이전트가 지금 무엇을 하고 있는지 단계별로 보기를, **so that** 긴 분석 중에도 멈춘 것인지 진행 중인지 알 수 있다.
- **Given** novelty job이 생성되면, **When** 프론트가 상태를 조회하거나 구독하면, **Then** `queued`, `retrieving_corpus`, `searching_external`, `summarizing_prior_work`, `checking_similarity`, `forming_ideas`, `planning_experiment`, `exporting_notion`, `completed`, `failed`, `degraded` 중 하나를 표시한다.
- **Given** 각 단계가 진행되면, **When** UI가 업데이트되면, **Then** 현재 tool, 검색 질의, 발견한 출처 수, 부분 결과, 실패/저하 상태를 보여준다.
- **Given** 일부 source가 실패하면, **When** job이 계속 가능하면, **Then** source별 `degraded`를 표시하고 성공한 source만으로 부분 산출물을 제공한다.
- **Traces**: FR-35, NFR-P5, NFR-R3

### US-NV8 — 내부 저장 후 Notion export
**As** 연구자(P1), **I want** novelty 결과를 검토한 뒤 Notion에 저장하기를, **so that** 연구 계획을 내 작업 공간으로 옮긴다.
- **Given** novelty 결과가 완료되면, **When** 저장 상태를 보면, **Then** DocSuri 내부 DB/S3에 owner-scoped 세션, 입력 참조, 단계 이벤트, 최종 결과, export 상태가 저장된다.
- **Given** 사용자가 Notion 연결을 승인하면, **When** export를 실행하면, **Then** 사용자별 OAuth 또는 명시 연결 토큰을 사용하고 토큰은 암호화 저장된다.
- **Given** 사용자가 미리보기 후 export를 승인하면, **When** Notion MCP 호출이 성공하면, **Then** Notion 저장 위치와 상태를 표시한다. 자동 export는 하지 않는다.
- **Traces**: FR-35, SEC-8, SEC-12, SEC-14

### US-NV9 — novelty Agent 운영 관측성과 품질 게이트 *(페르소나 OP)*
**As** 운영자(OP), **I want** novelty Agent의 비용, 외부 source 장애, 근거 무결성, export 실패를 관측하기를, **so that** 조용한 오답과 비용 폭주를 막는다.
- **Given** 운영 대시보드, **When** novelty job 지표를 보면, **Then** job 수, 단계별 실패율, U2 full 검색 사용량, Agent-Browser 호출 수, source별 degraded 수, Notion export 실패율, per-job budget 초과를 볼 수 있다.
- **Given** QT-10이 실행되면, **When** 결과를 확인하면, **Then** SourceRef 무결성, source normalization, job state transition, 실험 계획 필수 필드, Notion export 무결성을 검증한다.
- **Traces**: NFR-C1, NFR-O1, QT-10, RES-11

---

## 에픽 10 — 문헌탐색·근거형성 Agent *(U4, 2026-06-29 편입)*

> 연구자가 여러 논문을 가로질러 근거를 형성하는 대화형 AI Agent. 검색·DocModel·요약·인용 파이프라인을 Agent가 자율 오케스트레이션해 핵심 주장·방법·결과·한계를 추출·비교하고 쟁점 오버레이로 제시. 신뢰 원칙: 날조 없음(FR-5·C-2), 근거 0건이면 기권(abstain). D5 포트(EvidenceFormationPort)를 통해 U12(연구아이디어 Agent)가 소비한다. 설계 입력: `../requirements/requirements.md` §FR-36~38, NFR-P6, QT-8.

### US-EV1 — 근거형성 세션 시작
**As** 연구자(P1), **I want** 로그인 후 채팅 화면에서 근거형성 세션을 시작하기를, **so that** 관심 주제를 멀티턴 대화로 탐색할 수 있다.
- **Given** 로그인한 사용자가 근거형성 Agent 진입점(하단 네비)을 탭하면, **When** 페이지가 열리면, **Then** 빈 채팅 화면과 연구 주제 입력창이 표시된다.
- **Given** 로그인하지 않은 사용자가 진입점을 탭하면, **When** 접근하면, **Then** 로그인 화면으로 리다이렉트된다.
- **Given** 이전에 저장된 세션이 있으면, **When** 진입점을 열면, **Then** 저장된 세션 목록이 표시되고 재진입할 수 있다.
- **Traces**: FR-36, SEC-8

### US-EV2 — 자동 범위 근거형성 질문
**As** 연구자(P1), **I want** 연구 주제를 입력하면 Agent가 관련 논문을 자동 검색해 근거를 추출·비교해 주기를, **so that** 직접 논문을 고르지 않아도 다논문 비교 결과를 받는다.
- **Given** 사용자가 연구 주제를 입력하고 전송하면, **When** Agent가 auto scope으로 근거형성을 실행하면, **Then** 관련 논문에서 추출한 근거 명제(핵심 주장·방법·결과 수치·한계) 비교표와 쟁점 오버레이가 스트리밍으로 점진 표시된다.
- **Given** 표시된 근거 명제, **When** 읽으면, **Then** 논문 원문 추출 기반이며 생성 산문(새로운 주장)을 포함하지 않는다(C-2, FR-5).
- **Given** 각 근거 명제에 상충 출처가 있으면, **When** 쟁점 오버레이를 보면, **Then** 지지/상충 출처가 함께 표시된다.
- **Traces**: FR-37, FR-5, C-2, NFR-P6, QT-8

### US-EV3 — 명시 논문 집합 근거형성
**As** 연구자(P1), **I want** 내 라이브러리 논문이나 arXiv ID를 지정해 근거형성 범위를 제한하기를, **so that** 이미 검토한 논문 집합 안에서 근거를 비교한다.
- **Given** 사용자가 paperIds를 명시해 질문하면, **When** Agent가 explicit scope으로 근거형성을 실행하면, **Then** 지정 논문 집합만 사용해 근거를 추출·비교하고 자동 검색은 하지 않는다.
- **Given** 명시 집합과 자동 검색을 혼합 요청하면, **When** mixed scope을 사용하면, **Then** 명시 집합과 자동 검색 결과를 병합해 근거를 형성한다.
- **Traces**: FR-37, FR-9, Q4=A

### US-EV4 — 첨부 문서 근거형성
**As** 연구자(P1), **I want** 아직 인덱싱되지 않은 내 논문 초안이나 PDF를 첨부해 근거형성 입력으로 사용하기를, **so that** Corpus 바깥의 문서도 비교 근거에 포함한다.
- **Given** 사용자가 문서를 첨부해 근거형성 질문을 하면, **When** Agent가 실행되면, **Then** 첨부 문서를 doc-model 파이프라인으로 처리해 근거 추출 대상에 포함한다.
- **Given** 첨부 문서가 허용 형식·크기 한도를 초과하면, **When** 처리 전 검증하면, **Then** 즉시 에러 안내를 표시하고 처리를 시작하지 않는다.
- **Traces**: FR-37, FR-18, Q6=A

### US-EV5 — 멀티턴 후속 질문
**As** 연구자(P1), **I want** 이전 근거형성 응답 맥락을 유지하며 후속 질문을 이어가기를, **so that** 한 세션 안에서 주제를 점진적으로 심화한다.
- **Given** 근거형성 첫 응답이 완료된 상태에서 사용자가 후속 질문을 입력하면, **When** Agent가 이전 턴 맥락을 참조해 응답하면, **Then** 이전 응답에서 언급된 논문·근거를 재활용해 더 구체화된 결과를 제공한다.
- **Given** 후속 질문이 이전 Corpus와 완전히 다른 주제이면, **When** Agent가 판단하면, **Then** 새로운 검색 scope으로 근거를 갱신한다.
- **Traces**: FR-36, FR-37, Q7=A

### US-EV6 — 기권 경로 (근거 없음·범위 밖)
**As** 연구자(P1), **I want** 근거가 없거나 Corpus 범위 밖이면 날조 대신 기권 메시지를 받기를, **so that** 없는 근거를 신뢰하는 오류를 막는다.
- **Given** Agent가 관련 근거를 찾지 못하면, **When** 근거형성 결과를 반환하면, **Then** state=abstain + 비기술 기권 사유("관련 근거를 찾을 수 없습니다" 수준)가 표시되고 날조 근거 명제는 0건이다.
- **Given** 질문이 Corpus 범위 밖이면, **When** 처리하면, **Then** out_of_corpus 사유로 기권하며 내부 벡터 점수·위반 상세를 사용자에게 노출하지 않는다.
- **Traces**: FR-37, FR-5, SEC-9, C-2, QT-8

### US-EV7 — 세션 재열람 & 영속
**As** 연구자(P1), **I want** 이전 근거형성 세션을 다시 열어 결과를 재확인하기를, **so that** 나중에 검토할 때 처음부터 재실행하지 않아도 된다.
- **Given** 사용자가 세션 목록을 열면, **When** 이전 세션을 선택하면, **Then** 해당 세션의 근거형성 결과와 대화 이력이 표시된다.
- **Given** 세션이 내 계정에만 저장되어 있으면, **When** 다른 사용자가 접근하면, **Then** 해당 세션을 절대 볼 수 없다.
- **Traces**: FR-38, SEC-8

### US-EV8 — 세션 삭제·초기화
**As** 연구자(P1), **I want** 근거형성 세션과 결과를 삭제하거나 초기화하기를, **so that** 개인 데이터를 직접 통제한다.
- **Given** 사용자가 특정 세션 삭제를 요청하면, **When** 삭제가 완료되면, **Then** 해당 세션의 대화 이력과 근거형성 결과가 삭제된다.
- **Given** 사용자가 전체 세션 초기화를 요청하면, **When** 초기화가 완료되면, **Then** 모든 근거형성 세션이 삭제되고 기본 상태로 돌아간다.
- **Traces**: FR-38, SEC-8, SEC-14

### US-EV9 — 근거형성 근거화·불변식 운영 *(페르소나 OP)*
**As** 운영자(OP), **I want** 근거형성 Agent의 날조 0건·abstain 경로·스트리밍 지연을 지속 검증하기를, **so that** 할루시네이션·반쪽짜리 결과를 조기 탐지한다.
- **Given** QT-8 근거화 평가셋, **When** 시스템 대비 실행하면, **Then** 날조 근거 명제 0건, EvidenceItem DTO 라운드트립 정합, abstain 경로 정상 동작을 보고한다.
- **Given** 스트리밍 응답, **When** NFR-P6 검사를 실행하면, **Then** 첫 토큰 지연이 허용 SLA 안에 있고 비동기 잡 오프로드가 올바르게 동작한다.
- **Given** U12가 EvidenceFormationPort.form_evidence()를 호출하면, **When** state=abstain 응답이 반환되면, **Then** U12가 날조 없이 기권 처리하는 것을 D5 계약 테스트로 검증한다.
- **Traces**: QT-8, FR-5, NFR-P6, NFR-O1, D5

---

## 페르소나 → 스토리 맵
| 페르소나 | 스토리 |
|---|---|
| P1 (박지훈) | US-H1, US-D1..D7, US-A1..A7, US-L1, US-L2, US-L3, US-I2, US-S1..S5, US-CG1..CG5, US-P1..P6, US-NV1..NV8, US-EV1..EV8 |
| P2 | US-H1, US-D1, US-A1..A7, US-P4, US-P5, US-P6, US-NV1, US-NV3, US-NV6, US-NV7 |
| OP | US-I1, US-I2, US-I3, US-R1, US-R2, US-R3, US-R4, US-R5, US-S6, US-CG6, US-P7, US-NV9, US-EV9 |

## FR → 스토리 커버리지
| 요구사항 | 스토리 |
|---|---|
| FR-1 | US-D1, US-H1 |
| FR-2 | US-D2 |
| FR-3 | US-D3 |
| FR-4 | US-D4 |
| FR-5 | US-D5, US-D6, US-R1, US-H1 |
| FR-6 | US-I1, US-I2 |
| FR-7 | US-A1, US-A2, US-H1 |
| FR-26 | US-A3 |
| FR-27 | US-A4 |
| FR-28 | US-A5, US-A6 |
| FR-29 | US-A7 |
| FR-8 | US-L1 |
| FR-9 | US-L2 |
| FR-10 | US-L3 |
| FR-11 | US-D6, US-D7, US-R2 |
| NFR-C1 | US-R3 |
| NFR-R1/R2 | US-D7, US-R2 |
| NFR-O1 | US-R4 |
| NFR-P1 | US-H1 (인수 기준) |
| SEC-4 | US-D4 |
| SEC-8 | US-A2, US-L1, US-L2, US-L3 |
| SEC-9 | US-D7 |
| SEC-11 | US-A1 |
| SEC-12 | US-A1, US-A2 |
| NFR-U1 | US-H1, US-D1, US-D4 |
| NFR-U2 | US-D4 |
| RES-6 | US-R5 |
| RES-7 | US-I2, US-I3, US-R4 |
| RES-8 | US-I3 |
| RES-9 | US-I3, US-R2 |
| RES-11 (a/b/c) | US-R3, US-R1, US-R2, US-R4 |
| QT-1 | US-D5, US-D6, US-R1 |
| QT-2 | US-D3 |
| QT-3 | US-D7, US-R2 |
| QT-4 (PBT) | 스토리 비매핑 — Functional/NFR Design 보류(RES-4/RES-12와 동일) |
| FR-18 (DocModel 리치뷰/phase-1 eager 생성) [U1/U7/U5] | US-I1, US-I2, US-S3 |
| QT-9 (U1 Corpus 품질/불변식) [U1] | US-I1, US-I2, US-I3 |
| FR-12 (AI 요약) [U7] | US-S1, US-S3, US-S5 |
| FR-13 (한국어 번역) [U7] | US-S2, US-S5 |
| FR-14 (요약/번역 개인화) [U7] | US-S4 |
| NFR-P2 (온디맨드 응답) [U7] | US-S5 |
| QT-5 (요약/번역 근거화) [U7] | US-S1, US-S3, US-S6 |
| NFR-C1 (U7 비용 게이트) [U7] | US-R3, US-S6 |
| FR-15 (각주 트리) [U8] | US-CG1, US-CG2, US-CG3 |
| FR-16 (인용 노드 저장/연동) [U8] | US-CG4, US-CG5 |
| NFR-P3 (각주 트리 온디맨드 응답) [U8] | US-CG1 |
| QT-6 (인용 엣지 정확도·그래프 불변식) [U8] | US-CG2, US-CG3, US-CG6 |
| NFR-C1 (U8 citation API 쿼터 게이트) [U8] | US-CG5 |
| FR-19 (사용자 관심 프로필) [U9] | US-P3, US-P6 |
| FR-20 (개인화 적용) [U9] | US-P4, US-P5, US-P6 |
| NFR-P4 (개인화 비차단) [U9] | US-P1, US-P4, US-P7 |
| QT-7 (행동/프로필 불변식) [U9] | US-P2, US-P3, US-P7 |
| FR-30 (novelty 입력·오케스트레이션) | US-NV1, US-NV2 |
| FR-31 (U2 full 검색·외부 탐색) | US-NV1, US-NV3, US-NV4 |
| FR-32 (유사 연구·차별화 후보) | US-NV3, US-NV6 |
| FR-33 (실험 계획) | US-NV6 |
| FR-34 (원고 위험 신호) | US-NV5 |
| FR-35 (진행상태·저장·Notion export) | US-NV7, US-NV8 |
| NFR-P5/R3 (novelty 비동기·source별 저하) | US-NV7, US-NV9 |
| QT-10 (novelty 품질/불변식) | US-NV3, US-NV5, US-NV9 |
| FR-36 (근거형성 세션·멀티턴) [U4] | US-EV1, US-EV5 |
| FR-37 (다논문 근거형성·추출·기권) [U4] | US-EV2, US-EV3, US-EV4, US-EV5, US-EV6 |
| FR-38 (근거형성 세션 영속·사용자 제어) [U4] | US-EV7, US-EV8 |
| NFR-P6 (스트리밍 우선·비동기 잡) [U4] | US-EV2, US-EV9 |
| QT-8 (근거형성 근거화·불변식) [U4] | US-EV2, US-EV6, US-EV9 |

_FR-1..11 전부 커버됨(표 본문 대조 검증). **FR-12..14·NFR-P2·QT-5 = U7 에픽 6(US-S1..S6) 커버(2026-06-18 편입, 팀 합의). FR-15..16·NFR-P3·QT-6 = U8 에픽 7(US-CG1..CG6) 커버(2026-06-19 편입). FR-18·QT-9 = U1 Corpus/DocModel eager 개정(US-I1..I3 + US-S3) 커버(2026-06-26 편입). FR-19..20·NFR-P4·QT-7 = U9 에픽 8(US-P1..P7) 커버(2026-06-23 편입). FR-26..29 = 계정 에픽 2 보강(US-A3..A7) 커버(2026-06-24 편입 — 재설정·소셜 OIDC·라이프사이클·입력 견고화). FR-30..35·NFR-P5/R3·QT-10 = U12 에픽 9(US-NV1..NV9) 커버(2026-06-29 편입 — 차별화(novelty) 형성 Agent). FR-36~38·NFR-P6·QT-8 = U4 에픽 10(US-EV1..EV9) 커버(2026-06-29 편입 — 문헌탐색·근거형성 Agent).** SEC/RES의 인프라·설계 단계 항목(SEC-1/2/6/7/10/13/14, RES-1/2/3/4/10/12)은 스토리에 비매핑하고 NFR/Infra Design에서 다룬다. 적대적 비평 패스 완료(2026-06-15, 7/7 critic)._
