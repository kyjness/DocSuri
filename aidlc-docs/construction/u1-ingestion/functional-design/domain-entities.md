# domain-entities.md — U1 Ingestion 도메인 엔티티 (프로덕션)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U1 Ingestion · **일자**: 2026-06-16
**근거**: 계획서(프로덕션 재스코핑 배너) — **Q1=D**(풀 FR-6 슬라이스)·**Q2=C**(OA 전문 청킹)·**Q12=B**(이벤트 경로 활성)·**Q13=B**(철회 tombstone)·그 외 A.
**원칙**: 기술 무관(엔티티 = 도메인 개념·관계·식별 규칙). 직렬화/저장 표현은 NFR/Infra. **VectorSpec 구체값(차원·모델·거리 메트릭)은 NFR Requirements에서 PIN.**
**프로덕션 스코프**: 전문(full-text) 수집·다중 청크·이벤트 경로·철회 tombstone **전부 활성**. (이전 데모 트랙 폐기.)

---

## 1. 식별자 값타입 & 식별/버전 규칙

| 엔티티 | 정의 | 규칙 |
|---|---|---|
| **ArxivId** | arXiv 식별자(버전 포함 가능, 예 `2401.01234v2`) | 원천 식별자. 버전 토큰 분리 가능. |
| **PaperId** | **정규 = 버전 없는 ArxivId** | **Q3=A**: 한 논문의 모든 버전이 동일 PaperId. 인덱스·디덥·라이브러리(U4) 참조 안정 키. |
| **PaperVersion** | arXiv 버전 정수(vN) | 최신 버전만 인덱스(latest-wins upsert). |
| **ChunkId** | `chunkId(PaperId, ordinal)` 결정적 | **PBT-08 결정성**. **프로덕션: 논문당 다중 청크(ordinal 0..N)** — 섹션 인지 분할(§3). |
| **ContentFingerprint** | 디덥 키 = **`PaperId + PaperVersion` 파생**(콘텐츠 해시 아님, Q6=A) | 잠긴 `fingerprint()->ContentHash`와 정합: ContentHash가 ID+버전 파생 키를 담음(개념상 VersionKey). |
| **EventId** | new-arXiv 이벤트 식별자 | **Q12=B 활성**. at-least-once ack 단위. **Q15=A: 이벤트-레벨 dedup 없음** — 멱등은 ContentFingerprint(DUPLICATE) 단일 백스톱. |
| **JobId** | 인제스천 잡 식별자 | 잡 진행도·실패율·워터마크 전진 상관 키. |
| **ObjectRef** | OA 전문 원천의 오브젝트 스토리지 참조(키/버전) | **Q2=C·SEC-9 활성**: 전문 보관 위치. 재구축·재처리 재사용. |

> **버전 의미**: 신규 게재=신규 PaperId(NEW). 동일 PaperId vN 증가=CHANGED(재처리·덮어쓰기). 동일 vN 재수신=DUPLICATE(단락). 워터마크=arXiv **updated**(Q7=A)로 vN 개정 포착.

---

## 2. 수집·파싱 엔티티

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **CategoryFilter** | `categories[]`, `from`/`to`(기간) | **Q1=D: `categories=[cs.LG,cs.AI,cs.CL,cs.CV,stat.ML]`, 최근 5년(수십만 건).** `resolveSliceCategories()` 산출. |
| **PageCursor** | 불투명 페이지/하베스트 커서 | 대량 시드 하베스트 + 증분 조회 페이지네이션 상태(프로토콜=NFR Q2). |
| **MetadataPage** | `records[]`(원천 메타), `nextCursor`, `hasMore` | 슬라이스 페이지 단위 조회 결과. |
| **RawDocument** | `text`(정규화 평문), `sourceMeta`, `oaStatus` | **BR-29**: 취득 = arXiv HTML 우선(평문 변환의 최선 소스) → PDF 폴백. 산출은 **평문 1종**(뷰어·AI 공통). |
| **ParsedPaper** | `paperId`, `version`, `title`, `authors[]`, `year`, `abstract`, **`full_text`(정규화 평문)**, `categories[]`, `arxivUrl`, `updatedAt`, `objectRef?` | **Q2=C/BR-29: 본문 전문(평문).** FetchParseProcessor.parse 산출. 요약/번역 입력 + 뷰어 렌더(평문, 앵커 하이라이트). |
| **RejectedRecord** | `reason`(RejectReason), `sourceRef` | parse/validate 거부. **§4 RejectReason 분류.** |
| **ValidationResult** | `ok`(bool), `violations[]` | FetchParseProcessor.validate 산출(SEC-5). ok=false → `VALIDATION_VIOLATION` / PERMANENT(BR-15). |
| **WithdrawalMarker** | `paperId`, `detectedAt`, `signal`(철회 근거) | **Q13=B 활성.** 탐지원(프로덕션): arXiv 메타데이터 철회 표시 **+ 전문 withdrawal 공지**(BR-14). → tombstone 라우팅. |

