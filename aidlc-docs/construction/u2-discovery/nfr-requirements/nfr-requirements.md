# nfr-requirements.md — U2 Discovery 비기능 요구사항 (프로덕션)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U2 Discovery · **트랙**: Track 3(@kyjness) · **일자**: 2026-06-16
**근거**: FD 산출물(전부 A) · 계획서(§4 답변) · `requirements.md` · U1 `tech-stack-decisions.md`([전역])
**고도**: NFR 목표(정책 형태) + 스택 종류. 리전/IaC/CI-CD/배포 타깃·NFR-P1 수치 실측은 NFR Design/Infra/Build&Test 보류(NS-1).
**스코프**: 단일 프로덕션 트랙. U2 = 배포 ① backend 모놀리스 내 **동기 검색 읽기 모듈**.

---

> **페이즈 2 개정(2026-06-29, 재인셉션)**: lite/full scope SLA 프로파일(§1)·SEC-9 비노출에 `blockRefs`/`sourceProvenance` 추가(§5)·QT-1 멀티소스(비-arXiv) 근거 평가셋(§9). 임베딩 모델·specVersion 불변(Cohere Embed v4·specVersion v2).

## 1. 성능 (Performance) — NFR-P1 **주 대상**

- **목표(제안 계승)**: **P50 < 3s, P95 < 8s** 종단(질의 → 정렬 결과).
- **scope별 SLA(2026-06-29 — 페이즈 2/Q6·#236)**: NFR-P1 SLA 대상은 **`lite`(사람 검색창 기본)** — 초록 chunk k-NN + 제목/초록 BM25. **`full`(에이전트 심층·본문 chunk)은 비-SLA**(요약/에이전트 온디맨드 프로파일 준함). lite/full 분기는 #236 랜딩.
- **레이턴시 예산 분해(Q4=A)**: **U2 자체 단계**(질의 임베딩 + OpenSearch 하이브리드 검색 + RRF/랭킹 + 조립)에 예산 할당 + **U6 근거화(enforce, post-handler)는 별도 예산**(책임 분리). 종단 합이 NFR-P1 충족.
  - U2 단계 동인: Bedrock 질의 임베딩 1회(TD-U2-6) + OpenSearch k-NN+BM25 + 앱 RRF 병합.
  - **임베딩 캐시(TD-U2-7)**: 동일 정규화 질의 재임베딩 회피로 캐시 히트 시 임베딩 레이턴시 0.
- **콜드스타트 가정(Q4=A)**: **워밍된 long-running 서비스**(콜드스타트 제외) 가정. 배포 타깃(ECS/Fargate vs Lambda)·워밍은 Infra; Lambda 채택 시 콜드스타트 예산 재검토.
- **async I/O(Q6=A)**: 외부 호출(Bedrock/OpenSearch) 대기를 async로 중첩 — 동시 ~50(NFR-S1)에서 처리량 확보.
- **수치 실측**: P50/P95·캐시 TTL·동시성은 Build & Test/Infra 실측·확정(NS-1).

## 2. 확장성 (Scalability) — NFR-S1

- **규모**: 등록 ~3,000·동시 ~50(제안). U2는 재설계 없이 저(低)천명대 확장.
- **확장 모델(Q6=A)**: **stateless read 모듈 + 수평 확장**(backend 인스턴스 복제). 세션/상태 미보유(인증 컨텍스트는 게이트웨이 주입). 오토스케일 트리거/한도는 Infra(RES-8).
- **외부 쿼터 인지(RES-8)**: Bedrock 임베딩 처리량·OpenSearch 요청 한도 — 수치/쿼터 증액은 Infra.

## 3. 가용성 · 신뢰성 (Availability / Reliability)

- **가용성**: NFR-A1(99.5%, API 대상) — U2는 backend 배포 ①의 모듈로 그 가용성에 기여.
- **의존성 격리(Q7=A, RES-9 / NFR-R2)** — **정책 형태(수치는 NFR Design/Infra)**:
  - **임베딩(Bedrock) 장애/타임아웃 → lexical-only 폴백**(DegradedResultDTO, US-R2) — degradeMode와 별개의 의존성 장애 폴백.
  - **OpenSearch(인덱스) 장애 → fail-closed 에러**(검색 불가; 조용한 오답 금지, NFR-R1).
  - 명시 타임아웃 + 서킷 브레이커 + 정의된 저하 동작(BR-16, RES-10).
- **저하 모드(Q6=A, NFR-C1/R2)**: `getBudgetState().degradeMode`(U6 단일 권위 조회) → RERANK_OFF(U2 baseline상 무변화·배너만)/LEXICAL_ONLY(임베딩 생략·BM25). `ResultMeta.degraded`/`mode` 명시.
- **부분/조용한 결과 금지(NFR-R1)**: 종단 상태 명시(SearchResponse union). "조용한 결과"란 *무표시*를 뜻하며, **count:0을 명시한 빈 페이지(SearchResultPageDTO, resultCount=0)는 허용** — 무매치는 이 명시적 빈 페이지로 종단(BR-9). 금지되는 것은 근거 없는 카드를 성공인 양 섞는 것(→ AbstainDTO로 거부).

## 4. 비용 (Cost) — NFR-C1

- **NFR-C1 = $1600/월(시스템 전역, U1 확정)** — U2 슬라이스 = **검색당 질의 임베딩 1회** + OpenSearch 컴퓨트. **Q1=A/Q3=A로 LLM 재작성·리랭킹 없음** → U2 LLM 비용 동인 최소.
- **절감**: 임베딩 캐시(TD-U2-7)로 중복 질의 임베딩 회피; LEXICAL_ONLY 저하 시 임베딩 생략.
- **텔레메트리**: 질의 임베딩 호출수·검색 지연·degradeMode를 `ObservabilityHub`로 emit → NFR-C1/RES-11(a) 신호 공급. **U6.CostGuardCircuitBreaker가 시스템 상한 강제**(U2는 조회·분기만, BR-12). 유닛별 배분은 Infra.

## 5. 보안 (Security) — Q8=A

- **U2 직접**:
  - **SEC-5**: 질의 도메인 검증·새니타이즈(BR-1/2; ≤500자·제어문자 거부·NFC).
  - **SEC-9** *(2026-06-29 개정 — 페이즈 2)*: 내부 필드(owner·raw/RRF 점수·디버그·`vector`/`chunkId`/`section`/**`blockRefs`/`sourceProvenance`**) 외부 비노출(BR-6/15·INV-2; Q3: blockRefs/sourceProvenance 외부 노출 페이즈 3·4 이월); 카드는 소스 중립 투영(§domain-entities §5.1 + `sourceName`/`sourceUrl`, Q2)만; 일반화 에러.
  - **SEC-15**: 모든 외부 호출 fail-closed·전역 에러 핸들러(BR-16·INV-3).
  - **SEC-3**: 구조화 로깅(requestId 상관)·**질의 원문/PII 로깅 정책 준수**.
- **위임(단일 권위)**: **SEC-8 인증·인가** = U6 게이트웨이(authn) + U3.AuthorizationGuard(객체 인가) — U2는 `RequestContext.authSession` 신뢰(BR-13). **SEC-11 레이트리밋** = U6 게이트웨이(U2 미구현).
- **공유(backend)**: **SEC-10 공급망** — 락파일·SCA·SBOM·이미지 다이제스트 핀(TD-U2-9); CI 실행은 NFR Design.

## 6. 관측성 (Observability) — NFR-O1

- 구조화 로깅(타임스탬프·requestId·레벨, PII/시크릿 차단 SEC-3) + 메트릭(지연·검색/근거화 건강도·degradeMode·임베딩 호출수) + 트레이스 → **`U6.ObservabilityHub.emit*`/`startSpan` 제출**(단일 수집). 라이브러리는 언어(Python) 따름. 전송/대시보드는 U6/Infra.

## 7. 유지보수성 (Maintainability)

- **모노레포 `backend/modules/discovery/`**(UQ2=A) + Python 도구(uv 또는 app-shell 합의) + 락파일(SEC-10).
- **PBT(Q9=A)**: Hypothesis — PBT-02(정규화 멱등)·PBT-03(랭킹 순서/절단)·PBT-07(디덥/결과셋 보존)·PBT-09(DTO 라운드트립). 도메인 제너레이터에 **다국어(한국어) 질의 포함**.
- **모듈 경계**: U2는 backend 모놀리스 모듈 — app-shell/미들웨어(U6) 결선은 조율 존(직접 변경 금지).

## 8. 사용성 (Usability) — 위임

- **NFR-U1/U2(폰 우선·폰 목업)** = U5 소관. U2는 폰 카드 DTO(FR-4 7필드) **형상 제공**만(`ResultAssembler`).

## 9. 테스트 (QT-2/3/4) — Q9=A

- **QT-1(근거화 — 페이즈 2 보강)**: 보류 평가셋 날조 0건·코퍼스 밖 기권. **멀티소스(비-arXiv) 케이스 추가** — 소스 중립 실재 링크 검증(BR-18·GroundingStructuralGuard, Q2). enforce는 U6 단일권위(QT-1 평가셋 소유=U6/OP).
- **QT-2(관련도)**: Recall@10 ≥ 0.7(제안). **RelevanceRanker 출력이 평가 표면**; **평가셋에 한국어 질의 포함**(cross-lingual TD-3 검증). 평가셋 구축·실행 소유=U6/OP.
- **QT-3(신뢰성/저하)**: 모든 업스트림 장애·빈/기권/저하 경로 정의·테스트(BR-9/10/11/16). U6.ReliabilityEvalProbe 소유; U2는 저하 폴백·종단 상태 기여.
- **QT-4(PBT)**: §7.

## 10. 병렬 개발 (mock-first) — Q10=A

- **포트 + 2구현**: `VectorStoreAdapter`·`LexicalIndexAdapter`·`LlmGatewayAdapter`를 **인터페이스 + mock 픽스처/real 어댑터(opensearch-py·Bedrock)**, DI/환경 토글. mock 픽스처에 **QT-2 + 한국어↔영어 cross-lingual 케이스**(MR-2).
- **U6 포트 스텁(개발용)**: GroundingEnforcementHook=pass-through(+abstain 케이스); getBudgetState=정상 티어. 실 강제는 U6(MR-3).
- **계약 불변**: mock↔real 교체가 `SearchResponse`·FD 로직 불변(MR-4). U5는 동일 계약 mock으로 병렬.

## 11. 추적성

- NFR-P1(예산 분해·캐시·콜드스타트) · NFR-C1(질의 임베딩 슬라이스·캐시·degradeMode) · NFR-S1(stateless 수평) · NFR-R2/RES-9(폴백·fail-closed) · NFR-A1/O1 · SEC-5/8(위임)/9/10(공유)/11(위임)/15/3 · QT-2(한국어)/3/4 · C-5(AWS) · §5-A/TD-3/TD-4([전역 계승]) → §1~10 + `tech-stack-decisions.md`.
