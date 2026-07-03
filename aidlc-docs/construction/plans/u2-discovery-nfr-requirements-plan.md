# u2-discovery-nfr-requirements-plan.md — NFR Requirements 계획 + 질문 게이트

**단계**: CONSTRUCTION → NFR Requirements (유닛별 루프, U2) · **유닛**: U2 Discovery · **트랙**: Track 3(@kyjness) · **일자**: 2026-06-16
**근거**: `construction/u2-discovery/functional-design/`(FD 산출물·답변 전부 A) · `requirements.md`(NFR-P1/C1/S1/R2, SEC, QT) · `unit-of-work.md`(UQ2 모노레포·UQ5 공유계약) · `project-structure-and-parallel-dev.md`(§5-A backend=Python) · U1 `tech-stack-decisions.md`(TD-3/TD-4 [전역])
**목적**: U2 비기능 요구사항 확정 + **기술 스택 선정**. FD 보류 수치(NFR-P1 예산 등) 정책 확정, mock-first 전환 경계 확정.
**고도(altitude)**: **스택 종류 + NFR 목표(정책 형태)**를 정한다. 리전/AZ 토폴로지(RES-2)·IaC·배포 타깃(ECS/Lambda)은 **Infra Design**; CI/CD·롤백·배포 방식(RES-4)·복원력 테스트(RES-12)는 **NFR Design**; NFR-P1 **수치 실측**은 Build & Test/Infra.

