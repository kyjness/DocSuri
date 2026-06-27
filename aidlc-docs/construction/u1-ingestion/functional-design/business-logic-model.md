# business-logic-model.md — U1 Ingestion 비즈니스 로직 모델 (프로덕션)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U1 Ingestion · **일자**: 2026-06-16
**근거**: 계획서(프로덕션 재스코핑) — Q1=D·Q2=C·Q12=B·Q13=B·그 외 A.
**원칙**: 기술 무관 알고리즘 수준. 타임아웃·동시성 수치·큐/스토어 구현은 NFR/Infra.
**프로덕션 스코프**: 전문 수집·다중 청크·이벤트 경로·철회 tombstone·전문 오브젝트 보관 전부 활성.
**U1 Corpus 개정(2026-06-26)**: 재인셉션 D6/FR-6에 따라 phase-1 Corpus 논문은 **수집 시점 eager DocModel 생성 + DocModel Block 기반 인덱싱**으로 전환한다. 기존 2026-06-23 lazy/on-demand DocModel 결정은 누락분·재빌드·백필·phase-1 밖 논문 보강 경로로만 남는다.

---

## 0. U1 Corpus 우선 적용 로직 (2026-06-26)

> **우선순위**: 본 섹션은 U1 Corpus Functional Design의 최신 권위다. 아래 §1~§7의 arXiv-only, single-watermark, lazy DocModel, `Chunker.chunk(parsed)` 설명과 충돌하면 본 섹션이 우선한다. 기존 섹션은 과거 결정 추적을 위해 유지한다.

### 0.1 Source별 incremental loop

```
runSourceIncrement(sourceName):
  watermark <- CorpusRefreshScheduler.loadSourceWatermark(sourceName)
  job <- CorpusRefreshScheduler.createJob(INCREMENTAL, sourceName, watermark)

  for page in CorpusSourceAdapterSet.fetchMetadataPage(sourceName, watermark):
    for sourceRecord in page.records:
      processSourceRecord(sourceRecord, job)

    if page durable and all accepted items committed or routed to retry/DLQ:
      CorpusRefreshScheduler.advanceWatermark(sourceName, page.highWatermark)
```

- `SourceWatermark`는 source별로만 전진한다. arXiv 실패가 Semantic Scholar/OpenAlex watermark를 막지 않고, 반대도 동일하다.
- watermark 전진은 해당 page의 accepted item이 durable commit, retry, 또는 DLQ 중 하나로 명시 상태를 갖춘 뒤에만 가능하다.
- phase-1 seed/backfill은 같은 loop를 쓰되 `kind=PHASE1_SEED` 또는 `BACKFILL`로 표시하고 비용 게이트가 우선순위를 결정한다.

### 0.2 논문 후보 처리

```
processSourceRecord(sourceRecord, job):
  candidate <- CorpusSourceAdapterSet.fetchFullTextCandidate(sourceRecord)
  licenseDecision <- FullTextExtractionProcessor.validateLicense(sourceRecord, candidate)
    if not allowed: routePermanent(NON_OA_OR_NOT_ALLOWED); return

  fullText <- FullTextExtractionProcessor.extractFullText(candidate)
    # arXiv: HTML first, PDF fallback
    # Semantic Scholar/OpenAlex: PDF -> GROBID, raw PDF transient only

  normalized <- FullTextExtractionProcessor.normalizeSource(sourceRecord, fullText)
  canonical <- SourcePriorityDeduplicationGuard.canonicalize(normalized)
  dedupDecision <- SourcePriorityDeduplicationGuard.deduplicate(canonical)

  if dedupDecision == LOSING_DUPLICATE:
    storeSourceProvenance(canonical)
    return SKIPPED_DUPLICATE

  if dedupDecision in {NEW, CHANGED, BETTER_SOURCE_FOR_SAME_VERSION}:
    ingestCanonicalPaper(canonical, job)
```

