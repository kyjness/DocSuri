# U1 Ingestion — 파이프라인 상세 (수집·청킹·임베딩·색인)

> 학습용 메모. **커밋하지 않는다.** 근거: `ingestion/src/docsuri_ingestion/` 실제 코드 + `shared/`.
> 형식: **[받음] → [함] → [내보냄]**. 먼저 `00-project-overview.md`·`u2-discovery.md` 가정.
> ★U1 = U2의 **거울짝**. U2(단일 reader)가 읽던 `docsuri-corpus-v1` 인덱스의 `IndexRecord`를 **채우는 게 U1(단일 writer)**. U2 §0에서 본 그 데이터가 여기서 만들어진다.

---

## 0. 이 유닛이 하는 일 / U2와 정반대인 성격

arXiv에서 논문을 긁어와 → 검증 → 조각내고 → 임베딩 → **OpenSearch 인덱스에 색인**한다. 즉 **창고를 채우는 일꾼**.

**U2와 정반대 (이 대비가 핵심):**

| | U1 Ingestion | U2 Discovery |
|---|---|---|
| 목표 | **처리량(throughput)** | **레이턴시(P50<3s)** |
| 실행 | 비동기 **워커**(백그라운드, 별도 프로세스) | 동기, 사용자 요청 경로 |
| 장애 시 | **끈질기게 재시도**(5회) | **빨리 포기/우회**(재시도 안 함) |
| 임베딩 역할 | `search_document`(writer) | `search_query`(reader) |
| 인덱스 | 단일 **writer** | 단일 **reader** |

**[코드 위치]** `ingestion/`은 `backend/` 밖 — **별도 프로세스**(사용자 요청 앱이 아님).

```
docsuri_ingestion/
├── worker.py          ← 큐 폴링 루프 (SIGTERM drain)
├── application.py     ← ★IngestionPipelineService.ingest_one (색인 1건) + RefreshOrchestrationService (트리거)
├── processors.py      ← parse·chunk·dedup·assemble
├── resilience.py      ← retry·circuit·timeout·DLQ
├── adapters/          ← arxiv·aws(S3/SQS/OpenSearch/Bedrock)·postgres
└── config.py          ← 코퍼스 범위·라이선스 allowlist·withdrawal 마커
```

---

## 트리거 — `RefreshOrchestrationService` (무엇을 색인할지 큐에 적재)

색인할 논문을 **3가지 방식**으로 발견해 SQS 큐에 `IngestionJob`을 넣는다:

| 메서드 | 언제 | 무엇을 |
|---|---|---|
| `on_schedule_tick()` | 주기적 | **증분** — watermark(마지막 처리 시점) 이후 갱신된 것만 |
| `on_new_arxiv_event(e)` | 새 논문 이벤트 | 그 한 편 |
| `trigger_full_rebuild()` | 전체 재구축 | 코퍼스 전체 (락 획득) |

**[중요]** 전체 재구축(rebuild)이 진행 중이면 증분/이벤트는 **defer(연기)**. *watermark* = "여기까지 처리함" 표시 → 다음엔 그 **이후 것만** 가져와 중복 처리 방지.
**[코퍼스 범위]** `config.py`: 카테고리 `cs.LG·cs.AI·cs.CL·cs.CV·stat.ML`, 기간 2021~2026.

---

## 워커 — `worker.py` (큐에서 꺼내 처리)

**[함]**
```python
while not _shutdown_event.is_set():
    for message in queue.receive_messages(max_messages=10):   # SQS에서 최대 10개
        process_message(runtime, message)                     # → ingest_one
    _shutdown_event.wait(timeout=1.0)
```
- **SIGTERM/SIGINT → graceful drain**: 신호 받으면 현재 배치까지만 처리하고 깔끔히 종료(작업 안 잃음).
- `process_message`: 페이로드 파싱 실패(포이즌) → PERMANENT → DLQ + ack. 정상 → `ingest_one` 호출 후 ack.

---

## 색인 1건 — `IngestionPipelineService.ingest_one` (★본체)