> **[전역] 계승(재결정 아님)**: U1(빌드 #1)이 PIN한 시스템 전역 결정을 U2가 상속한다 — **§5-A: backend 런타임=Python** · **TD-3: 임베딩=Cohere Embed Multilingual v4·1024·코사인·reader=`search_query`(cross-lingual KR↔EN; v3→v4 마이그레이션 완료 2026-06-24, 정합 정정 2026-06-30)** · **TD-4: 벡터+lexical 스토어=OpenSearch** · **NFR-C1=$1600/월(시스템 전역 상한)**. 해당 질문엔 `[전역 계승]` 표기.
> **[backend-shared] 조율 존**: 일부 결정(웹 프레임워크·공급망 툴링)은 backend 모듈형 모놀리스(단일 런타임·app-shell @ELSAPHABA)의 **공유 결정**이다 — U2가 제안하되 app-shell 소유자/트랙 합의 필요. `[backend-shared]` 표기.

---

## 1. 유닛 컨텍스트 (NFR 렌즈)

- U2 = **동기 검색 읽기 경로 API 모듈**(배포 ① backend 모놀리스 내). 사용자 동기 경로의 주체.
- **U2 핵심 NFR 동인**:
  - **NFR-P1(P50<3s, P95<8s)** — U2가 **주 대상**(질의→정렬 결과). 단계: 질의 임베딩(Bedrock Cohere) + OpenSearch 하이브리드 검색 + 랭킹 + 조립; 근거화(enforce)는 U6 게이트웨이 post-handler(종단 예산에 포함되나 책임 분리).
  - **NFR-C1(시스템 전역 $1600/월)** — U2 슬라이스 = **검색당 질의 임베딩 1회**(Q1=A/Q3=A로 LLM 재작성·리랭킹 없음 → LLM 비용 동인 최소). degradeMode는 U6 단일 권위 조회.
  - **NFR-S1(~3,000 사용자·동시 ~50)** · **NFR-R2(우아한 저하·lexical 폴백)** · **NFR-A1(99.5%, API 대상)**.
- **FD 잠금(답변 A)**: RRF·PaperId 디덥(BR-4)·baseline 랭킹 N=20(BR-5)·기권 우선(BR-9/10)·검증 NFC/다국어(BR-1/2)·인증 필수(BR-13)·비차단 이벤트(BR-14)·INV-1 단일 근거화 게이트·mock-first(MR-1~4).

---

## 2. NFR Requirements 실행 계획 (Step 2 — 답변 확정 후, 체크박스)

> 산출물은 `aidlc-docs/construction/u2-discovery/nfr-requirements/` 에 생성. **§4 답변 전 미생성.**

- [x] **nfr-requirements.md** — U2 NFR 확정:
  - 성능(**NFR-P1 예산 분해**·캐싱 정책·콜드스타트 가정), 확장성(stateless 수평 확장·동시성), 가용성/신뢰성(의존성 격리·폴백·fail-closed).
  - 비용(**NFR-C1 U2 슬라이스** = 질의 임베딩; 캐싱으로 중복 임베딩 회피; degradeMode 조회).
  - 보안: SEC-5(도메인 검증)·SEC-8(인증 위임)·SEC-9(비노출)·SEC-15(fail-closed)·SEC-3(PII 로깅 금지)·**SEC-10**(공급망, backend 공유)·**SEC-11 레이트리밋=U6 위임** 명시.
  - 관측성(NFR-O1: 구조화 로그·메트릭·트레이스 — `ObservabilityHub` 제출), 유지보수성(PBT·모노레포 빌드).
  - 테스트(QT-2 관련도 평가셋 한국어 포함·QT-3 저하 평가·QT-4 PBT).
- [x] **tech-stack-decisions.md** — ADR 형식(결정·근거·대안·전환 비용):
  - **[전역 계승]**: API 런타임=Python · 임베딩=Cohere Multilingual v4(reader=search_query) · 스토어=OpenSearch · NFR-C1 상한.
  - **[backend-shared]**: 웹 프레임워크 · 공급망 툴링(uv·락파일·SCA·SBOM·이미지 핀).
  - **U2 고유**: OpenSearch 하이브리드 질의 메커니즘(RRF) · 질의 임베딩 어댑터 · 캐싱 · PBT(Hypothesis) · **mock 어댑터 패키징/전환**.
- [x] **mock-first 전환 경계** — 포트(어댑터) 인터페이스 + 2구현(mock 픽스처/real) DI 토글; mock 픽스처에 QT-2+한국어 cross-lingual 케이스(MR-2).
- [x] **추적성** — NFR/스택 결정 → NFR-P1/C1/S1/R2, SEC-5/8/9/10/11/15, QT-2/3/4, C-5(AWS), §5-A/TD-3/TD-4 역추적.

---

## 3. 가정 (잘못이면 §4 또는 지적으로 정정)

- **NS-1**: 리전/AZ(RES-2)·IaC·CI/CD·롤백·배포 타깃(RES-4)·복원력 테스트(RES-12)는 본 단계 밖(NFR Design/Infra). NFR-P1 **수치 실측**은 Build & Test/Infra.
- **NS-2 [전역 계승]**: §5-A Python·TD-3 임베딩·TD-4 OpenSearch·NFR-C1 $1600은 U1에서 확정된 시스템 전역 결정 — **U2 재논의 아님**(계승·정합만 확인).
- **NS-3**: 근거화 **강제(enforce) 메커니즘**은 U6 소관(단일 권위). U2는 포트 소비 + 개발용 스텁(Q8 FD)만. U6 enforce 레이턴시는 종단 NFR-P1의 **의존성**(U2 책임 밖)이나 예산 분해에서 가시화.
- **NS-4 [backend-shared]**: 웹 프레임워크·공급망 툴링은 backend app-shell(@ELSAPHABA) 공유 결정 — U2 제안 + 소유자/트랙 합의로 확정.
- **NS-5**: mock↔real 교체는 `SearchResponse` 계약·FD 비즈니스 로직 불변(MR-4). real 어댑터 가동은 U1 코퍼스·OpenSearch·Bedrock 준비 후.

---

## 4. 명확화 질문 (Step 3 — `[Answer]:` 태그; A/B/C/D 또는 E=기타)

### A. 기술 스택

**Q1 [backend-shared] — API 웹 프레임워크.** backend 모듈형 모놀리스(§5-A Python 단일 런타임)의 웹 프레임워크.
- A) **FastAPI**(async·타입힌트·**pydantic v2 정합**(shared/python 이미 pydantic v2)·async I/O로 임베딩+검색 대기 중첩(NFR-P1)·자동 OpenAPI). (권장)
- B) Flask / Django REST Framework.
- C) 기타.
- **권장**: A — shared/python 바인딩(pydantic v2)·async 외부 호출(Bedrock/OpenSearch)·NFR-P1에 유리. **⚠️ backend 공유 결정 — app-shell 소유자(@ELSAPHABA)/트랙 합의 필요**(U2 단독 확정 아님).
- **[Answer]**: **A (FastAPI) — 제안. ⚠️ app-shell 소유자(@ELSAPHABA) 합의 전제로 기록**(잠정; backend 공유 결정이므로 트랙 사인오프 전까지 확정 아님). U2는 이 가정 위에서 NFR/설계 진행하되, 합의 결과가 다르면 재정합.