---

## 3. 청킹·임베딩 엔티티

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **Chunk** | `chunkId`, `paperId`, `text`, `section`, `position`(ordinal) | **Q2=C: 논문당 다중 청크 — 섹션 인지 결정적 분할**(초록·본문 섹션). 추적 메타(FR-5). |
| **ChunkSet** | `paperId`, `chunks[]`(다중) | Chunker.chunk 산출. **결정성·멱등**(동일 ParsedPaper→동일 ChunkSet·동일 ChunkId, PBT-08). 본문 크기 정책(BR-21). |
| **EmbeddingBatch** | `vectors[]`(**chunkId 정렬**), `vectorSpecRef` | embedBatch 산출. **정렬 불변식**: `vectors[i] ↔ chunks[i].chunkId`(재정렬/누락 0). 공유 VectorSpec(NFR Requirements PIN) 공간. 다중 청크 배치. |

---

## 4. 인덱스 엔티티 (공유 벡터 인덱스 — U1 write-only 생산자)

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **IndexRecord** | `chunkId`, `paperId`, `version`, `vector`, **카드 필드**(title·authors·year·arxivId·abstractSnippet·arxivUrl) + `categories` + `abstract` + `section` + `lexicalTerms` | **Q4=A·Q2=C: 청크당 1 레코드(논문당 다수).** FR-2 하이브리드(lexical=제목+초록+본문 토큰) + FR-4 카드 + FR-5 해소 가능 ID/링크. |
| **IndexRecordBatch** | `records[]`(한 논문의 전 청크), `paperId`, `jobRef?` | `VectorIndexWriter.upsert` 입력 = **논문 단위 원자 커밋 단위**(Q8=A/BR-7). **프로덕션: 논문당 다중 IndexRecord 전부 또는 전무.** PBT P3/P4 대상. |
| **StoredFullText** | `paperId`, `version`, `objectRef`, `contentType` | **Q2=C·SEC-9 활성**: OA 전문 오브젝트 스토리지 보관(공개 차단). 재구축·재처리 재사용(arXiv 재취득 회피). |
| **WriteResult** | `written`, `skipped`, `failed[]` | upsert/tombstone 결과. `failed[]`→IngestionResilienceService. |
| **IndexStats** | `docCount`, `vectorCount`, `lastWrite` | 소비 계약(business-logic §5): U6.HealthCheckService.deepCheck(RES-6) + RES-2 재구축 완전성 검증. `lastWrite`=성공 커밋 시 전진. **프로덕션: vectorCount ≫ docCount(다중 청크).** |
| **Tombstone** | `paperId`, `tombstonedAt`, `reason` | **Q13=B 활성.** 철회 논문의 전 청크 제거. **순서 규칙(BR-14, 버전 단조)**: tombstone(vW)는 `vW ≥ current_version`일 때만 적용, 더 새로운 vN이 이미 있으면 무시(strictly-newer-vN-wins). 제어평면 `current_version` compare-and-set로 강제 — `isNew`는 인서트 스킵용이며 삭제 가드 아님. |

> **단일 writer/단일 reader**: U1.VectorIndexWriter만 쓰고 U2.HybridRetriever만 읽음(잠금).

---

