# u1-ingestion-functional-design-plan.md — Functional Design 계획 + 질문 게이트

**단계**: CONSTRUCTION → Functional Design (유닛별 루프, 첫 유닛) · **유닛**: U1 Ingestion · **일자**: 2026-06-16
**근거(SSOT)**: `aidlc-docs/inception/` — `unit-of-work.md`, `unit-of-work-story-map.md`, `application-design/{components,component-methods,services,component-dependency}.md`, `user-stories/stories.md`, `requirements/requirements.md`
**원칙**: 이 단계는 **기술 무관(technology-agnostic)** — 비즈니스 로직·도메인 모델·비즈니스 규칙만 설계한다. 임베딩 모델·벡터 스토어·큐·언어/런타임 등 구체 기술은 **NFR Requirements/Infra Design**에서 확정.
**데모 우선**: Sprint 1 머지 기준은 "데모가 부팅되는가"다(프로덕션 완성도 아님). 권장안은 데모를 부팅시키는 최소 기능에 편향하되, 프로덕션 타깃을 설계 의도로 함께 문서화한다.
**검증**: 본 계획은 적대적 완전성 비평(3 렌즈: 컴포넌트 커버리지 · 비즈니스 규칙/엣지케이스 · 추적성/고도) 1회를 거쳐 보강했다 — §6은 그 결과로 추가된 동시성·복구 질문이다.