**Q2 — OpenSearch 하이브리드 질의 메커니즘(reader).** U2가 k-NN(ANN)+BM25를 어떻게 질의·병합?
- A) **opensearch-py(공식 클라이언트) + 앱 레벨 RRF 병합**(k-NN 쿼리 + BM25 쿼리 각각 → 앱에서 RRF, BR-4). (권장)
- B) OpenSearch 네이티브 하이브리드(search pipeline/normalization processor)로 **서버측 병합**.
- C) 기타.
- **권장**: A — RRF를 앱 레벨(BR-4)에 두면 mock/real 교체·결정성(PBT-07)·튜닝 용이. B는 OpenSearch 버전·파이프라인 의존(성능 이점은 Infra에서 재검토 여지). PaperId 디덥은 앱 레벨 유지.
- **[Answer]**: A

**Q3 [전역 계승] — 질의 임베딩 어댑터(LlmGatewayAdapter).** 질의 임베딩(reader=`search_query`)?
- A) **Bedrock Cohere Embed Multilingual v4(TD-3 계승)**, `input_type=search_query`(writer=search_document와 비대칭), 1024·코사인. (권장)
- B) 기타(= TD-3 재논의 — 전체 재임베딩 유발, 비권장).
- **권장**: A — 시스템 전역 계승(VectorSpec 불변식). cross-lingual(한국어 질의). **B는 사실상 불가**(U1 코퍼스 재임베딩).
- **[Answer]**: A

### B. 성능 (NFR-P1)

**Q4 — NFR-P1 레이턴시 예산 + 콜드스타트 가정.** P50<3s/P95<8s 검증 전제?
- A) **U2 자체 단계(embed+retrieve+rank+assemble)에 예산 할당 + U6 근거화는 별도 예산**(책임 분리); **워밍된 long-running 서비스 가정(콜드스타트 제외)**; 동시 ~50(NFR-S1). 수치 실측은 Build&Test/Infra. (권장)
- B) 종단 단일 예산(U6 근거화 포함)·콜드스타트 포함으로 보수적 검증.
- C) 기타.
- **권장**: A — U2는 모듈, 근거화는 U6 post-handler라 책임 분리가 자연스럽고 측정 가능. 콜드스타트는 배포 타깃(Infra) 종속 — long-running 컨테이너 가정. (Lambda면 B 보강.)
- **[Answer]**: A

**Q5 — 질의 임베딩/결과 캐싱(NFR-P1/C1).** 동일·유사 질의 반복 시?
- A) **질의 임베딩 캐시**(정규화 질의 키 기반, **명시 TTL**) — 동일 질의 재임베딩 회피(레이턴시·비용). 결과 페이지 캐시는 후순위(신선도·owner 스코프 복잡). (권장)
- B) 결과 페이지까지 캐시(신선도 정책 동반).
- C) 캐시 없음.
- **권장**: A — 캐싱 규약(미스 시 원본 적재·**TTL 필수·만료 없는 키 금지**)과 정합. 결과 캐시는 신선도/소유 스코프 주의로 후순위. 구체 TTL/스토어는 Infra.
- **[Answer]**: A

### C. 확장성 · 가용성

**Q6 — 동시성/확장 모델.** NFR-S1(~50 동시·~3,000 사용자)에서 U2?
- A) **stateless 모듈 + 수평 확장**(backend 인스턴스 복제) + **async I/O**(임베딩/검색 외부 대기 중첩). 오토스케일 트리거/수치는 Infra(RES-8). (권장)
- B) 기타.
- **권장**: A — stateless read 경로·수평 확장 용이. async로 외부 호출 동시성 확보.
- **[Answer]**: A