- dedup key 순서: DOI -> arXiv id -> normalized(title + first author + year).
- 승자 규칙: source priority(arXiv > Semantic Scholar > OpenAlex)를 기본으로 하되, 같은 canonical paper에서 더 완성도 높은 FullText/DocModel 후보는 provenance와 quality signal로 보존한다.
- losing duplicate는 embedding/index를 만들지 않는다. 단, provenance는 남겨 재현성과 추적성을 보장한다.

### 0.3 Canonical paper commit pipeline

```
ingestCanonicalPaper(canonical, job):
  paperId, version <- canonical.paperId, canonical.version

  fullTextRef <- CorpusArtifactStore.putFullText(canonical.fullText)
  docModel <- DocModelBuildCoordinator.buildDocModel(canonical.fullText, canonical.provenance)
  DocModelBuildCoordinator.validateDocModel(docModel)
  docModelRef <- DocModelBuildCoordinator.storeDocModel(docModel)

  chunks <- DocModelBlockChunker.chunkDocModel(docModel)
  assert every chunk.blockRef exists in docModel

  embeddings <- EmbeddingGatewayAdapter.embedBatch(chunks)
  generation <- CorpusIndexWriter.prepareGeneration(vectorSpec=v2, docModelSchema=docModel.schemaVersion)
  records <- assembleCorpusIndexRecords(generation, canonical, chunks, embeddings, docModelRef)

  writeResult <- CorpusIndexWriter.upsert(generation, records)
    if writeResult partial/fail:
      IngestionResilienceService.handle(error, stage=INDEX_WRITE)
      return RETRY_OR_DLQ

  SourcePriorityDeduplicationGuard.markCommitted(paperId, version, canonical.fingerprint)
  CorpusArtifactStore.putGenerationManifest(paperId, version, generation, fullTextRef, docModelRef)
  CorpusRefreshScheduler.markItemCommitted(job, paperId, version)
```

- commit 단위는 `(paperId, version)`이다. FullText, DocModel, chunks, index records, S3 object refs가 같은 version을 가져야 한다.
- DocModel validation 실패는 index write 전에 차단한다. 스키마 roundtrip과 negative validation은 QT-9에 포함한다.
- `CorpusIndexWriter.upsert`는 generation 내부에만 기록한다. alias cutover는 별도 gate(0.5)에서 수행한다.
- 기존 `StoredFullText(.txt)`는 검색 투영/재처리 보조 artifact로 남길 수 있으나, 인덱싱 권위는 DocModel Block이다.

### 0.4 Retry, DLQ, reprocess

```
handleCorpusFailure(error, jobItem):
  failure <- IngestFailureHandler.classify(error)
  ObservabilityHub.emitMetric("u1.corpus.stage_failure", tags=failure.tags)
  ObservabilityHub.emitLog("u1.corpus.failure", payload=failure.redactedPayload)

  if failure.retriable and attempts remain:
    scheduleRetry(jobItem, backoffWithJitter, sourceQuotaAware)
  else:
    sendToDLQ(jobItem, failure)

reprocessDLQ(dlqItem):
  job <- CorpusRefreshScheduler.createJob(REPROCESS_DLQ, dlqItem.sourceName)
  processSourceRecord(dlqItem.sourceRecord, job)
```

- retry/DLQ는 source, GROBID, DocModel validation, embedding, index write 단계별로 stage를 보존한다.
- reprocess는 원래 pipeline을 다시 타며 dedup/upsert/idempotency 규칙으로 중복을 만들지 않는다.
- 실패 신호는 U1 내부 `emitFailureSignal` 이름을 쓰더라도 실제 포트 호출은 `ObservabilityHub.emitMetric`/`emitLog`다.

### 0.5 Index generation과 alias cutover

```
cutoverCorpusGeneration(generation):
  require QT-9 invariants pass
  require sample search and summary/docModel read smoke pass
  require generation.indexStats within expected phase-1 bounds

  CorpusIndexWriter.switchAlias(generation.indexAlias, generation.id)
  CorpusIndexWriter.markGenerationActive(generation.id)
```

- OpenSearch alias는 DocModel 기반 generation 검증 후에만 전환한다.
- 이전 full-text 기반 index generation은 rollback window 동안 보존한다.
- partial generation은 검색에 노출하지 않는다.