## 5. 제어 평면 엔티티

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **ScheduleTrigger** | `firedAt`, `kind`(INCREMENTAL) | RefreshScheduler.onSchedule(일 1회, NFR Q13=A). |
| **NewArxivEvent** | `eventId`, `arxivRef` | **Q12=B 활성**: NewArxivEventHandler 소비(at-least-once 멱등, Q15=A). |
| **IngestionJob** | `jobId`, `kind`(**`SEED_REBUILD` \| `INCREMENTAL` \| `EVENT`**), `slice`(CategoryFilter), `since?`(Watermark), `status` | RefreshOrchestrationService 생성·분배. SEED_REBUILD=US-I1 전체 재구축(워터마크 리셋, 대량 시드 하베스트 — 프로토콜 NFR Q2), INCREMENTAL=US-I2 증분, **EVENT=Q12=B new-arXiv 단건**. |
| **Watermark** | 단일 전역 타임스탬프(arXiv updated, Q7=A) | RPO 지표(RES-2). **Q17=A max-clamp**(전진만); SEED_REBUILD만 의도적 리셋(BR-13 상호배제 보호). |

---

## 6. 디덥·상태 엔티티

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **DedupState** | `paperId` → `fingerprint`, `ingestedAt` | markIngested 기록(INV-1: upsert 내구화 후). |
| **DedupDecision** | `NEW` \| `CHANGED` \| `DUPLICATE` | isNew 산출. NEW/CHANGED만 fetchFullText→chunk→embed→upsert; DUPLICATE 단락(NFR-C1 재임베딩 0). |

---

## 7. 실패 엔티티 (US-I3 / RES-7/8/9)

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **IngestError** | `stage`, `cause`, `httpStatus?` | 파이프라인 단계 오류(전문 취득·임베딩·쓰기 포함). |
| **FailureClass** | `RETRIABLE` \| `PERMANENT` | **Q9=A**: RETRIABLE=네트워크/타임아웃/5xx/429; PERMANENT=파싱·검증·비-OA·404. |
| **RetryDecision** | `RETRY`(at delay) \| `EXHAUSTED` | **Q10=A**: 지수 백오프+지터(수치 NFR Q14). |
| **IngestItem** | 재시도 가능 작업 단위(per-paper: record + 잡 컨텍스트) | scheduleRetry/sendToDLQ 파라미터. 입도=논문 단위(Q8=A). |
| **DLQItem** | `item`(IngestItem), `reason`(FailureReason), `attempts` | 소진/영구 격리(US-I3). |
| **FailureReason** | 사유 코드 | RejectReason ∪ {RETRY_EXHAUSTED, FULLTEXT_FETCH_FAILURE, EMBEDDING_FAILURE, WRITE_FAILURE …}. |

**RejectReason 분류**: `NON_OA` · `PARSE_FAILURE` · `VALIDATION_VIOLATION` · `FETCH_FAILURE`. **엄격 OA 라이선스 검증(팀 결정, BR-1)** → 재배포 불가/미표기 라이선스 NON_OA 배제.

---

## 8. 공유 계약 (참조 — 소유=공유 임베딩 게이트웨이 레이어, UQ5=A)