생성자에서 `assert_writer_embedding_role()` — 부팅 시 **임베딩 역할이 `search_document`인지 강제**(U2 reader와 비대칭, 어긋나면 색인 자체를 거부).

**[공통 복원력]** 의존성 호출마다 `resilience.dependency_call`로 감싼다 (`resilience.py`):
- **retry 5회** — 지수 backoff(1초→2→4→8…) + jitter(±20%)
- **circuit breaker** — 5회 연속 실패 시 **OPEN**(차단), 60초 후 재시도 허용
- **timeout 30초** — 초과 시 RetriableError

> *circuit breaker(서킷 브레이커)* = 어떤 의존성이 계속 실패하면 **잠시 호출을 끊어**(OPEN) 더 망가지지 않게 하고, 일정 시간 뒤 다시 시도. (U6 비용 가드의 서킷과 같은 개념, 다른 대상.) retry와 **독립**으로 동작.

### 단계별 (성공 경로)

```
① record_job_started ──────────────▶ PostgreSQL (컨트롤 플레인: 작업 상태)
② fetch_metadata + fetch_full_text ─▶ arXiv HTTP
③ parse (FetchParseProcessor)
④ dedup 평가 ──────────────────────▶ PostgreSQL
⑤ begin_upsert (claim, 단조 가드)
⑥ put_full_text ───────────────────▶ S3 (원문 보관)
⑦ chunk (Chunker)
⑧ embed_documents ─────────────────▶ Bedrock (Cohere v3, search_document, 1024d)
⑨ assemble IndexRecord
⑩ bulk_upsert + delete_stale_chunks ▶ OpenSearch docsuri-corpus-v1
⑪ mark_ingested · advance_watermark · record_job_finished
```

### ③ parse — 라이선스·검증·철회 게이트 (`FetchParseProcessor`)

**[함]** 색인 전에 **거른다**:
- **라이선스 allowlist**: CC-BY 계열(`creativecommons.org/licenses/by/`·`by-sa/`·`cc0/`)만 통과. 아니면 `LicenseRejectedError`. → **오픈액세스만 색인**(저작권 안전).
- **메타 검증**: title·authors·abstract·category 다 있어야. 없으면 `ValidationViolationError`.
- **철회(withdrawal) 감지**: 제목·초록·본문에 "this paper has been withdrawn" 등 마커 있으면 → `withdrawal_detected=True` → 색인 대신 **tombstone 경로**(인덱스에서 제거).

> *tombstone(툼스톤)* = "이 논문은 철회됨" 묘비. 색인에 넣는 대신 **제거 표시**를 OpenSearch에 써서, 이미 색인됐던 게 검색에 안 잡히게.

### ④⑤ dedup — 같은 논문 재처리 방지 (멱등 색인)

**[함]** `(paperId, version, fingerprint)`로 중복 판정:
- **DUPLICATE/STALE** → `record_job_finished(success=True)` + **short-circuit 종료**(임베딩 등 비싼 단계 안 함).
- **begin_upsert** = claim(점유). **단조 가드(monotonic guard)** — 이미 처리된 것보다 **낮은 버전은 거부**.

> *단조 가드* = "버전은 **올라가기만** 한다." 오래된 메시지가 재배달돼도(SQS at-least-once) **최신본을 옛 버전으로 덮어쓰지 못하게** 막는다. *fingerprint* = 논문 내용의 지문(해시) — 내용 안 바뀌었으면 재색인 생략.

### ⑥ put_full_text — S3

**[함]** 원문 전문을 S3에 저장 → `stored_full_text_ref` 받아 보관. **(이게 U7이 요약할 때 읽는 그 전문이다.)**

### ⑦ chunk — 조각내기 (`Chunker`)

**[함]** 논문을 청크로 분할:
- **최대 2400자/청크**, **겹침(overlap) 240자**, **논문당 최대 128청크**.
- 섹션 = `abstract` + 본문 헤딩별로 나눔.
- 겹침을 두는 이유: 청크 경계에서 문맥이 잘려 검색 누락되는 걸 줄이려고(앞 청크 끝 240자를 다음 청크가 다시 포함).