### 0.6 Lazy build의 남은 역할

Lazy/on-demand DocModel build는 U1 phase-1 Corpus의 기본 경로가 아니다. 다음에만 허용한다.

- phase-1 이전 데이터에서 DocModel이 누락된 논문 보강.
- parserVersion/schemaVersion 변경 후 선택적 rebuild/backfill.
- phase-1 범위 밖 논문의 리치뷰/요약 요청.
- 장애로 eager build가 DLQ 처리된 item의 reprocess.

이 경우에도 저장 키와 index/read 계약은 `(paperId, version)`을 따른다.

---

## 1. 서비스 오케스트레이션 (3종, 이벤트/스케줄 백본)

### 1.1 IngestionPipelineService — 논문 단위 end-to-end (FR-6, US-I1, NFR-R1, NFR-C1)
**논문 단위 원자성(Q8=A) + 커밋 순서 INV-1.** Q2=C로 전문 취득·다중 청크 활성.

```
ingestOne(record, job):
  1. raw ← ArxivSourceClient.fetchFullText(arxivId)                  # Q2=C 전문 취득 · BR-29: HTML 우선(native→ar5iv)→PDF 폴백; raw.text=정규화 평문(인덱스 입력). 동일 HTML 소스가 doc-model 입력(§7)
  2. parsed | rejected ← FetchParseProcessor.parse(raw)              # 메타+전문 본문 정규화
       rejected → IngestionResilienceService.handle(PERMANENT, reason)
  3. validation ← FetchParseProcessor.validate(parsed)              # SEC-5 필수필드/형식
       violation → handle(PERMANENT, VALIDATION_VIOLATION)
  4. (Q13=B) if 철회 신호 탐지(메타 + 전문 withdrawal 공지) → WithdrawalMarker
       → VectorIndexWriter.tombstone(paperId) → markIngested(paperId+vN) → advanceWatermark → return TOMBSTONED   # INV-1; §2 순서 규칙
  5. decision ← DeduplicationGuard.isNew(parsed)                    # Q6=A paperId+version
       DUPLICATE → return SKIPPED (단락, 재임베딩 0 — NFR-C1)
       NEW | CHANGED → 계속
  6. (Q2=C) 전문 원천 보관: StoredFullText(objectRef) ← ObjectStorage.put(raw)   # SEC-9 공개 차단, 재구축 재사용 · BR-29: 정규화 평문(.txt) — 인덱스 청킹·검색 투영용 유지(Q4: doc-model 진실원천, .txt는 파생 평문). doc-model은 여기서 eager 생성 안 함(§7 lazy)
  7. chunkSet ← Chunker.chunk(parsed)                               # 섹션 인지 다중 청크, 결정적
  8. embeddings ← EmbeddingGatewayAdapter.embedBatch(chunkSet)      # 공유 VectorSpec(NFR PIN); 비용 텔레메트리
  9. records ← assemble IndexRecordBatch (IndexRecord[] = 논문 전 청크, Q4=A)   # 논문 단위 원자 커밋 단위
  10. # ── INV-1 커밋 순서 (논문 단위 원자성) ──
      writeResult ← VectorIndexWriter.upsert(records)               # 전 청크 성공해야 commit
        partial/fail → handle(classify(err)); 미커밋(부분 인덱싱 금지, NFR-R1); return RETRY|DLQ
      DeduplicationGuard.markIngested(paperId, fingerprint)         # upsert durable 후
      RefreshScheduler.advanceWatermark(job.id, parsed.updatedAt)   # 잡 단위, max-clamp(Q17)
  11. 모든 단계 오류 → IngestionResilienceService (재시도/DLQ/경보)
```
- **원자성(Q8=A)**: 한 논문의 **전 청크**(다중) 임베딩·기록 성공 시에만 markIngested. 일부 실패=미커밋·재시도(부분 인덱싱 금지).
- **크래시 복구(INV-1)**: upsert 후 markIngested 전 크래시 → 다음 실행 CHANGED/NEW 재분류·**멱등 재upsert**(ChunkId 키)로 정합.

