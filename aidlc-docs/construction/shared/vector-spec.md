# shared/vector-spec — 임베딩·인덱스 공용 계약 🔒 FROZEN

**상태**: 🔒 FROZEN (U1 FD/NFR 완료로 동결) · **일자**: 2026-06-16
**근거**: U1 `nfr-requirements`(TD-3 임베딩·TD-4 스토어) · U1 `functional-design`(IndexRecord·ChunkId·BR-3/4/6) · `component-dependency.md`(U1 writer ↔ U2 reader 동일 공간)
**불변식**: **U1.VectorIndexWriter(단일 writer)가 쓰고 U2.HybridRetriever(단일 reader)가 읽는** 동일 임베딩 공간. writer·reader는 **동일 `specVersion`·`model`·`dimensions`·`distanceMetric`·`normalize`** 소비.

---

## 1. 임베딩 계약 (Embedding Contract)
| 항목 | 값 | 비고 |
|---|---|---|
| `specVersion` | `v2` | 변경 = 전체 재임베딩(단방향). v1→v2는 Cohere v3→v4 전환 |
| `model` | **Cohere Embed v4** (Bedrock) | cross-lingual(한국어 질의 ↔ 영어 코퍼스), TD-3 |
| `dimensions` | **1024** | OpenSearch k-NN 인덱스 차원과 일치(ANN 호환 게이트) |
| `distanceMetric` | **cosine** | 정규화 임베딩; OpenSearch `space_type: cosinesimil` |
| `normalize` | true | Cohere 정규화 벡터 |
| **`inputType` (비대칭)** | **writer=`search_document` · reader=`search_query`** | Cohere 필수 파라미터 — **U1은 문서 임베딩, U2는 질의 임베딩**. 불일치 시 검색 품질 저하(같은 모델이라도). |

> **저하 모드(NFR-C1/US-R2)**: 비용 서킷 OPEN 시 U2는 임베딩 생략·lexical-only 폴백 → 그때도 인덱스의 `title`/`abstract`/`lexicalTerms` analyzed 필드(아래 §2)로 동작. 임베딩 공간 자체는 불변.

## 2. IndexRecord 스키마 (공유 인덱스 문서 — 청크당 1 레코드)
U1이 쓰고 U2가 읽는 인덱스 문서. **논문당 다수 청크 레코드**(Q2=C 전문 다중 청크).

| 필드 | 타입 | 출처/의미 | 트레이스 |
|---|---|---|---|
| `chunkId` | string | `chunkId(paperId, ordinal)` 결정적 — **인덱스 문서 ID(멱등 upsert 키)** | BR-5/9, PBT P2/P3 |
| `paperId` | string | 버전 없는 arXiv ID(정규 식별자) | BR-3 |
| `version` | int | arXiv vN(현재 인덱싱된 버전) | BR-3/14 |
| `vector` | float[1024] | 청크 임베딩(cosine, search_document) | §1 |
| `section` | string | 청크 출처 섹션(초록/본문 섹션) | BR-5 |
| `lexicalTerms` | text(분석됨) | **청크 본문 전용 lexical 필드**(하이브리드 FR-2). 제목과 초록은 기존 `title`/`abstract` analyzed 필드에 한 번만 저장하고, U2 lexical reader는 `title` + `abstract` + `lexicalTerms`를 함께 조회한다. boost 튜닝은 검색 품질 단계로 미루되 재색인 없이 쿼리 변경으로 적용 가능 | BR-6 |
| **카드 필드** (FR-4) | | U2 결과 카드 직접 매핑(→ `ResultCardVM`, dtos.md §1.1) | |
| · `title` | string | 논문 제목 | FR-4 |
| · `authors` | string[] | 저자 | FR-4 |
| · `year` | int | 게재 연도 | FR-4 |
| · `arxivId` | string | 표시용 arXiv ID(버전 포함 가능) | FR-4 |
| · `abstract` | string | 전체 초록(스니펫 산출 원본) | FR-4/5 |
| · `abstractSnippet` | string | 카드용 스니펫(파생) | FR-4 |
| · `arxivUrl` | string | **해소 가능 실재 링크**(FR-5 근거화 — 날조 금지) | FR-4/5 |
| `categories` | string[] | arXiv 카테고리(슬라이스 cs.LG/cs.AI/cs.CL/cs.CV/stat.ML) | C-6 |
| `doi` | string? | 알려진 DOI alias. 내부 keyword이며 외부 DTO에는 노출하지 않는다. DOI/arXiv/title canonical alias 보정과 후속 lookup에 사용한다. | BR-C4 |
| `sourceArxivId` | string? | 외부 source가 제공한 arXiv alias. `paperId`가 `src-*`인 DOI 기반 record에서도 실제 arXiv 표시/alias를 보존한다. 내부 keyword이며 외부 DTO에는 직접 노출하지 않는다. | BR-C4 |
| `sourceProvenance` | object? | `sourceName`, `sourceId`, `sourceTier`, `sourceUrl`, `doi`, `arxivId`. 검색 record 내부 lineage이며 OpenSearch에서는 non-indexed object로 저장한다. | BR-C4/11 |