### D. 신뢰성 (NFR-R2 / RES-9)

**Q7 — 의존성 격리(타임아웃·서킷·폴백) 정책.** expand(Bedrock 임베딩)·retrieve(OpenSearch) 외부 호출 장애 시?
- A) **명시 타임아웃 + 서킷 + 폴백**: **임베딩 장애/타임아웃 → lexical-only 폴백**(DegradedResultDTO, US-R2 — degradeMode와 별개의 의존성 장애 폴백); **OpenSearch(인덱스) 장애 → fail-closed 에러**(검색 불가, 조용한 오답 금지). **수치는 NFR Design/Infra(AS).** (권장)
- B) 기타.
- **권장**: A — RES-9·NFR-R2·BR-16. 임베딩 폴백 가능(lexical 존재) vs 인덱스는 폴백 불가(fail-closed). 정책 형태만, 수치 후속.
- **[Answer]**: A

### E. 보안

**Q8 — 보안 처분(검증·인가·레이트리밋·공급망).**
- A) **U2 직접**: SEC-5(BR-1/2 도메인 검증)·SEC-9(BR-15 비노출)·SEC-15(BR-16 fail-closed)·SEC-3(질의 로깅 PII 정책). **위임**: SEC-8 인증·SEC-11 **레이트리밋=U6 게이트웨이**(U2 미구현). **공유**: SEC-10(락파일·SCA·SBOM·이미지 핀)=backend 모노레포 툴링. (권장)
- B) 기타.
- **권장**: A — 단일 권위 경계 준수(레이트리밋·인증=U6/게이트웨이). SEC-10은 backend 공유 CI(NFR Design 실행).
- **[Answer]**: A

### F. 테스트 (QT-2/3/4)

**Q9 [전역 계승] — PBT 프레임워크 + 평가셋 표면.**
- A) **Hypothesis(Python, TD-8 계승)** for PBT-02/03/07/09(도메인 제너레이터=다국어 질의·shrinking·시드 재현성). **QT-2 관련도 평가셋(Recall@10≥0.7, 한국어 질의 포함)** + **QT-3 저하/상태 평가**는 **mock 픽스처 기반으로 U2가 출력 표면 제공**(평가 실행 소유는 U6/OP). (권장)
- B) 기타.
- **권장**: A — 시스템 결정 계승. U2는 평가 대상 출력(랭킹·종단 상태)을 표면화, 평가셋 구축·실행 소유는 U6/OP.
- **[Answer]**: A

### G. 병렬 개발 (mock-first)

**Q10 — mock 어댑터 패키징/전환.** `VectorStoreAdapter`·`LexicalIndexAdapter`·`LlmGatewayAdapter`(+포트 스텁)?
- A) **포트 인터페이스 + 2구현(mock 픽스처 / real 어댑터), DI/환경 토글**. mock=결정적 픽스처(QT-2+한국어, MR-2); real(opensearch-py·Bedrock)은 U1 코퍼스 준비 후 교체. backend app-shell DI와 정합. (권장)
- B) 기타.
- **권장**: A — FD Q8/Q9·MR-1~4 계승. 계약(SearchResponse)·로직 불변 교체(MR-4).
- **[Answer]**: A

---

## 5. 다음 절차

1. `§4`의 `[Answer]:` 태그를 채운다(또는 채팅으로 A/B/C/D/E 회신). 모호 답변 시 후속 질문(Step 5) — 해소 전 진행 불가.
2. **[backend-shared] Q1·Q8 일부**는 app-shell 소유자/트랙 합의 표시(U2 단독 확정 아님).
3. 답변 확정 → `§2` 산출물 생성(`u2-discovery/nfr-requirements/` nfr-requirements·tech-stack-decisions + mock 전환 경계·추적성).
4. 완료 메시지 + 리뷰 게이트 → 승인 시 **U2 NFR Design**(검색/랭킹/캐싱/저하 패턴·논리 컴포넌트·CI=GHA 등).

> 본 계획·질문은 **리뷰 게이트**입니다. 답변 전까지 NFR Requirements 산출물을 생성하지 않으며, 아직 커밋하지 않았습니다.