### 1.2 RefreshOrchestrationService — 제어 평면 (US-I1/I2, RES-2, Q12=B, Q16=A)
인제스천 개시 **3 진입점** 통합·잡 분배.

```
triggerFullRebuild():                                  # US-I1 시드/전체 재구축, RES-2
  acquire REBUILD_LOCK (Q16=A 상호 배제)                 # rebuild 동안 INCREMENTAL/EVENT 보류·거부
  job ← IngestionJob(SEED_REBUILD, slice=resolveSliceCategories() [5cat,1yr], since=null)
  reset Watermark (의도적 리셋 — Q17 예외 경로)
  for batch in harvest(대량 시드 하베스트):              # 프로토콜=NFR Q2; 수십만
      for record in batch: IngestionPipelineService.ingestOne(record, job)  # 쿼터 인지 동시성(NFR Q11=B, 쓰기 직렬화)
  release REBUILD_LOCK; emit job 건강도(진행도·실패율)

onScheduleTick(trigger):                               # US-I2 증분(일 1회)
  if REBUILD_LOCK held → defer/reject (Q16=A)
  job ← RefreshScheduler.onSchedule(trigger) → IngestionJob(INCREMENTAL, slice, since=Watermark)
  for page in paginate(ArxivSourceClient.fetchMetadataPage(slice, cursor, since=Watermark)):  # 증분 조회(프로토콜=NFR Q2)
      for record in page.records: IngestionPipelineService.ingestOne(record, job)

onNewArxivEvent(event):                                # Q12=B 활성(이벤트 경로)
  if REBUILD_LOCK held → defer (Q16=A)
  job ← NewArxivEventHandler.onNewArxivEvent(event) → IngestionJob(EVENT, 단건)
  IngestionPipelineService.ingestOne(event.record, job); NewArxivEventHandler.ackEvent(eventId)  # at-least-once 멱등(Q15=A)
```
- **Q16=A 상호 배제**: 단일 writer 인덱스 보호. rebuild 중 증분·이벤트 보류/거부(RPO 손상 차단).
- **Q12=B 활성**: 이벤트·스케줄·수동 재구축 3경로 모두 운영. 동시성은 fetch/embed 병렬·인덱스 쓰기 직렬화(NFR Q11=B, 단일 writer 유지).

### 1.3 IngestionResilienceService — 복원력 횡단 (US-I3, RES-7/8/9, NFR-R1)
```
handle(error|class, context):
  cls ← IngestFailureHandler.classify(error)            # Q9=A (전문 취득·임베딩·쓰기 실패 포함)
  if RETRIABLE: decision ← scheduleRetry(item, attempt) # Q10=A 지수 백오프+지터, 쿼터 인지
       RETRY → 재시도 큐(NFR Q6 PIN) ; EXHAUSTED → sendToDLQ
  if PERMANENT: sendToDLQ(item, reason)
  emitFailureSignal(jobId, error) → U6.ObservabilityHub # Q11=A 구조화 로그·경보
  # 잡 계속 진행; 잡 실패율 임계 초과 → 갱신 실패 경보(RES-7, US-I2)
```
- 외부 호출(ArxivSourceClient/ObjectStorage/EmbeddingGatewayAdapter/VectorIndexWriter)에 **타임아웃·서킷 주입(RES-9)**. 부분 인덱싱 차단(NFR-R1).

---

## 2. 컴포넌트 알고리즘 수준 (9개, 프로덕션)

