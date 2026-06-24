# business-rules.md — U1 Ingestion 비즈니스 규칙·속성·추적성 (프로덕션)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U1 Ingestion · **일자**: 2026-06-16
**근거**: 계획서(프로덕션 재스코핑) — Q1=D·**Q2=B(제목+초록만 인덱싱, issue #120 결정 2026-06-18)**·Q12=B·Q13=B·그 외 A · `requirements.md`.
**원칙**: 기술 무관 결정·검증·제약. 수치(백오프·동시성·타임아웃)는 정책+NFR Requirements 확정값(Q14).
**프로덕션 스코프**: **초록 단일 청크(논문당 1벡터)**·이벤트 경로·철회 tombstone·전문 오브젝트 보관 활성.

---

## 1. 비즈니스 규칙 (BR)

| ID | 규칙 | 근거/답 |
|---|---|---|
| **BR-1 (엄격 OA 라이선스 검증)** | **팀 결정(2026-06-16): 엄격 OA 라이선스 검증.** 각 논문의 arXiv 라이선스를 검사해 **재배포 가능 라이선스만**(예 CC-BY/CC-BY-SA/CC0) 수집·전문 보관·인덱싱; **재배포 불가·미표기·불명(예 arXiv 비독점 라이선스) → NON_OA 배제**. 취득 실패도 제외. (Q5 A→엄격 검증 확정; A-5 가정 강화; 커버리지보다 정합 우선.) | C-1, A-5, **Q5=엄격** |
| **BR-2 (콘텐츠 범위)** | **제목+초록만 임베딩·인덱싱**(Q2=B, issue #120). 전문은 수집·S3 보관(BR-20, U7 요약 용도)하되 **벡터 인덱스 대상이 아님**. | FR-6, **Q2=B** |
| **BR-3 (논문 식별·버전)** | `PaperId=버전 없는 arXiv ID`. 최신 vN만 인덱스(latest-wins). NEW/CHANGED/DUPLICATE 의미(Q3=A). | Q3=A |
| **BR-4 (디덥 지문)** | `ContentFingerprint=PaperId+PaperVersion` 파생(콘텐츠 해시 아님). 동일 지문 재수신→DUPLICATE 단락(재임베딩 0). | NFR-C1, PBT-08, Q6=A |
| **BR-5 (청킹 결정성·전략)** | **논문당 단일 청크(초록 전문)**; `chunk`·`chunkId` 결정적·멱등(동일 입력→동일 ChunkSet/ChunkId). | FR-6, QT-4, PBT-08, **Q2=B** |
| **BR-6 (IndexRecord 구성)** | 논문당 1 레코드 = 카드 필드(FR-4) + category + version + section("abstract") + abstract + lexicalTerms(**제목+초록** 토큰만). 해소 가능 arXiv ID/링크 필수(FR-5). | FR-2/4/5, Q4=A |
| **BR-7 (논문 단위 원자성)** | 한 논문의 **단일 청크(초록)** 임베딩·기록 성공 시에만 커밋(markIngested). 실패=미커밋·재시도. **부분/조용한 인덱싱 금지.** | NFR-R1, **Q8=A** |
| **BR-8 (커밋 순서 INV-1)** | **index write durable → markIngested → advanceWatermark**. upsert 후 markIngested 전 크래시→재분류·멱등 재upsert. | NFR-R1, INV-1 |
| **BR-9 (멱등 upsert)** | upsert는 ChunkId 키 멱등(재실행·재전송이 중복 레코드 0). CHANGED는 덮어쓰기. | QT-4, PBT-08, Q3=A |
| **BR-10 (워터마크·RPO)** | 기준 시각=arXiv updated. RPO=마지막 인제스천(RES-2, 별도 백업 없음). | RES-2, Q7=A |
| **BR-11 (워터마크 역행)** | max-clamp(전진만, 역행 무시). 예외: SEED_REBUILD만 의도적 리셋(BR-13 보호). | RES-2, Q17=A |
| **BR-12 (이벤트 멱등·포이즌)** | 이벤트 at-least-once 소비(**Q12=B 활성**). 멱등=DeduplicationGuard DUPLICATE 단일 백스톱(이벤트-레벨 dedup 없음). 처리 후 ackEvent. 포이즌→DLQ. | RES-7, **Q15=A, Q12=B** |
| **BR-13 (재구축↔증분/이벤트 상호배제)** | 단일 writer 보호: SEED_REBUILD 활성 중 INCREMENTAL·EVENT 보류/거부(REBUILD_LOCK). | NFR-R1, RES-2, **Q16=A** |
| **BR-14 (철회·tombstone · 버전 단조 순서)** | **Q13=B 활성**: 철회 탐지(메타+전문 withdrawal 공지) → tombstone(전 청크); INV-1 순서. **순서 규칙 = highest-vN-wins, 제어평면 `current_version`(paperId별)에 대한 원자적 compare-and-set로 강제**(— `isNew`는 인서트 스킵 판정일 뿐 **삭제 가드가 아님**): **upsert(vN)**는 `vN ≥ current_version`일 때만 적용(→ current_version:=vN, INDEXED); **tombstone(vW)**는 `vW ≥ current_version`일 때만 적용(→ current_version:=vW, TOMBSTONED), **`current_version > vW`면 삭제 무시**(strictly-newer-vN-wins). 원자적이라 {철회 vW·인서트 vN} **도착 순서 무관**하게 최고 버전 성격으로 수렴(v2 삭제·v3 인서트 경쟁 시 v3 생존). 재구축 시 능동 재탐지. | **Q13=B** |
| **BR-15 (실패 분류)** | RETRIABLE=네트워크/타임아웃/5xx/429; PERMANENT=파싱·검증·비-OA·404. (전문 취득·임베딩·쓰기 실패 포함.) | RES-9, Q9=A |
| **BR-16 (재시도·쿼터)** | 지수 백오프+지터, arXiv 보수 쿼터(RES-8), 소진→DLQ. **수치는 NFR Q14 확정.** | RES-8/9, Q10=A |
| **BR-17 (DLQ·경보)** | 소진/영구→DLQ 격리 + 구조화 실패 신호 U6.ObservabilityHub. 잡 계속; 실패율 임계 초과→갱신 실패 경보. | RES-7, NFR-O1, NFR-R1, Q11=A |
| **BR-18 (fail-closed)** | 모든 외부 호출(arXiv/오브젝트 스토리지/임베딩 게이트웨이/벡터 스토어) 타임아웃·서킷; 실패 fail closed. | SEC-15, RES-9, NFR-R1 |
| **BR-19 (입력 검증)** | 파싱 산출 필수 필드·형식 검증·새니타이즈. | SEC-5 |
| **BR-20 (전문 보관·공개 차단)** | **Q2=C 활성**: OA 전문 원천을 오브젝트 스토리지 보관(StoredFullText/ObjectRef), **공개 차단(SEC-9)**, 재구축·재처리 재사용. at-rest 암호화/TLS(SEC-1, NFR Q17). | **SEC-9**, SEC-1, RES-2 |
| **BR-21 (본문 크기 정책)** | **Q2=B**: 인덱싱 대상=초록만이므로 본문 크기가 벡터 비용에 영향 없음. 전문은 S3 보관만(BR-20) — 과대 전문 취득 제한은 S3 스토리지 비용 관점에서만 적용. | FR-6, NFR-C1 |
| **BR-29 (전문 추출 소스·형식)** | **결정 D 활성**(FD plan `사후 결정` Q18=D; #139 근원=추출 소스·형식 미설계). 전문은 **arXiv HTML 우선(native → ar5iv) → PDF 폴백**으로 취득한다 — HTML은 *가장 깨끗한 평문을 뽑는 소스*, PDF는 폴백(커버리지 스파이크: native 단독 34%·ar5iv 포함 90% → **ar5iv 필수**, HTML 전무 ~9%는 PDF 폴백 실필요). **보관=정규화 평문(`.txt`)** — **인덱스 청킹·검색 투영용으로 유지**(인덱싱 권위; Q4: doc-model=진실원천, `.txt`=파생 평문). **e-print(LaTeX) 미해제 디코딩 금지** — gzip/tar 페이로드를 텍스트로 디코딩하지 않음(`arxiv.py:73` 결함 제거); 단 doc-model 폴백 단계에서 *해제 후* LaTeX 파싱은 허용(BR-30, Q6 폴백 사다리). HTML 부재는 폴백(거부 아님); 추출·평문화 실패는 BR-15 분류(PARSE/FETCH). **피벗(doc-model)**: 수식·표·그림의 리치 렌더/보관은 더 이상 범위 밖이 아님 — **doc-model로 구조화**(BR-30)하고 자체 리치뷰가 렌더(D4). 앵커 하이라이트 계약 유지(BR-SF). on-demand 비전은 에이전트 단계(D5). | **D**, Q4, Q6, SEC-5, BR-15/19/20/30 |
| **BR-30 (doc-model 구조·생성, 피벗 2026-06-23)** | **결정 D1·D2·D6 활성**(SSOT=`construction/plans/docmodel-foundation-pivot-plan.md`). doc-model = arXiv HTML **결정적 파싱 → JSON**(`doc-model/{paperId}/v{ver}.json`): 섹션/블록·앵커 · **표=구조화 데이터(rows/cols)** · **수식=LaTeX(MathML 변환)** · **그림/표이미지=webp `assetId` 참조**(픽셀·메타는 §6/FR-17 산출물 재사용 — **재추출 0**). **LLM 추출 금지**(표 숫자 환각 방지) — 결정적 파서만, 동일 HTML→동일 doc-model(P7). **생성=lazy on-demand + `(paperId, version)` 캐시**(D6): 첫 요약/열람/에이전트 사용 시 생성, version 변경 시 무효화(Q5); `ingestOne` eager 아님(인덱스 hot path 비차단). 생성 폴백 사다리=`native HTML → ar5iv → e-print LaTeX → (최후) PDF 파싱`(Q6). 알고리즘은 BLM §7. | **D1/D2/D6**, Q4/Q5/Q6, BR-29, FR-17 |

---

## 2. RejectedRecord 사유 분류

| RejectReason | 의미 | FailureClass |
|---|---|---|
| `NON_OA` | 비-OA/재배포 불가 라이선스(BR-1 프로덕션 검증) | PERMANENT |
| `PARSE_FAILURE` | 메타/전문 파싱 불가 | PERMANENT |
| `VALIDATION_VIOLATION` | 필수 필드/형식 위반(SEC-5) | PERMANENT |
| `FETCH_FAILURE` | 원천/전문 취득 실패 | RETRIABLE→소진 시 DLQ |

> 거부율(PARSE/VALIDATION 급증)은 BR-17 잡 실패율 경보 보조 신호(RES-7).

---

## 3. PBT 속성 (QT-4 / PBT-08 blocking)

| 속성 | 진술 | 트레이스 |
|---|---|---|
| **P1 디덥 멱등성** | isNew 결정적·입력 의존; 동일 이벤트/논문 재전송이 추가 인덱싱·중복 0(Q15=A). | PBT-08, BR-4/9/12 |
| **P2 청크 결정성** | 동일 ParsedPaper → 동일 ChunkSet·동일 ChunkId(초록 단일 청크, 결정적). | PBT-08, BR-5 |
| **P3 upsert 멱등성** | 동일 IndexRecordBatch 재upsert가 인덱스 상태 불변; CHANGED는 덮어쓰기. | PBT-08, BR-8/9 |
| **P4 무손실·무중복** | 주어진 ParsedPaper에 대해 `|upserted IndexRecords| == 1`(논문당 1벡터, 누락/중복 0). | NFR-R1, BR-7 |
| **P5 임베딩 정렬 보존** | `EmbeddingBatch.vectors[i] ↔ chunks[i].chunkId`(재정렬/누락 0). | NFR-R1, BR-7 |
| **P6 워터마크 단조성** | advanceWatermark는 BR-11 max-clamp(전진만); SEED_REBUILD 리셋만 예외. | RES-2, BR-11 |

> 프레임워크는 NFR Requirements(Q8=A Hypothesis)·도메인 제너레이터·shrinking·시드 재현성. P1/P3/P4/P5=PBT-08 차단성, P2=청크 결정성, P6=RES-2 정합.

---

## 4. 프로덕션 스코프 (데모 트랙 폐기 — 단일 트랙)

| 축 | 프로덕션 결정 | 비고 |
|---|---|---|
| 코퍼스 슬라이스 | cs.LG/cs.AI/cs.CL/cs.CV/stat.ML × 5년(수십만)(Q1=D) | FR-6 풀 슬라이스 |
| 본문 깊이 | **제목+초록만 인덱싱(Q2=B, issue #120)** | 전문은 S3 보관만(BR-20); 벡터 인덱스 대상 아님 |
| 트리거 표면 | 수동 rebuild + 스케줄 증분 + **new-arXiv 이벤트 활성**(Q12=B) | 3경로 |
| 철회/tombstone | 탐지·tombstone 활성(Q13=B) | 메타+전문 신호(BR-14) |
| 평가셋 코퍼스 | QT-1/QT-2 대상 논문 포함 보장(Q14=A FD) | U2/U6 FD가 평가셋 구축 |
| OA 전문 보관/SEC-9 | **활성** — 오브젝트 스토리지 보관·공개 차단(BR-20) | 재구축 재사용 |
| 임베딩 모델/VectorSpec | **NFR Requirements(TD-3) 확정** | 시스템 전역 불변식(U1 writer=U2 reader 동일 공간) |
| 벡터+lexical 스토어 | **NFR Requirements(TD-4) 확정** | ANN+BM25 lexical+per-paperId 삭제 요건(BR-14) |
| NFR-C1 비용 상한 | **NFR Requirements 확정**(시스템 전역) | U6.CostGuardCircuitBreaker 강제; 디덥(BR-4)/본문 크기(BR-21) 통제 |

---

## 5. 추적성 매트릭스 (요구사항 → 규칙/속성/엔티티)

| 요구사항 | 랜딩 |
|---|---|
| **FR-6**(인제스천·인덱싱·갱신) | BR-2/5/6, IngestionPipelineService, RefreshOrchestrationService |
| **C-1**(OA 전용) | BR-1(OA 배제·라이선스), RejectReason(NON_OA) |
| **C-6**(AI/ML 전용) | CategoryFilter / resolveSliceCategories(5 카테고리, Q1=D) |
| **RES-2**(재구축 자산·RPO·런북) | BR-10/11/13, IndexStats, AS-5, BR-20(전문 재사용) |
| **RES-7**(갱신 실패 경보) | BR-17, RejectReason 거부율 |
| **RES-8**(쿼터 인지) | BR-16, ArxivSourceClient(증분+대량 하베스트) |
| **RES-9**(타임아웃·서킷·저하) | BR-15/16/18, IngestionResilienceService |
| **NFR-C1**(비용·디덥) | BR-4(DUPLICATE), BR-21(본문 크기), EmbeddingGatewayAdapter 텔레메트리; **상한=NFR Requirements 확정·시스템 전역(U6.CostGuardCircuitBreaker 강제)** |
| **NFR-R1**(부분/조용한 인덱싱 금지) | BR-7/8/13/17/18, P4/P5 |
| **NFR-O1**(관측성) | BR-17, IndexStats |
| **SEC-1 / SEC-5 / SEC-9 / SEC-15** | BR-20(at-rest/TLS) / BR-19 / BR-20(공개 차단) / BR-18 |
| **QT-4 / PBT-08** | P1~P6 |
| **US-I1**(시드 빌드) | triggerFullRebuild(대량 하베스트), BR-13 |
| **US-I2**(스케줄 갱신) | onScheduleTick, BR-10/17 |
| **US-I3**(복원력) | BR-15/16/17/18, IngestionResilienceService |
| **Q12=B**(이벤트 경로) | NewArxivEventHandler, BR-12, EVENT 잡 |
| **Q13=B**(철회) | BR-14, Tombstone, WithdrawalMarker |
| **미커버 검증** | 위 표로 U1 트레이스 0 미커버; backing US-H1/US-D2는 공유 인덱스 존재로 충족 |

---

## 6. 공유 계약 정합 주석 (VectorSpec)

- U1.EmbeddingGatewayAdapter(writer)·U2.QueryUnderstandingExpander(reader)는 **동일 VectorSpec(차원·모델·거리 — NFR Requirements PIN)**. 동일 임베딩 공간 불변식.
- 계약 산출물 소유=공유 임베딩 게이트웨이 레이어(UQ5=A); U1(빌드 #1)이 값을 PIN, 후속 유닛 재결정 없음(NS-5). 선택 스토어 ANN 인덱스가 PIN된 차원·거리 메트릭 지원 확인(ANN 호환 게이트).
- 단일 writer(U1)/단일 reader(U2) 경계.

---

## 7. 멀티모달 자산 규칙 (FR-17 — 표시 전용, 2026-06-22 확장)

> **근거**: `requirements.md` FR-17 · FD 계획 Q1~Q7=A(Q2=C 혼합). **표시 전용** — §3 인덱싱/임베딩 경로·BR-5~9·VectorSpec **불변**(자산은 검색 비대상, `IndexRecord` 미포함).

### 7.1 비즈니스 규칙 (BR)

| ID | 규칙 | 근거/답 |
|---|---|---|
| **BR-22 (자산 추출 위치·dedup 게이팅)** | 그림·도표 자산은 `parse`에서 디스커버리하되 **저장은 dedup 이후 NEW\|CHANGED만**. DUPLICATE는 자산 재추출·재저장 **0**(재임베딩 0과 동일 비용 정신). | Q1=A, NFR-C1 |
| **BR-23 (혼합 추출·소스 판정)** | **Q2=C**: arXiv e-print(LaTeX) 가용·추출 성공 시 `structured`, 없거나 실패 시 **PDF 페이지 크롭 `page-crop` 폴백**. `sourceMode`로 경로 기록(품질·관측). 추출 라이브러리·bbox 임계·이미지 포맷/해상도는 NFR. | Q2=C |
| **BR-24 (실재 자산만 — 생성 금지)** | 상세/뷰어에 표시되는 자산은 **원문에서 추출된 실재 자산만**. 생성·합성·보정 이미지 금지(FR-5 날조 금지 정신의 표시 측 대응). 추출 불가=해당 자산 미표시(빈 자산 위조 금지). | FR-5, FR-17 |
| **BR-25 (캡션 비중복·앵커 좌표)** | 캡션은 본문 보존분을 참조(중복 추출 안 함). 자산은 `sectionRef`+`ordinal`로 위치 좌표를 가져 앵커(`AnchorVM.target=figure\|table`)가 자산에 매칭된다(표시 측 연동, U7/U5). | 인셉션 Q5, FR-12 |
| **BR-26 (OA 게이트 재사용·비공개)** | 자산 저장·노출은 전문과 **동일 OA 라이선스 게이트(BR-1)**. 비-OA 논문은 자산 미저장·미노출. 자산 바이너리는 오브젝트 스토리지 **공개 차단(SEC-9)**, 노출은 단기 만료 서명 URL(읽기 측 정책, U7). | BR-1, SEC-9, C-1 |
| **BR-27 (자산 best-effort·비차단)** | **Q4=A**: 자산 추출·저장 실패는 **논문 인덱싱(INV-1 원자 커밋)·markIngested·워터마크 전진을 차단하지 않는다**. 실패는 `ASSET_EXTRACT_FAILURE`/`ASSET_STORE_FAILURE`로 관측·재시도(BR-17 경로). 검색 정합은 인덱스가 권위, 자산은 표시 보조. | Q4=A, NFR-R1(인덱스 측만) |
| **BR-28 (자산 멱등·정리)** | `assetId(paperId,version,type,ordinal)` 결정적 → 재처리 멱등(중복 0). **CHANGED(vN↑)**: 이전 버전 stale 자산 교체/정리(`replace_assets`). **tombstone(철회)**: 자산·매니페스트 제거(`remove_assets`). 매니페스트↔저장 자산 정합(고아·누락 0). | Q3=A, Q4=A, BR-14 |

### 7.2 PBT 속성 (추가)

| 속성 | 진술 | 트레이스 |
|---|---|---|
| **P7 자산 추출 결정성** | 동일 `raw/ParsedPaper` → 동일 자산 집합·동일 `assetId`(순서·type별 ordinal 안정). | BR-22/28, 인셉션 Q3 |
| **P8 매니페스트↔자산 정합** | `AssetManifest.assets`와 실제 저장 자산이 1:1(고아·누락 0); CHANGED 교체·tombstone 제거 후에도 정합. | BR-28 |

### 7.3 FailureReason 추가

`ASSET_EXTRACT_FAILURE` · `ASSET_STORE_FAILURE` — **둘 다 비차단(BR-27)**: 논문은 인덱싱 성공으로 커밋되며, 자산 실패만 관측·재시도. (RejectReason과 달리 논문 거부 아님.)

### 7.4 추적성 (추가)

| 요구사항 | 랜딩 |
|---|---|
| **FR-17**(그림·도표 자산 추출·표시) | BR-22~28, §6 AssetExtractor/AssetStorePort, FigureTableAsset/AssetManifest |
| **Q2=C**(혼합 추출) | BR-23, AssetSourceMode |
| **Q4=A**(자산 best-effort) | BR-27, §6.1 분리 커밋 경계 |
| **Q6=A**(매니페스트 RDS) | AssetManifest 영속(S3 바이너리 + RDS 메타) |
| **BR-1/SEC-9 재사용** | BR-26(OA 게이트·공개 차단) |
| **FR-5**(날조 금지) 표시 측 | BR-24(실재 자산만) |

> **범위 경계**: 읽기 측 계약 필드·서명 URL 발급·U5 렌더는 본 U1 FD 밖(공유계약·U7·U5 단계). U1은 **생산자**(추출·저장·매니페스트). 비전 LLM 추론은 차기 사이클(범위 밖).