> **근거화 전제(FR-5)**: 모든 노출 결과는 이 레코드(실재 arXiv ID/링크)에 매핑. U6.GroundingEnforcementHook(ports.md)가 응답 엣지에서 검증.

## 3. 인덱스/검색 계약 요건 (스토어 = OpenSearch, TD-4)
- **ANN**: `vector` 1024차원 k-NN(cosine). **Lexical**: `title`/`abstract`/`lexicalTerms` analyzed 필드. `lexicalTerms`는 청크 본문만 저장하며, 제목/초록은 표시 필드를 검색 필드로 재사용해 중복 저장을 피한다. **하이브리드 검색**(FR-2)은 ANN과 lexical 결과를 병합(U2.HybridRetriever). 필드별 boost 값은 검색 품질 단계에서 쿼리만 변경해 적용한다.
- **Alias/provenance**: `doi`와 `sourceArxivId`는 keyword alias로 저장한다. `sourceProvenance`는 근거/운영 디버깅용 원천 lineage이며 검색하지 않는다(`enabled=false`).
- **per-paperId 멱등 삭제/tombstone**(BR-14): `paperId` 기준 전 청크 삭제 가능해야 함(버전 단조 가드는 제어평면, logical-components §3.3).
- 인덱스명·샤드·레플리카·구체 매핑 JSON은 **Infra Design**.

## 4. 동일-공간 불변식 (writer ↔ reader) 및 런타임 호환성 게이트
- U1.EmbeddingGatewayAdapter(`embedBatch`, search_document)와 U2.QueryUnderstandingExpander(`expand`, search_query)는 **동일 `specVersion`·`model`·`dimensions`·`distanceMetric`·`normalize`** 사용.
- **PIN 소유권과 런타임 검증**: VectorSpec의 초기 PIN은 U1(빌드 #1)이 설정하지만, 이후 계약은 **공유 임베딩 게이트웨이 레이어**가 소유한다. 공유 Python 계약의 `assert_same_space()`는 `specVersion`뿐 아니라 `model`·`dimensions`·`distanceMetric`·`normalize`까지 비교한다. U1/U2 배포와 candidate index 검증은 이 동일-공간 검사를 통과해야 하며, per-record `modelVer` 필드는 현 FROZEN IndexRecord 계약에 포함하지 않는다.
- `specVersion` 불일치 또는 model/dim 변경 → **인덱스 비정합**(검색 무효) → **전체 재임베딩 필수**. 이 경우 `RefreshScheduler.triggerFullRebuild`를 통해 새로운 빈 candidate index로 재구축하고 검증 후 alias를 전환한다.