| 컴포넌트 | 핵심 알고리즘(프로덕션) |
|---|---|
| **ArxivSourceClient** | `resolveSliceCategories`→ 5 카테고리·최근 1년 phase-1. `fetchMetadataPage`(증분, updated 기준 Q7=A) + 대량 시드 하베스트(프로토콜 NFR Q2). **`fetchFullText` 활성(Q2=C)** — OA 전문 취득. 레이트/쿼터 보수 준수(RES-8)·타임아웃(RES-9)·fail-closed(SEC-15). |
| **FetchParseProcessor** | `parse`: 메타+**전문 본문** ParsedPaper(Q2=C). OA 판정(엄격 라이선스 검증, BR-1). `validate`: 필수필드·형식(SEC-5). **(Q13=B) 철회 신호 탐지**(메타 철회 표시 + 전문 withdrawal 공지) → WithdrawalMarker. |
| **Chunker** | `chunk`: **섹션 인지 다중 청크**(초록·본문 섹션, 오버랩 정책), 추적 메타(paperId·section·position), **결정적·멱등**(PBT-08). `chunkId(paperId, ordinal)` 결정적. 과대/빈/손상 본문 정책(BR-21). |
| **EmbeddingGatewayAdapter** | `embedBatch`: 다중 청크 배치 벡터화(**공유 VectorSpec, NFR PIN**), 타임아웃·재시도·서킷(RES-9), 비용 텔레메트리(NFR-C1), vector↔chunkId 정렬 보존. `embeddingSchema()`→VectorSpec. fail-closed(SEC-15). |
| **VectorIndexWriter** | `upsert`: ChunkId 키 멱등 upsert(논문 전 청크 배치, latest-wins Q3=A). `tombstone`(Q13=B): 철회 논문 전 청크 제거(순서 규칙 아래). `indexStats`→IndexStats(§5). 쓰기 실패 표면화(NFR-R1). |
| **DeduplicationGuard** | `fingerprint`=paperId+version(Q6=A). `isNew`→NEW/CHANGED/DUPLICATE. `markIngested` INV-1 순서. **이벤트 재전송 멱등 단일 백스톱(Q15=A).** |
| **RefreshScheduler** | `onSchedule`→INCREMENTAL 잡. `advanceWatermark` max-clamp(Q17=A). `triggerFullRebuild`→SEED_REBUILD(워터마크 리셋). |
| **NewArxivEventHandler** | **Q12=B 활성**: `onNewArxivEvent`→EVENT 잡, `ackEvent`(at-least-once, 멱등=DedupGuard DUPLICATE 백스톱 Q15=A, 포이즌 이벤트 DLQ). |
| **IngestFailureHandler** | `classify`(Q9=A), `scheduleRetry`(Q10=A), `sendToDLQ`(US-I3), `emitFailureSignal`(Q11=A→ObservabilityHub). |

### Tombstone 순서 규칙 (Q13=B)
- `tombstone(paperId)`는 인덱스에서 해당 PaperId의 **전 청크** 제거. tombstone 경로도 INV-1 순서(durable → markIngested(paperId+vN) → advanceWatermark).
- **순서 규칙 = 버전 단조(highest-vN-wins)**: 제어평면 DedupState가 paperId별 `current_version` + 상태(INDEXED/TOMBSTONED) 보유. **upsert(vN)**는 `vN ≥ current_version`, **tombstone(vW)**는 `vW ≥ current_version`일 때만 적용(아니면 무시) — **`current_version`에 대한 원자적 compare-and-set**(실현=NFR Design). **`current_version > vW`면 삭제 무시**(strictly-newer-vN-wins). **`isNew`는 인서트 스킵 판정이며 삭제 가드가 아님** — 삭제는 위 버전 비교로 가드. 원자적이라 도착 순서 무관 수렴(예: v2 삭제·v3 인서트 경쟁 → v3 생존).
- **재구축 시에도** 동일 철회-신호 탐지(BR-14)가 parse 경로에서 능동 실행(능동 재탐지).

---

## 3. 제어 흐름 — 트리거 표면 (Q12=B, 3경로 모두 활성)

```
[수동/CLI/운영]            [Scheduler/Timer (일1회)]        [Event Bus (Q12=B 활성)]
      │ triggerFullRebuild         │ onScheduleTick                   │ onNewArxivEvent
      ▼                            ▼                                   ▼
        RefreshOrchestrationService  ──(REBUILD_LOCK 상호배제, Q16=A; rebuild 중 증분·이벤트 보류)──
                       │ 잡 분배(논문 단위, fetch/embed 병렬·쓰기 직렬화)
                       ▼
            IngestionPipelineService.ingestOne  → (per-paper 파이프라인 §1.1)
```