> **⚠️ 재스코핑(프로덕션 직행, 2026-06-16; Q2 재결정 2026-06-18)** — 팀 결정 "Go straight to production, don't think about demos." 데모-스코프 답변을 **프로덕션으로 오버라이드**: **Q1 A→D**(풀 FR-6 슬라이스: cs.LG·cs.AI·cs.CL·cs.CV·stat.ML, 최근 5년, 수십만 건), **Q2=B**(제목+초록만 인덱싱, issue #120; 전문은 S3 보관·U7 용도만), **Q12 A→B**(new-arXiv 이벤트 경로 활성). **Q13=B 유지**(철회 tombstone). 그 외(Q3~Q11·Q14~Q17·INV-1)는 프로덕션 스코프로 재해석(특히 SEC-9 오브젝트 스토리지 보관·BR-21 본문 크기 정책 **활성**, Q5 OA 라이선스 검증 재고). **이 배너가 §4 인라인 [Answer]를 오버라이드.** 데모/프로덕션 2-트랙 폐기 → 단일 프로덕션 트랙. FD 산출물은 프로덕션으로 갱신됨.

---

## 1. 유닛 컨텍스트 (Step 1 — Analyze Unit Context)

- **책임**: arXiv OA AI/ML 슬라이스를 수집·청크·임베딩하여 **공유 벡터 인덱스(+lexical 필드)** 를 생성·갱신하는 **단일 writer 독립 워커**(배포 ② 인제스천 워커). 사용자 동기 경로가 아니라 이벤트/스케줄 백본(DQ3=C/DQ6).
- **스토리**: **US-I1**(인제스천·인덱싱 시드 빌드, FR-6/C-1) · **US-I2**(최신성 스케줄 갱신, FR-6/RES-7) · **US-I3**(복원력 인제스천, RES-8/RES-9). 백킹: US-H1/US-D2(공유 인덱스 존재 전제).
- **컴포넌트(9)**: ArxivSourceClient · FetchParseProcessor · Chunker · EmbeddingGatewayAdapter · VectorIndexWriter · DeduplicationGuard · RefreshScheduler · NewArxivEventHandler · IngestFailureHandler.
- **서비스(3)**: **IngestionPipelineService**(fetch→parse→dedup→chunk→embed→index→watermark end-to-end 오케스트레이터) · **RefreshOrchestrationService**(스케줄+신규-arXiv 이벤트 제어 평면, 증분/전체 재구축 분배) · **IngestionResilienceService**(타임아웃·재시도/백오프·서킷·DLQ·쿼터·실패/갱신 건강도 신호).
- **공유 계약**: `VectorSpec`(차원·모델·거리 메트릭) — U1 writer와 U2 reader가 **동일 임베딩 공간**을 소비해야 하는 단일 진실 원천 불변식. (구체 모델/차원 값은 NFR Requirements.)
- **핵심 트레이스**: FR-6, C-1, C-6, RES-2(재구축 가능 자산·RPO=마지막 인제스천·재구축 런북), RES-7, RES-8, RES-9, NFR-C1(비용 텔레메트리/디덥), NFR-R1(부분 인덱싱 금지·fail closed), NFR-O1, SEC-5, SEC-9(공개 스토리지 차단), SEC-15, QT-4/**PBT-08**(디덥 멱등·청크 결정성·결과셋 보존), US-I1/I2/I3.

---

## 2. Functional Design 실행 계획 (Step 2 — 답변 확정 후 수행, 체크박스)

> 아래 산출물은 모두 `aidlc-docs/construction/u1-ingestion/functional-design/` 에 생성한다. **답변(§4·§6) 확정 전에는 생성하지 않는다.**

- [ ] **domain-entities.md** — U1 도메인 엔티티·관계 정의(기술 무관). **잠긴 U1 시그니처(component-methods.md)에 대해 망라적으로 작성**:
  - 파이프라인: `RawDocument`, `ParsedPaper`/`RejectedRecord{reason}`, `ChunkSet`/`Chunk`(chunkId·paperId·section·position), `EmbeddingBatch`(vectors[] aligned to chunkId), `IndexRecord`(인덱스 스키마 + lexical 필드).
  - 디덥/식별: `DedupDecision{NEW|CHANGED|DUPLICATE}`, `ContentFingerprint`(Q6 답에 따라 의미 확정), 식별 값타입 `ArxivId`·`PaperId`·`ChunkId`·`ContentHash`(식별자/버전 규칙 포함).
  - 제어 평면: `IngestionJob`, `JobId`, `ScheduleTrigger`, `NewArxivEvent`/`EventId`, `CategoryFilter`, `PageCursor`, `MetadataPage{records[],nextCursor,hasMore}`, `Watermark`.
  - 쓰기/결과: `WriteResult{written,skipped,failed[]}`, `IndexStats{docCount,vectorCount,lastWrite}`, `Tombstone`/`WithdrawalMarker`(잠긴 `VectorIndexWriter.tombstone` 계약 모델링 — 탐지 범위는 Q13).
  - 실패: `IngestError`, `FailureClass{RETRIABLE|PERMANENT}`, `RetryDecision`, `DLQ Item`/`FailureReason`. 공유 `VectorSpec`(참조).
  - **이 목록은 component-methods.md의 U1 시그니처에 대해 망라적이다**; NFR/Infra로 미루는 사소한 값타입은 명시 표기.
- [ ] **business-logic-model.md** — 서비스 3종 오케스트레이션 + 9 컴포넌트 알고리즘 수준 설계: 시드 빌드(`triggerFullRebuild`, US-I1)·증분 갱신(`onSchedule`, US-I2)·이벤트 경로(범위 §4 Q12) 흐름, 단계별 데이터 변환, 멱등 upsert/tombstone, 워터마크 전진. **제어 평면의 재구축↔증분 동시성 처리(§6 Q16)** 및 **IndexStats 소비 계약**(`U6.HealthCheckService.deepCheck`(RES-6) + RES-2 재구축 완전성 검증 공급; `lastWrite` 전진 시점 정의) 포함.
- [ ] **business-rules.md** — 결정 규칙·검증·제약:
  - OA 배제 규칙(C-1) + **RejectedRecord 사유 분류**{비-OA, 파싱 실패, 검증 위반, 취득 실패} 및 거부율의 RES-7 갱신 실패 경보 연동 여부.
  - dedup/fingerprint 규칙(PBT-08), 청킹 결정성·멱등성 규칙, **과대/빈/손상 본문 처리 정책**(Q2=A면 사실상 N/A — 초록 전용).
  - 워터마크/RPO 규칙(RES-2) + **워터마크 역행 규칙(§6 Q17)**, **논문 단위 원자성**(NFR-R1 부분 인덱싱 금지).
  - **커밋 순서 불변식 INV-1**(§6): index write durable → `markIngested` → `advanceWatermark`; upsert 멱등성으로 replay-safe(크래시 시 다음 실행 재분류·멱등 재upsert).
  - **이벤트 at-least-once 멱등 소비 + `ackEvent` 경계 + 포이즌 이벤트 DLQ**(§6 Q15; Q12=A 스텁이어도 계약 정의).
  - 실패 분류·재시도·백오프·DLQ·경보(US-I3/RES-7/8/9), 레이트/쿼터 준수(RES-8), fail-closed(SEC-15), 입력 검증(SEC-5), 공개 스토리지 차단(SEC-9).
- [ ] **PBT 속성 식별(QT-4 / PBT-08 blocking)** — 테스트 가능 속성 명문화:
  - 디덥 멱등성(**중복 이벤트 재전송 포함**, Q15 답 반영), 청크 결정성(동일 입력→동일 청크/ChunkId).
  - upsert 멱등성, **무손실·무중복**: 주어진 `ParsedPaper`에 대해 `|upserted IndexRecords| == |ChunkSet|`(청크 조용한 누락/중복 0, NFR-R1).
  - **EmbeddingBatch vector↔chunkId 정렬 보존**(embedBatch 출력→upsert 입력 사이 재정렬/누락 0).
  - 워터마크 단조성 — **§6 Q17이 정한 역행 규칙을 참조**(공백 단조성 주장 금지). (프레임워크 선정은 NFR Requirements.)
- [ ] **데모 범위 vs 프로덕션 타깃 경계(표)** — 행: FR-6 슬라이스/주기/규모(Q1) · 본문 깊이(Q2) · 트리거 표면(Q12) · 철회/tombstone(Q13) · 평가셋 코퍼스 보장(Q14) · **OA 전문 보관(Object Storage)/SEC-9**(Q2=A이면 부재 → SEC-9 정당화된 N/A + 재구축은 arXiv 재취득; Q2=B/C이면 보관 + SEC-9 적용 + 재구축 시 재사용).
- [ ] **추적성 매트릭스** — U1 컴포넌트/규칙/속성 → 요구사항 ID 역추적(미커버 0 검증).
- [ ] **공유 계약 정합 주석** — VectorSpec 동일 공간 불변식·단일 writer/단일 reader 경계(기술 무관 수준).

---

## 3. 가정 (명시 — 잘못이면 §4/§6 또는 별도 지적으로 정정 요청)

- **AS-1**: 본 단계는 코드 미생성. 산출물은 설계 문서뿐이며 기술 스택 결정 없음.
- **AS-2**: `SearchExecuted`·근거화 후크·비용 서킷 등 U2/U6 소관은 U1 Functional Design 범위 밖(인덱스 호환 계약만 참조).
- **AS-3**: QT-1(근거화)·QT-2(관련도) 평가셋 **구축**은 U2/U6 Functional Design 산출물이다. U1은 그 평가셋이 동작하도록 **대상 논문을 코퍼스에 포함**시키는 책임만 진다(§4 Q14).
- **AS-4**: 수치형 NFR(P50, $300/월, 재시도 횟수·백오프·동시성 등)의 **정책**은 여기서 정하되 **확정 수치**는 NFR/Infra Design에서 검증·고정.
- **AS-5**: `triggerFullRebuild`는 RES-2 "재구축 가능 자산" 흐름을 정의한다. **운영 재구축 런북(절차·검증·실행자)** 문서화는 Infra/Operations 단계로 보류하되, 본 Functional Design에서 그 진입점·완전성 검증 계약(IndexStats)을 명시한다.

---

## 4. 명확화 질문 (Step 3 — `[Answer]:` 태그로 답변; 미답 시 진행 불가)

> 답변 방법: 각 질문의 `**[Answer]**:` 뒤에 **A/B/C/D** 중 하나(또는 **E = 기타: 직접 기술**)를 적어 주세요. 모든 질문에 **E(기타)** 선택 가능. 모호한 답("상황에 따라", "섞어서" 등)에는 후속 질문을 추가합니다. **§6에 동시성·복구 추가 질문(Q15~Q17)이 있습니다.**

### A. 비즈니스 로직 모델링 · 데이터 흐름 (범위/파이프라인)

**Q1 — 데모 시드 코퍼스 범위 (FR-6 슬라이스).** Sprint 1 데모에서 인덱싱할 arXiv 슬라이스는?
- A) **단일 카테고리 `cs.LG`, 최근 ~1년(수천 건)** — 의미 있는 시맨틱 검색이 가능하면서 비용/시간 경계. (권장)
- B) 제안 5개 카테고리(cs.LG/cs.AI/cs.CL/cs.CV/stat.ML), 최근 1년.
- C) 큐레이션 소형 고정 픽스처(수백 건; QT-1/QT-2 평가셋 논문 포함 보장) — 가장 빠른 데모 부팅.
- D) FR-6 풀 슬라이스(5개·5년·수십만 건) — 프로덕션 타깃(데모엔 과대).
- **권장**: A — 데모가 "실제로 검색되는" 인상을 주면서 비용/인제스천 시간 경계. 단 QT-2 평가셋 질의가 의미 있으려면 코퍼스가 너무 작으면 안 됨(Q14 연동). 프로덕션 타깃 D는 Infra Design에서 확장.
- **[Answer]**: A

**Q2 — 본문 깊이(임베딩 대상 텍스트).** FR-6은 "메타데이터+전문"이나, 데모에서 청크·임베딩 대상 본문은?
- A) **초록(abstract) + 메타데이터만** 임베딩(전문 본문 청킹 제외) — 데모 비용/속도 최적, 카드 표시(FR-4)·근거화(FR-5)에 충분. (권장)
- B) 초록 + 본문 일부 섹션(서론/결론).
- C) OA 전문 전체 청킹 — FR-6 프로덕션 타깃(전문 추출·대량 청킹 부담).
- D) 설정 가능(기본 A, 추후 C로 승급).
- **권장**: A — 본문 전문 추출/대량 청킹을 데모에서 제거하면 ArxivSourceClient.fetchFullText·전문 파싱·**OA 전문 보관(SEC-9 오브젝트 스토리지)이 부재**가 되어 단순화된다. **부수 효과(의식적 수용 필요)**: 전문 보관이 없으면 RES-2 **재구축이 arXiv 재취득에 의존**(저장 원천 재사용 불가). **이 답에 따라 Chunker·FetchParseProcessor·ArxivSourceClient의 데모 범위가 크게 달라짐.**
- **[Answer]**: A
- **[2026-06-18 프로덕션 확정]**: A 유지 — 데모 한정 결정이 아니라 **프로덕션 범위에서도 본문 검색 미도입**(팀 확정). 현 코드 이미 abstract-only(인덱스 저장필드에 본문 없음, lexicalTerms=title+abstract). ⚠️ `shared/vector-spec.md`(🔒 FROZEN)는 `section`(초록/본문)·멀티청크 `chunkId`로 본문 청킹을 *허용*하나 **의도적 미사용** — specVersion 변경(전체 재임베딩) 비용 때문에 스펙은 그대로 둠. U1 writer 구현 시 논문당 ordinal=0 / `section="abstract"` 청크 1개만 방출하도록 강제(인베리언트 테스트 1개). 본문 검색 도입 시 "전문 임베딩 비싸다" 비판 재적용 → 비용 재산정 선행.

### B. 도메인 모델

**Q3 — 논문 식별자·버전(vN) 처리.** 정규 `paperId`와 arXiv 버전 취급은?
- A) **paperId = 버전 없는 arXiv ID(예 `2401.01234`)**; 항상 최신 버전으로 upsert, vN 증가 시 재처리(덮어쓰기). (권장)
- B) paperId = arXiv ID + 버전(`2401.01234v2`); 버전별 별도 레코드.
- C) 버전 무시 — 최초 수집본 고정, 갱신 안 함.
- **권장**: A — 검색 결과 중복(같은 논문 여러 버전) 방지 + dedup/워터마크와 일관(Q6/Q7).
- **[Answer]**: A

**Q4 — 공유 IndexRecord 필드·lexical 필드.** FR-4 카드 필드(제목·저자·연도·arXiv ID·초록 스니펫·관련도·링크) 외 인덱스 레코드에 무엇을 담아 U2에 제공?
- A) **FR-4 카드 필드 + 카테고리 + 버전 + 전체 초록(스니펫 산출용) + lexical 텀(제목+초록 토큰)**. (권장)
- B) FR-4 카드 필드 최소만.
- C) A + 저자 소속·참고문헌 등 확장 메타.
- **권장**: A — FR-2 하이브리드(lexical) 지원 + FR-5 근거화(해소 가능 ID/링크) + FR-4 카드. 확장 메타는 후순위.
- **[Answer]**: A

### C. 비즈니스 규칙

**Q5 — OA 판정 규칙 (C-1).** "오픈액세스/재배포 가능"을 어떻게 판정해 비-OA를 배제?
- A) **가정 A-5에 따라 모든 arXiv 논문을 OA로 취급, 라이선스 미검사**(데모 단순화); 본문 취득 실패 항목만 제외. (권장; Q2=A이면 본문 미취득이라 사실상 배제 0)
- B) arXiv 라이선스 필드 검사 — 재배포 불가/미표기 라이선스 제외.
- C) OA 전문(PDF/소스) 실제 취득 가능 항목만 포함(Q2=C와 정합).
- **권장**: A — Q2=A(초록 전용)와 정합. Q2가 B/C면 본 답을 B/C로 동반 조정 권장. RejectedRecord 사유 체계에 영향.
- **[Answer]**: A

**Q6 — 디덥 지문(fingerprint) 정의 (PBT-08).** NEW/CHANGED/DUPLICATE를 가르는 콘텐츠 지문은?
- A) **arXiv ID + 버전 번호(vN)** — 버전 증가=CHANGED, 동일 버전 재수신=DUPLICATE. (권장)
- B) 정규화 콘텐츠(초록/본문) 해시.
- C) 메타데이터(제목+저자+초록) 해시.
- D) A + 콘텐츠 해시(둘 중 하나라도 변하면 CHANGED).
- **권장**: A — 결정적·저비용·arXiv 버전 시맨틱과 일치(Q3=A 연동). 재임베딩 비용 회피(NFR-C1).
- **명명 주석**: 잠긴 시그니처 `fingerprint(...) -> ContentHash`(components.md "콘텐츠 지문")와의 정합 — A를 택하면 지문이 **콘텐츠 해시가 아니라 ID+버전 키**가 된다. domain-entities.md에서 `ContentFingerprint`를 "ID+버전 파생 키"로 재정의(또는 개념 엔티티명을 `VersionKey`로)하여 문서-구현 드리프트를 방지한다.
- **[Answer]**: A

**Q7 — 증분 워터마크 의미 (US-I2 / RES-2 RPO).** `sinceWatermark`/RPO를 전진시키는 기준 시각은?
- A) **arXiv 최종 수정일(updated)** — 신규 게재 + 기존 논문 개정(vN) 모두 포착. (권장)
- B) arXiv 최초 제출일(submitted) — 신규 게재만.
- C) 인제스천 처리 시각(server-side).
- **권장**: A — Q3/Q6(버전 인지)과 일관, 개정 누락 방지. (역행 처리 규칙은 §6 Q17.)
- **[Answer]**: A

**Q8 — 인덱싱 원자성 단위 (NFR-R1 부분 인덱싱 금지).** 부분/조용한 인덱싱을 막는 원자성 경계는?
- A) **논문 단위 원자성** — 한 논문의 전 청크 임베딩·기록 성공 시에만 `markIngested`; 일부 실패 시 미커밋·재시도 대상(부분 인덱싱 금지). (권장)
- B) 청크 단위(부분 기록 허용 + 부분 상태 표시).
- C) 잡(배치) 단위 원자성(전부 또는 전무).
- **권장**: A — NFR-R1과 정합하면서 한 논문 실패가 잡 전체를 막지 않음(Q11 연동). (Q2=A면 논문당 1청크라 자명.) 커밋 순서는 §6 INV-1.
- **[Answer]**: A

### D. 에러 처리 · 복원력 (US-I3 / RES-7/8/9)

**Q9 — 실패 분류 정책(RETRIABLE vs PERMANENT).**
- A) **RETRIABLE = 네트워크/타임아웃/5xx/429(레이트)**; **PERMANENT = 파싱 실패·검증 위반·비-OA·404**. (권장)
- B) 팀 정의 매트릭스(별도 표 작성 요청).
- C) 전부 고정 횟수 재시도 후 DLQ(분류 단순화).
- **권장**: A — RES-9 의존성 격리 + 영구 실패 조기 DLQ. (PERMANENT의 사유 분류는 business-rules.md RejectedRecord 체계와 정합.)
- **[Answer]**: A

**Q10 — 재시도/백오프/쿼터 자세 (RES-8/9) — 정책만(수치는 Infra 확정).**
- A) **지수 백오프 + 지터 + arXiv 보수적 쿼터 준수(낮은 동시성·요청 간 최소 지연) + 소진 시 DLQ**; 구체 지연/시도 상한은 NFR/Infra에서 고정(AS-4). (권장)
- B) 더 공격적(동시성↑·간격↓).
- C) 정책 포함 전부 Infra Design 보류(여기선 분류만).
- **권장**: A — RES-8 쿼터/RES-9 격리. **정책 형태(shape)만** 확정, 수치는 후속(고도 일관성).
- **[Answer]**: A

**Q11 — DLQ + 갱신 실패 경보 거동 (US-I3 / US-I2 / RES-7).**
- A) **소진 항목 DLQ 격리 + 구조화 실패 신호를 U6 ObservabilityHub로 발행(경보); 잡은 계속 진행(한 논문 실패가 전체를 막지 않음); 잡 단위 실패율 임계 초과 시 갱신 실패 경보**. (권장)
- B) 첫 영구 실패 시 잡 중단.
- C) DLQ만, 경보 없음(데모 단순화).
- **권장**: A — RES-7 인제스천 갱신 실패 경보 + NFR-R1(정체/손상 방지).
- **[Answer]**: A

### E. 비즈니스 시나리오 · 데모 범위

**Q12 — 인제스천 트리거 표면(데모 범위).** DQ3=C는 이벤트(new-arXiv) + 스케줄 경로를 정의. 데모에 포함할 트리거는?
- A) **수동/스케줄만**: `triggerFullRebuild`(시드 빌드 US-I1) + `onSchedule`(증분 US-I2); **NewArxivEventHandler는 인터페이스만 정의·데모 비활성(스텁)**. (권장)
- B) 이벤트 경로까지 완전 구현(내부 new-arXiv 이벤트 발생원 포함).
- C) 시드 빌드(`triggerFullRebuild`)만; 스케줄 갱신도 데모 후순위.
- **권장**: A — 이벤트 버스 인프라 부담을 데모에서 제거하되 인터페이스 보존(설계 무결성 유지). **U1 데모 빌드 분량을 직접 좌우.** (스텁이어도 멱등 계약은 §6 Q15에서 정의.)
- **[Answer]**: A

**Q13 — 철회/대체 tombstone 범위.** arXiv 철회·대체 논문의 `tombstone` 처리?
- A) **인터페이스 정의 + 데모 범위 제외**(철회 탐지 미구현; 재구축 시 자연 정합). (권장)
- B) 갱신 중 철회 탐지·tombstone 구현.
- C) 완전 제외(인터페이스도 후순위).
- **권장**: A — 데모 가치 낮음·재구축으로 정합 가능, 단 계약은 보존(domain-entities.md `Tombstone/WithdrawalMarker`).
- **설계 의도 주석(보류이나 계약 인지)**: 프로덕션 tombstone은 **지연 도착 in-flight upsert와의 순서**가 필요 — tombstone이 우선하되 **엄격히 더 새로운 vN의 upsert가 오면 그것이 우선**.
- **[Answer]**: B

**Q14 — 평가셋 코퍼스 보장 (QT-1/QT-2 연동).** 시드 코퍼스를 QT-1(근거화)·QT-2(관련도) 평가셋 대상 논문이 인덱스에 반드시 포함되도록 큐레이션할까?
- A) **예** — 시드 선정 시 QT-2 기대 논문 + QT-1 in-corpus 질의 대상 논문 포함 보장(평가셋은 U2/U6 산출물이나 U1 코퍼스가 전제). (권장)
- B) 아니오 — 코퍼스 먼저 빌드 후 평가셋을 코퍼스에 맞춰 작성.
- C) 데모에서 평가셋 게이트 비적용.
- **권장**: A — 매직 모먼트(US-H1) + QT 게이트가 데모 코퍼스에서 실제 동작하도록 보장. Q1 범위와 연동(너무 작으면 QT-2 무의미).
- **[Answer]**: A

---

## 5. 결정된 불변식 (질문 아님 — 명백한 정답, 투명성 위해 명시)

- **INV-1 (커밋 순서·크래시 복구, NFR-R1)**: 인제스천 단계 커밋 순서는 **index write durable → `markIngested` → `advanceWatermark`** 다. `upsert` 성공 후 `markIngested` 이전 크래시 시 다음 실행이 NEW/CHANGED로 재분류·재처리하며, 정합은 **upsert 멱등성**으로 보장된다(부분/조용한 인덱싱 금지). business-rules.md에 불변식으로 기재하고 PBT upsert-멱등성 속성이 이 재실행 경로를 커버한다.
  - **이견 시 §6에서 지적**해 주세요(예: 워터마크를 먼저 전진시켜야 하는 사유가 있다면).

---

## 6. 동시성·복구 추가 질문 (적대적 비평 보강 — `[Answer]:` 태그)

**Q15 — NewArxivEventHandler 멱등 경계(중복 이벤트 재전송 시) + 포이즌 이벤트.** *(3개 비평 렌즈 전부가 지적 — 최우선)* Q12=A로 라이브 경로를 스텁하더라도 인터페이스 **계약**은 지금 멱등 의미를 정해야 함(DeduplicationGuard의 DUPLICATE 단락 역할을 규정).
- A) **DeduplicationGuard의 DUPLICATE 판정이 단일 멱등 백스톱**(이벤트는 그대로 `ackEvent`); 포이즌 이벤트는 분류 후 DLQ. (권장)
- B) `eventId` 기준 별도 **이벤트-레벨 dedup** 추가(콘텐츠 디덥과 분리).
- C) 둘 다(이벤트-레벨 + 콘텐츠-레벨 이중 방어).
- **권장**: A — 단일 멱등 권위(콘텐츠 디덥)로 단순; at-least-once 재전송이 재인덱싱·중복을 만들지 않음. 선택된 답을 **PBT-08 디덥 멱등성 속성(재전송 포함)** 에 반영.
- **[Answer]**: A

**Q16 — 전체 재구축 ↔ 증분 갱신 동시성(단일 writer 경합).** `triggerFullRebuild`(US-I1, 워터마크 리셋 후 전체 재인제스천)와 `onSchedule` 증분(US-I2)이 **동일 단일 writer 인덱스**에 동시 진입할 때? (제어 평면 결정 — 인프라 아님; 미정 시 증분이 재구축 미완 레코드를 지나 워터마크를 전진시켜 RES-2 RPO를 조용히 손상·NFR-R1 위반.)
- A) **상호 배제** — 재구축 중 증분 보류/거부. (권장)
- B) 단일 활성 잡 락(RefreshOrchestrationService가 잡 직렬화).
- C) 데모는 동시 트리거 없음 가정 — 인터페이스만 보존(규칙 미구현).
- **권장**: A — 명시적 상호 배제가 RPO 손상을 원천 차단. C는 데모 최소이나 위험을 가정에 의존(권장 A). business-rules.md(워터마크+단일 writer) + business-logic-model.md(제어 평면)에 반영.
- **[Answer]**:A

**Q17 — 워터마크 역행(regression) 강제 규칙 (RES-2 RPO).** `advanceWatermark(jobId, watermark)`가 잡별 타임스탬프를 받으므로 지연/순서 역전 잡(및 재구축 리셋)이 워터마크를 뒤로 움직이려 할 수 있음 — 규칙이 있어야 "단조성"이 의미를 가짐.
- A) **max-clamp**(역행 시도 무시, 항상 최대값 유지). (권장)
- B) 역행 거부 + 경보(이상 신호로 표면화).
- C) 전체 재구축만 리셋 허용(증분은 전진만).
- **권장**: A — 단순·안전; 단 재구축 리셋(Q16과 연동)은 의도된 예외로 별도 경로 허용. PBT-08 워터마크-단조성 속성을 **이 규칙을 참조**하도록 기술.
- **[Answer]**: A

---

## 사후 결정 — Construction 이후 (`[Answer]` 태그)

**Q18 — 전문 추출 소스·형식 (2026-06-23; #139).** Q2 재스코핑으로 전문 취득·S3 보관이 활성됐으나 *추출 방식*은 미설계였다. 코드는 arXiv e-print(gzip/tar/LaTeX)를 **미해제 디코딩**해 본문 ~44%가 깨진 문자(�)로 저장됨(실측 `1706.03762`). 전문을 어떻게 추출·보관하나?
- A) e-print(LaTeX) 해제 + `.tex` 병합 — 의존성 0이나 마크업 잔존.
- B) PDF 텍스트 추출(`pdfplumber`) — 렌더 근접.
- C) PDF 우선 + e-print 폴백.
- D) **arXiv HTML(native→ar5iv) 우선 + PDF 폴백** — HTML이 가장 깨끗한 평문 소스.
- **[Answer]**: **D** — 보관·소비는 **정규화 평문 1종**(`.txt`); 뷰어는 평문 렌더(앵커 유지). 리치 HTML 렌더/보관은 에셋 패널(FR-17)과 그림·표가 겹쳐 **에이전트 단계로 분리**(예방적 보관 회피, 원칙1). `pdfplumber` 코어 승격. **산출**: BR-29 · `full_text_extraction.py` · 커밋 `0ced380`.

---

## 7. 다음 절차

1. 팀이 `§4`·`§6`의 `[Answer]:` 태그를 채운다(또는 채팅으로 A/B/C/D/E 회신). `§5` INV-1은 이견 시에만 지적.
2. 모호 답변 발견 시 후속 명확화 질문 추가(규칙 Step 5).
3. 답변 확정 → `§2` 산출물 생성(domain-entities.md / business-logic-model.md / business-rules.md + PBT 속성).
4. 완료 메시지 + 리뷰 게이트 → 승인 시 다음 단계(**NFR Requirements** — 기술 스택 선정).

> 본 계획·질문은 **리뷰 게이트**입니다. 답변 전까지 Functional Design 산출물을 생성하지 않으며, 아직 커밋하지 않았습니다.