| 엔티티 | 정의 | 비고 |
|---|---|---|
| **VectorSpec** | `dimensions`, `modelRef`, `distanceMetric` | **NFR Requirements가 차원·모델·거리 메트릭을 PIN.** U1 writer ↔ U2 reader **동일 임베딩 공간 불변식**. U1(빌드 #1)이 값을 PIN하나 소유는 shared/(NS-5), 후속 유닛 재결정 없음. 선택 스토어 ANN 인덱스가 PIN된 차원·거리 지원 확인(ANN 호환 게이트). |

---

## 9. 엔티티 관계 (프로덕션)

```
CategoryFilter(5cat,5yr) ──(fetchMetadataPage / 대량 하베스트)──▶ MetadataPage{ records[] }
   record ──(parse, fetchFullText Q2=C)──▶ ParsedPaper{ paperId, version, abstract, body/sections } ──▶ StoredFullText(ObjectRef, SEC-9)
      │                                                          │ (Q13=B) 철회신호(메타+전문)? ─▶ WithdrawalMarker ─▶ Tombstone(전 청크)
      ├─(fingerprint=paperId+version)─▶ ContentFingerprint ─(isNew)─▶ DedupDecision
      │                                                                │ NEW|CHANGED
      ▼                                                                ▼
   ParsedPaper.body/abstract ─(chunk: 섹션 인지 다중)─▶ ChunkSet{ Chunk[0..N] } ─(embedBatch, 공유 VectorSpec)─▶ EmbeddingBatch{ vectors↔chunkId }
                                                                                  │
                                            Chunk + 메타 + vector ─▶ IndexRecord[] ─(논문 전 청크 = IndexRecordBatch)─▶ [공유 벡터 인덱스]
                                                                                  │ INV-1: upsert durable ─▶ markIngested ─▶ advanceWatermark(max-clamp)
IngestionJob{ SEED_REBUILD | INCREMENTAL | EVENT(Q12=B) } ── 제어 ──▶ (논문 단위 분배; Q8=A 원자성)
실패(IngestError) ─(classify)─▶ FailureClass ─▶ RetryDecision | DLQItem ─▶ 경보
```

---

## 10. 멀티모달 자산 엔티티 (FR-17 — 표시 전용, 2026-06-22 확장)

> **근거**: `requirements.md` FR-17 · 멀티모달 FD 계획 Q1~Q7=A(Q2=C 혼합 추출). **표시 전용** — 자산은 **검색 비대상**이므로 §3·§4(Chunk·EmbeddingBatch·IndexRecord·VectorSpec) **불변**. 자산은 `IndexRecord`에 포함되지 않는다.

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **AssetType** | `figure` \| `table` | 값타입. |
| **AssetSourceMode** | `structured` \| `page-crop` | **Q2=C 혼합**: `structured`=arXiv e-print(LaTeX) 직접 추출, `page-crop`=PDF 페이지 영역 크롭 폴백. 자산이 어느 경로로 나왔는지 기록(관측·품질 추적). |
| **AssetId** | `assetId(PaperId, PaperVersion, AssetType, ordinal)` 결정적 | **Q3=A**: `ChunkId`와 동형 결정성(PBT 후보 P7). `ordinal`=문서 등장 순서(0..N), type별 분리. 재처리 멱등 키. |
| **FigureTableAsset** | `assetId`, `paperId`, `version`, `type`(AssetType), `caption`, `sectionRef`, `ordinal`, `sourceMode`, `objectRef`, `pageRef?`/`bbox?` | **FR-17 핵심 엔티티.** `caption`=본문 보존 캡션 참조(중복 추출 안 함). `sectionRef`+`ordinal`=앵커(`AnchorVM.target=figure\|table`) 매칭 좌표(인셉션 Q5). `objectRef`=자산 바이너리의 오브젝트 스토리지 참조(SEC-9 **공개 차단**). `pageRef`/`bbox`=`page-crop` 모드 위치. **원문에서 추출된 실재 자산만**(생성·합성 금지, BR-24). |
| **AssetManifest** | `paperId`, `version`, `assets[]`(FigureTableAsset 메타) | 논문 단위 자산 목록. **영속(Q6=A)**: 바이너리=오브젝트 스토리지(S3), **매니페스트/메타=제어 메타 저장소(RDS)** — 읽기 측(U7 full-text/paper API)이 RDS 조회 후 S3 서명 URL 발급. 구체 테이블·스키마는 NFR/Infra. |

### 포트 (개념 — Q5=A)

| 포트 | 시그니처(개념) | 비고 |
|---|---|---|
| **AssetStorePort** | `put_asset(asset_binary) -> ObjectRef` · `put_manifest(AssetManifest)` · `replace_assets(paperId, version)`(CHANGED stale 교체) · `remove_assets(paperId)`(tombstone) | **신규 분리 포트**(단일 책임), `FullTextStorePort`와 별개. OA 게이트(BR-1)·SEC-9 공개 차단 동일. 바이너리→S3, 매니페스트/메타→RDS(Q6=A). |

> `ParsedPaper`에 **`assets?: FigureTableAsset[]`**(디스크립터 — 바이너리+메타) 필드가 추가된다(parse 산출, §2 표 보강). 저장은 dedup 이후 NEW\|CHANGED만(business-logic §6, Q1=A).

> 결정·검증 규칙은 `business-rules.md`, 오케스트레이션은 `business-logic-model.md`.