---

## 4. 데이터 흐름 ASCII (per-paper, 프로덕션 — 전문·다중 청크·철회)

```
fetchFullText(Q2=C) ─▶ RawDocument ─(parse)─▶ ParsedPaper{abstract, body/sections} ─▶ StoredFullText(ObjectRef, SEC-9)
                                   │ (Q13=B) 철회신호(메타+전문)? ──예──▶ tombstone(전 청크) ─▶ markIngested ─▶ advanceWatermark
                                   │아니오
                          isNew(paperId+version)
                          │DUPLICATE        │NEW|CHANGED
                          ▼                 ▼
                       SKIPPED      chunk(섹션 인지 다중) ─▶ embedBatch(공유 VectorSpec) ─▶ IndexRecord[](청크당)
                                                                                      │ INV-1, 논문 단위 원자
                                          upsert(IndexRecordBatch, 멱등) ─durable─▶ markIngested ─▶ advanceWatermark
   실패 전 단계 ─▶ IngestionResilienceService ─▶ classify ─▶ retry(큐)|DLQ ─▶ emitFailureSignal ▶ U6.ObservabilityHub
```

---

## 5. IndexStats 소비 계약 (cross-unit)

- `indexStats() -> IndexStats{docCount, vectorCount, lastWrite}`. **프로덕션: vectorCount ≫ docCount(논문당 다중 청크).**
- **소비자**: U6.HealthCheckService.deepCheck(RES-6, 벡터 스토어 연결성·규모) + **RES-2 재구축 완전성 검증**(시드 후 docCount/vectorCount가 기대 코퍼스 규모 도달).
- **`lastWrite`**: 성공 upsert/tombstone 커밋 시 전진(인제스천 건강도·정체 탐지, RES-7).
- **운영 재구축 런북**(AS-5): triggerFullRebuild 진입점 정의; 절차·실행자·검증은 Infra/Operations.

---

## 6. 멀티모달 자산 추출·저장 (FR-17 — 표시 전용, 2026-06-22 확장)

> **근거**: FR-17 · FD 계획 Q1~Q7=A(Q2=C 혼합). **표시 전용** — §1.1 인덱싱 경로(chunk·embed·upsert·INV-1 원자성)는 **불변**. 자산은 **best-effort 보조 산출**로 인덱스 커밋과 **분리**(Q4=A).

### 6.1 `ingestOne` 삽입 지점 (Q1=A: parse 추출 + dedup 이후 NEW|CHANGED 저장)

```
ingestOne(record, job):
  ...
  2. parsed ← FetchParseProcessor.parse(raw)
       # (FR-17) 메타+전문 정규화에 더해 그림·도표 자산 디스커버리:
       #   assets[] ← AssetExtractor.extract(raw, parsed)        # Q2=C 혼합(아래 6.2)
       #   parsed.assets = FigureTableAsset[](바이너리+메타, 캡션은 본문 캡션 참조)
  ...
  5. decision ← DeduplicationGuard.isNew(parsed)
       DUPLICATE → return SKIPPED   # 자산도 재추출·재저장 0 (Q1=A, NFR-C1 정신)
       NEW | CHANGED → 계속
  6. (Q2=C) StoredFullText ← ObjectStorage.put(raw)             # 기존
  6'. ── (FR-17, NEW|CHANGED만) 자산 저장: best-effort, 인덱스 원자성과 분리 (Q4=A) ──
       if parsed.oaStatus == OA (BR-1 게이트 통과):              # 비-OA는 자산 미저장(전문과 동일)
         for asset in parsed.assets:
           objectRef ← AssetStorePort.put_asset(asset.binary)    # S3, SEC-9 비공개
         AssetStorePort.put_manifest(AssetManifest(paperId, version, assets-meta))   # RDS (Q6=A)
         if CHANGED: AssetStorePort.replace_assets(paperId, version)   # 이전 버전 stale 교체/정리
       # 실패 시: emitFailureSignal(jobId, ASSET_*) → 관측·재시도 신호. 논문 인덱싱 비차단(Q4=A).
  7..10. chunk → embed → upsert(INV-1 원자) → markIngested → advanceWatermark   # 불변, 자산과 독립
```