### ⑧ embed_documents — Bedrock

**[함]** 각 청크 텍스트를 **1024차원 벡터**로. `input_type=search_document`(writer 역할). **U2가 쿼리를 `search_query`로 임베딩하던 것과 같은 모델·같은 공간**(vector-spec 불변식).

### ⑨ assemble — IndexRecord 조립 (`IndexRecordAssembler`)

**[함]** 청크+벡터를 합쳐 **U2가 읽을 바로 그 `IndexRecord`**를 만든다:
- `chunkId` = **결정적**(`chunk_id(paperId, ordinal)`) → OpenSearch upsert 키로 그대로 → 재처리해도 같은 키 = 멱등.
- `lexicalTerms` = `정규화(제목 + 초록 + 청크본문)` → U2의 **BM25 대상 필드**.
- `vector` → U2의 **k-NN 대상 필드**.
- 카드 7필드(title·authors·year·arxivId·abstractSnippet·arxivUrl) → U2 ⑧이 화면에 투영.

### ⑩ bulk_upsert + delete_stale_chunks — OpenSearch

**[함]** 레코드들을 `docsuri-corpus-v1`에 **일괄 upsert** + 이번 배치에 **없는 옛 청크는 삭제**(paperId 단위) → 버전이 올라가 청크 수가 줄어도 옛 조각이 안 남음.

### ⑪ 마무리

`mark_ingested`(dedup 상태 확정) · `advance_watermark`(여기까지 처리함) · `record_job_finished`.

---

## 실패 처리 — 분류해서 (worker + application)

```python
except IngestionError as exc:
    record_job_finished(success=False) → emit_failure_signal
    if PERMANENT:  send_to_dlq() + ack       # 포이즌·검증위반 → 격리, 다시 안 봄
    # RETRIABLE:   ack 안 함 → SQS가 재배달   # 일시 장애 → 다시 시도
```

**[왜 분류?]** *PERMANENT*(라이선스 거부·검증 위반·포이즌 메시지)는 재시도해도 또 실패 → **DLQ(Dead Letter Queue, 실패 격리 큐)** 로 보내고 ack(큐에서 치움). *RETRIABLE*(일시적 네트워크·타임아웃)은 ack 안 해서 SQS가 다시 배달. → **조용한 유실 없음.**

---

## 한 장 요약

```
트리거(RefreshOrchestrationService): 증분(watermark 이후)·이벤트·전체재빌드(락) → SQS 큐
        ↓
워커(worker.py): receive(max 10) → ingest_one  (SIGTERM drain)
        ↓
ingest_one — 의존성마다 retry5·circuit(5/60s)·timeout30s
 ① job_started      → PostgreSQL
 ② fetch            → arXiv HTTP
 ③ parse: 라이선스 allowlist(CC-BY) + 메타검증 + 철회→tombstone
 ④⑤ dedup(paperId·version·fingerprint) short-circuit + 단조 가드(낮은 버전 거부)
 ⑥ put_full_text    → S3   (U7이 읽을 전문)
 ⑦ chunk: 2400자·overlap240·≤128청크
 ⑧ embed            → Bedrock (search_document, 1024d)
 ⑨ assemble IndexRecord (chunkId 결정적·lexicalTerms·vector·카드7필드)
 ⑩ bulk_upsert + delete_stale_chunks → OpenSearch docsuri-corpus-v1
 ⑪ mark_ingested · advance_watermark · job_finished
 실패: PERMANENT→DLQ+ack / RETRIABLE→미ack 재배달
```

**전체 데이터 수명주기 완성**: U1이 `search_document`로 써넣은 `IndexRecord`를 → U2가 `search_query`로 읽고 → U7이 ⑥의 S3 전문을 요약한다. **단일 writer(U1) / 단일 reader(U2)**가 같은 공간(vector-spec)을 공유하는 게 전체 검색의 토대.
```