- **위치(Q1=A)**: 추출은 `parse`에 동반(디스커버리), **저장은 dedup 이후 NEW|CHANGED만** — DUPLICATE는 자산 재추출·재저장 0.
- **원자성 경계(Q4=A)**: 자산 저장은 **INV-1 원자 커밋(인덱스) 밖**. 자산 실패는 `markIngested`/워터마크 전진을 **막지 않는다**(표시 전용; 검색 정합은 인덱스가 권위). 자산 실패는 `IngestionResilienceService`로 관측·재시도(별도 신호, FailureReason `ASSET_EXTRACT_FAILURE`/`ASSET_STORE_FAILURE`).

### 6.2 혼합 추출 — `AssetExtractor.extract` (Q2=C)

```
extract(raw, parsed):
  if raw.eprintSource(LaTeX) 가용:
      assets ← structuredExtract(eprint)        # \includegraphics 그림 파일 + table 환경, sourceMode=structured
      if assets 성공(비어있지 않음·검증 통과): return assets
  # 폴백(소스 없음/추출 실패):
  assets ← pageCropExtract(pdf, layout)          # 페이지 렌더 후 그림/표 영역 크롭, sourceMode=page-crop, pageRef/bbox 기록
  return assets
```
- **결정성(P7)**: 동일 `raw/parsed` → 동일 자산 집합·동일 `assetId`(순서·type별 ordinal 안정). 추출 라이브러리·bbox 검출 임계·이미지 포맷/해상도는 **NFR/Infra**.
- **캡션**: 본문에 보존된 캡션을 참조/연결(중복 추출 안 함, BR-25). `sectionRef`+`ordinal`로 앵커 매칭 좌표 부여.

### 6.3 철회(tombstone) 연동 (Q4=A)

`ingestOne` step 4 tombstone 경로(BR-14)에 자산 정리 추가:
```
... → VectorIndexWriter.tombstone(paperId)            # 기존(전 청크 제거)
    → AssetStorePort.remove_assets(paperId)           # (FR-17) 자산·매니페스트 제거 (best-effort, 비차단)
    → invalidate doc-model 캐시(paperId)              # (피벗 §7) doc-model/{paperId}/* 무효화 (best-effort, 비차단)
    → markIngested(paperId+vN) → advanceWatermark
```

### 6.4 데이터 흐름 ASCII (자산 분기 추가)

```
parse(Q2=C) ─▶ ParsedPaper{abstract, body/sections, assets[](FR-17)}
   │ assets = AssetExtractor.extract: e-print 있으면 structured, 없/실패면 page-crop 폴백
   ▼
isNew ─DUPLICATE─▶ SKIPPED(자산 재저장 0)
   │ NEW|CHANGED
   ├─[인덱스 경로 불변]─▶ chunk ─▶ embed ─▶ upsert(INV-1 원자) ─▶ markIngested
   └─[자산 경로 best-effort, OA 게이트]─▶ AssetStorePort.put_asset(S3) + put_manifest(RDS)
                                          │ 실패 ─▶ emitFailureSignal(ASSET_*) (인덱싱 비차단)
                                          │ CHANGED ─▶ replace_assets(stale 교체)
철회 ─▶ tombstone(전 청크) + remove_assets(자산) ─▶ markIngested
```

---

## 7. doc-model 생성·캐시 (구조화 본문 — 피벗 2026-06-23)

> **근거**: 피벗 게이트 D1·D2·D6 + Q5 권장(SSOT=`construction/plans/docmodel-foundation-pivot-plan.md`). 요약/번역(U7) 입력을 `.txt` → **구조화 doc-model**로 전환(입력 업그레이드, **로직 불변** D2). **§1.1 인덱스/검색 경로(chunk·embed·upsert·INV-1 원자성)는 불변** — doc-model은 인덱스 권위가 아니라 **소비자(요약·리치뷰·에이전트) 입력 계약**.

### 7.1 산출물·보관 (BR-29 확장)
- **보관 = 평문 1종 → + doc-model.** 기존 `StoredFullText(.txt)`(정규화 평문)은 **인덱스 청킹·검색 투영**으로 유지(Q4 권장: doc-model = 진실원천, `.txt` = 파생 평문 투영). 신규 `doc-model/{paperId}/v{version}.json` = 본문(섹션/블록·앵커) + **표 = 구조화 데이터(rows/cols)** + **수식 = LaTeX(MathML 변환)** + 그림/표이미지 = webp `assetId` 참조.
- **이미지 바이트는 doc-model에 넣지 않음** — `assetId` 포인터만(base64 부풀림·개별 presign/lazy 불가 방지). 픽셀은 기존 `assets/.../{assetId}.webp`(§6 FR-17) 재사용, 메타는 RDS `paper_asset` 재사용 — **재추출 0**.
- **D8**: 기존 "표 = PDF 크롭"(TD-12)은 표 = 데이터로 승격(텍스트 에이전트가 표 숫자를 읽도록). 표 크롭 이미지는 있으면 webp로 두되 주 표현은 doc-model 데이터.

### 7.2 생성 = lazy on-demand + 캐시 (D6, Q5)
```
buildDocModel(paperId, version):              # U1 도메인 능력; 소비자(U7/리치뷰/에이전트)가 lazy 호출
  if cache hit (paperId, version): return cached         # D6 (paper_id, version) 캐시
  html ← SourceLadder.fetch(paperId)          # native HTML → ar5iv → (최후) e-print/PDF 폴백 (Q6, BR-29)
  doc  ← DocModelParser.parse(html)           # 결정적 파싱(LLM 추출 금지 D1): 섹션/블록/앵커 · 표 rows/cols · 수식 LaTeX
  doc.assets ← linkExisting(paper_asset)      # webp assetId 참조 연결(재추출 0; §6 산출물 재사용)
  ObjectStorage.put(doc-model/{paperId}/v{version}.json)  # SEC-9 비공개, doc-model/ prefix(Infra)
  return doc
```
- **트리거(Q5 권장) — 비동기·경계 B(구현됨)**: 첫 **열람(리치뷰)** 시 캐시 미스면 소비자(U7)가 **빌더를 직접 호출하지 않고** U1 큐에 `BUILD_DOC_MODEL` 잡을 enqueue(읽기 측은 enqueue만, 빌더 생성은 U1 워커 — 요약↔빌더 의존 분리). 워커가 `buildDocModel`을 실행(메타 fetch→파싱→`doc-model/{id}/v{ver}.json` 캐시). 읽기 API는 미스를 **`building`**(폴링 힌트 `retryAfterMs`)으로 반환 → 클라이언트 폴링 → 캐시 히트로 렌더. 멱등(캐시 히트 단락)·인프로세스 dedup·enqueue best-effort. **요약 입력 경로는 빌드를 트리거하지 않음**(미스→`.txt` 폴백·다음 요청 자동 업그레이드). **version 변경 시 무효화**(키 = paperId+version). 전 코퍼스 eager 아님(D6 — 비용=사용량 비례).
- **결정성(D1, P7)**: LLM 추출 금지(표 숫자 환각 방지) — 결정적 파서만. 동일 HTML → 동일 doc-model.
- **`ingestOne`은 doc-model을 eager 생성하지 않음** — 인덱스 hot path 비차단(§6 자산과 동일하게 인덱스 원자성 밖). 빌더는 U1 소유, 호출 시점은 on-demand. 파서 라이브러리·MathML→LaTeX 변환·캐시 스토어는 **NFR/Infra**(TD-12·Infra).
- **철회(tombstone) 연동**: §6.3 자산 정리에 doc-model 캐시 무효화 동반(`remove docModel(paperId)`, best-effort·비차단).

> 결정·검증 규칙은 `business-rules.md`. 엔티티는 `domain-entities.md`.
