# U2 Discovery — 검색 파이프라인 (용어 풀이 + 데이터 출처)

> 학습용 메모. **커밋하지 않는다.** 근거: `backend/modules/discovery/src/discovery/` 실제 코드 + `shared/`.
> 형식: 단계마다 **[받음] → [함] → [내보냄]**. **용어는 코드/문서 그대로 쓰고**, 옆에 괄호·설명으로 뜻을 단다. "어디서 가져오는지"(실물 쿼리·상수)까지.
> 먼저 `00-project-overview.md`(포트·어댑터·배선)를 읽었다고 가정.

---

## 이 유닛이 하는 일 (한 문단)

사용자가 검색어를 넣으면, **U1이 미리 채워둔 OpenSearch 인덱스**를 뒤져서 관련 논문 카드를 돌려준다. 단어 매칭만 하는 게 아니라 **의미가 비슷한 논문도** 같이 찾고(k-NN), 두 방식 결과를 RRF로 합쳐 순위를 매기고, "없는 논문을 지어낸 건 아닌지" enforce 검사까지 받은 뒤 화면에 내보낸다. 아래 ①~⑨가 그 순서다.

---

## 0. 먼저 알아야 할 것 — 검색 대상의 모양 `IndexRecord`

OpenSearch 인덱스 `docsuri-corpus-v1`에는 논문이 **통째로가 아니라 청크(chunk) 단위**로 들어있다.
- **청크(chunk)** = 긴 논문을 일정 길이로 자른 한 조각. 논문 1편 = 청크 여러 개. (검색·AI 처리는 너무 긴 텍스트를 한 번에 못 다뤄서 자른다. 자르는 건 U1이 함.)

청크 하나의 생김새가 `IndexRecord`다 (`shared/vector-spec/index-record.schema.json`):

| 필드 | 뜻 | 검색에서 쓰임 |
|---|---|---|
| `chunkId` | 청크 고유 ID (paperId + 순번) | 인덱스 문서 키 |
| `paperId` | 버전 뗀 arXiv 논문 번호 | **디덥(중복제거) 기준** |
| `version` | 색인된 논문 버전 (v1, v2…) | |
| `vector` | 청크 임베딩 (1024개 숫자) | **k-NN이 보는 필드** |
| `lexicalTerms` | 제목+초록+본문의 단어들 | **BM25가 보는 필드** |
| `section` | 이 청크가 논문 어느 절에서 왔나 | 내부용(화면 비노출) |
| `title` `authors` `year` `arxivId` `abstractSnippet` `arxivUrl` | **카드 7필드** (화면 표시용) | ⑧에서 사용 |
| `abstract` `categories` | 전체 초록 / 분야 | 내부용 |

**핵심 한 줄**: 검색은 `vector`(의미)와 `lexicalTerms`(단어) **두 필드를 두 방식으로** 뒤지고, 최종 카드는 **같은 레코드의 7필드**만 보여준다. 내부 점수(raw score)는 화면에 안 나간다 — **SEC-9**(이 프로젝트의 보안 규칙 번호: "내부 정보를 사용자에게 노출하지 않는다") 때문.

---

## 진입: 요청이 어떻게 도메인 코어에 닿나

`POST /api/search`가 들어오면 (`api/router.py`):
- U6 게이트웨이가 미리 넣어둔 **principal**(= 이 요청의 주인 정보: user_id·role 등)에서 `user_id`를 꺼낸다. 없으면 개발용 헤더 `x-user-id` 사용 (실제 인프라 없이 돌려보는 mock-first 개발 때문).

그다음 `api/gateway_seam.py`가 검색을 **두 토막으로 끊어서** 부른다:

```python
outcome = orchestrator.plan_and_retrieve(request, ctx)   # ① ~ ⑥ (검색까지)
if outcome.response is not None:
    return outcome.response                              # 검증실패·무결과면 여기서 끝
decision = grounding_hook.enforce(                        # ⑦ enforce (U6 담당)
    outcome.pending.grounding_input.candidate_response,
    outcome.pending.grounding_input.retrieved_records,
)
return orchestrator.finalize(outcome.pending, decision)   # ⑧ ⑨ (조립·발행)
```

→ 왜 두 토막? **검색하는 코드(U2)와 "지어냄을 검열하는 코드(U6의 enforce)"의 권한을 분리**하려고. 메서드를 `plan_and_retrieve` / `finalize`로 갈라놔서, U2 코드가 enforce를 **마음대로 못 부르게** 구조로 막았다(INV-1 = 불변식 1번). 검열 권한은 U6 한 곳에만. (자세한 건 ⑦.)

---

## ① validate / normalize — 검색어 검증·정규화 (`domain/validator.py`)

**[받음]** 사용자가 친 원본 쿼리 (예: `"  그래프  신경망 추천 "`).

**[함]** 검색에 쓰기 전에 검증 4종 + 정규화 2종.

**검증 4종:**
1. **문자열 타입** — 쿼리가 진짜 문자열인지 확인, 숫자·객체면 거부. (API를 코드로 직접 호출하면 엉뚱한 타입이 올 수 있어서.)
2. **제어문자 거부** — 화면엔 안 보이는데 시스템을 꼬이게 하는 문자(`\x00`~`\x1f` 등 *제어문자* = 출력용이 아니라 제어용 특수문자)를 거부. 단 탭·줄바꿈(`\t \n \r`)은 허용.
3. **정규화 후 빈 값** — 공백만 친 입력은 정규화하면 빈 문자열 → 입력 오류 처리.
4. **길이 제한** — 500자 초과 거부 (`MAX_QUERY_LEN=500`).

**정규화 2종:**
- **NFC 정규화** — `NFC` = 유니코드를 하나의 표준 형태로 통일하는 방식. **같은 글자도 컴퓨터는 다르게 저장할 수 있다** (예: "각"을 한 글자 통째로 저장 vs `ㄱ+ㅏ+ㄱ` 자모 조합으로 저장 → 눈엔 같지만 저장값은 다름). 안 통일하면 같은 쿼리인데도 캐시 미스(=캐시를 못 맞힘)가 나거나 결과가 달라진다.
- **공백 정리** — 연속 공백을 1칸으로, 앞뒤 strip.

```python
text = unicodedata.normalize("NFC", raw_query)
text = _WHITESPACE.sub(" ", text).strip()   # "  그래프  신경망 추천 " → "그래프 신경망 추천"
```
- 정규화는 **멱등(idempotent)** — 이미 정리된 걸 또 돌려도 안 바뀜 (= 같은 입력이면 항상 같은 출력).

**[내보냄]** 실패 → **HTTP 400**으로 종료. 성공 → 정규화된 문자열.
- 같은 검증을 **U6 게이트웨이도** 한다 (이중 방어, 코드 주석 "Mirrored at the U6 gateway"). 화면(U5)도 가볍게 하지만, 화면 검증은 우회 가능해서 서버가 다시 한다.

---

## ② degrade — 비용 상태 보고 "저하 여부" 결정 (`orchestrator._derive_degradation`)

**[받음]** (쿼리 아님) U6의 비용 상태.

**[함]** U6에 `cost_guard.get_budget_state()`로 **현재 저하 모드**를 물어 **읽기만** 한다(U2는 비용 판단 안 함). 받은 모드로 내부 스위치 2개를 조정:

| U6 모드 | `llm_enabled` | `rerank_enabled` | 효과 |
|---|---|---|---|
| `normal` | True | True | 정상 (하이브리드) |
| `rerank-off` | True | False | U2엔 무영향 (원래 리랭킹 없음 → no-op) |
| `lexical-only` | **False** | False | **임베딩 생략, BM25만** |

- **저하(degrade)** = 돈·부하가 클 때 기능을 **일부러 낮춰** 서비스가 죽는 대신 "조금 덜 좋게라도 계속 돌게" 하는 것.

**[내보냄]** 저하 모드 + `DegradationSignal`. 이 신호가 ③·⑤의 동작을 바꾼다.
- 비용 한도(cap $1600)와 단계 기준(사용률 0.80/0.95/1.0)은 **U6 소유**, U2는 결과만 읽음. (U6 학습에서 자세히.)

---

## ③ expand — 쿼리를 검색 재료로 (`domain/expander.py` + `cache/embedding_cache.py`)

**[받음]** 정규화 쿼리 + ②의 신호.

**[함]** "검색 계획(QueryPlan)"을 두 재료로 만든다:
- **lexical terms** (= BM25에 쓸 단어 목록): `query.lower().split()` → `("그래프","신경망","추천")`. **동의어 확장·LLM 재작성 없음** (검색이 매번 똑같아야 해서 — 이걸 *결정적(deterministic)* = 같은 입력이면 항상 같은 출력, 이라 함).
- **query embedding** (= k-NN에 쓸 벡터): `llm_enabled=True`일 때만 생성.
  - **임베딩(embedding)** = 텍스트의 *의미*를 숫자 벡터(여기선 1024차원 = 숫자 1024개)로 바꾼 것. 의미가 비슷하면 벡터가 가깝다 → 단어가 안 겹쳐도 뜻이 비슷한 논문을 찾을 수 있다.

**[실물 — 임베딩을 어디서 가져오나]**
expander에 꽂힌 임베더는 사실 **EmbeddingCache(캐시)를 한 겹 두른 것**:
```
QueryUnderstandingExpander(cache)
  └ cache = EmbeddingCache(BedrockCohereQueryEmbedder)
```
- `cache.embed_query(text)` → **정규화 쿼리 문자열을 키**로 메모리 사전(dict)을 먼저 조회.
  - **HIT**(TTL 내) → Bedrock 호출 생략, 저장된 벡터 반환.
  - **MISS** → 진짜 AWS Bedrock 호출 → 결과를 사전에 저장.
  - **TTL** = *Time To Live*, 저장값의 유효시간. 만료 없는 키 금지. (`max_entries=1024`, 가득 차면 오래된 것부터 *evict*=내보냄.)
- 진짜 호출의 실제 요청 body:
  ```python
  body = {
    "texts": [text],
    "input_type": "search_query",   # ★검색하는 쪽은 query, 저장하는 쪽(U1)은 document
    "embedding_types": ["float"],
  }
  client.invoke_model(modelId=<Cohere Embed Multilingual v3>, body=...)
  ```
  - **input_type 비대칭** — 같은 모델(Cohere v3)이라도 **쿼리는 `search_query`, 저장될 논문은 `search_document`로** 임베딩한다. 모델이 "질문"과 "문서"를 구분해 더 잘 매칭하게 설계돼서. (U1이 `search_document`로 넣은 걸 U2가 `search_query`로 찾는다.)
- 반환 벡터가 1024차원이 아니면 → **설정 오류로 요란하게 실패** (쿼리와 인덱스가 다른 임베딩 공간이면 검색이 무의미해서. 일시 장애와 구분).

**[내보냄]** `llm_enabled=True` → `mode=HYBRID`(벡터+단어), False → `LEXICAL_ONLY`(단어만).
- **갈림길**: Bedrock 장애 → `EmbeddingUnavailable` → 죽지 않고 **lexical-only로 강등 후 재시도**. (임베딩 실패는 캐시에 저장 안 함.)

---

## ④ retrieve — 실제로 인덱스를 뒤지기 (`domain/retriever.py`) ★핵심

**[받음]** ③의 검색 계획.

### (1) 두 검색을 발행 — 각각 상위 `RETRIEVAL_TOP_K=50`

둘 다 **같은 인덱스 `docsuri-corpus-v1`의 다른 필드**를 때린다 (`adapters/opensearch_index.py`):

- **k-NN** (HYBRID일 때만) — `vector` 필드, 의미 유사:
  ```python
  body = {"size": 50, "query": {"knn": {"vector": {"vector": <쿼리벡터>, "k": 50}}}}
  ```
  - **k-NN** = *k-Nearest Neighbors*, "가장 가까운 k개". 벡터 공간에서 쿼리 벡터 근처 50개를 집어온다 (= 의미가 가까운 검색).

- **BM25** (항상) — `lexicalTerms` 필드, 단어 일치:
  ```python
  body = {"size": 50, "query": {"match": {"lexicalTerms": "그래프 신경망 추천"}}}
  ```
  - **BM25** = 전통적 키워드 검색 점수 방식. 쿼리 단어가 그 문서에 **자주** 나오고 + 그 단어가 **희귀**할수록 점수↑ (흔한 단어는 가중치 낮음).

- 각 hit의 `_source`를 그대로 `IndexRecord`로 역직렬화하고, 인덱스가 매긴 점수(`_score`)도 같이 들고 나온다 → `[(IndexRecord, score), ...]` 순위 순.

### (2) RRF 병합 (`_reciprocal_rank_fusion`)

두 리스트를 합치는데 **점수가 아니라 순위(rank)만** 쓴다.
- **왜 점수를 안 쓰나**: k-NN 점수(0~1 코사인)와 BM25 점수(수백)는 **스케일이 너무 달라서**, 그냥 더하면 BM25가 압도한다. 그래서 점수 대신 등수만 본다.
- **RRF** = *Reciprocal Rank Fusion*, "역순위 합산". 앞 등수일수록 큰 값을 주는 공식으로 두 리스트를 합친다:
  ```
  score(논문) = Σ(각 리스트)  1 / (RRF_K + 그 리스트에서의 0-based rank + 1)     # RRF_K=60
  ```
- *숫자 예시* — 논문 P가 k-NN 1등(rank 0), BM25 3등(rank 2)이면:
  ```
  score(P) = 1/(60+0+1) + 1/(60+2+1) = 1/61 + 1/63 ≈ 0.0164 + 0.0159 = 0.0323
  ```
  → 두 검색 모두 상위면 두 항이 더해져 점수↑. 스케일 무관·결정적.

### (3) 디덥 (중복 제거)

인덱스는 청크 단위라 **같은 논문이 여러 청크로** 잡힌다. `paperId` 기준 **처음 본 1개만** 유지.
- **디덥(dedup)** = *deduplication*, 중복 제거. 같은 논문 청크 여러 개 → 논문 1건.
- 정렬 `(-score, paperId)` (점수순, 동점은 paperId로 → 항상 같은 순서, 결정적).

**[내보냄]** 디덥된 후보 목록(`CandidateSet`).
**[갈림길 둘]**
- 후보 **0건** → `AbstainDTO("no_results")`, **HTTP 200**. — **abstain(기권)** = "결과 없음"을 가짜 빈 페이지로 주지 않고 "못 찾았다"고 명확히 알리는 것.
- 검색 **실패**(`IndexUnavailable`) → `SearchUnavailable` → **HTTP 503**. OpenSearch가 유일 저장소라 **폴백 없음 = fail-closed**. — **fail-closed** = 애매하거나 고장 나면 통과 말고 거부. (임베딩은 lexical 폴백 있지만 인덱스는 폴백 없음.)

---

## ⑤ rank — 상위 `TOP_N=20`으로 절단 (`domain/ranker.py`)

**[받음]** ④ 후보 목록.
**[함]** `(-RRF점수, paperId)`로 정렬해 **상위 20개만** 자른다. **LLM 리랭킹 없음**(baseline). 20개 미만이면 있는 만큼만.
- **리랭킹(rerank)** = 1차로 뽑은 결과를 다시(보통 LLM으로) 정렬해 품질을 올리는 단계. 여기선 안 씀 → 그래서 ②의 `rerank-off` 모드가 U2엔 no-op인 것.

**[내보냄]** `RankedResults` 최대 20개.

---

## ⑥ 근거 입력 구성 (`domain/grounding_adapter.to_grounding_input`)

**[받음]** ⑤ 랭킹 결과.
**[함]** ⑦ enforce에 넘길 입력을 **모양만** 만든다(검사는 안 함):
```python
retrieved = tuple(c.record for c in ranked.ranked)         # 실제 IndexRecord들
GroundingInput(candidate_response=ranked, retrieved_records=retrieved)
```
**[내보냄]** `GroundingInput` = (후보 응답 + 검사 대상 실제 레코드들). 여기서 `plan_and_retrieve`가 끝나고 제어가 게이트웨이 seam으로 올라간다.

---

## ⑦ enforce — 근거화 검사 (U6 `GroundingEnforcementHook`) ★단일 호출 지점

**[받음]** ⑥의 후보 + 실제 레코드.
**[함]** **U6의 enforce 훅**이 검사한다: 후보가 노출하려는 식별자(arxivId/paperId/arxivUrl)가 **실제 검색된 레코드 안에 존재하나?**
- **근거화(grounding)** = 시스템이 내놓은 결과가 실제 데이터에 뿌리를 두는지 확인하는 것. 없는 논문을 지어내는 *환각(hallucination)*을 막는다.
- **enforce** = 그 근거화를 "강제(검열)"하는 단계.
- 결과 3가지: 전부 실재 → `pass` / 날조 섞임 → `block` / 후보·레코드 없음 → `abstain`.

**[내보냄]** `GroundingDecision(verdict)`.

> **왜 U2 밖에서?** 검색(U2)과 날조 검열(U6)을 **권한 분리**. 메서드를 갈라놔서 U2가 enforce를 건너뛰거나 조작 못 하게 했다(INV-1). 검열관은 U6 하나뿐. (enforce 내부는 U6 학습에서.)

---

## ⑧ assemble — 카드로 조립 (`orchestrator.finalize` → `assembler.py`)

**[받음]** ⑦ verdict + ⑤ 랭킹.
**[함]**
- `map_decision`: `pass` → 랭킹 그대로. `block`/`abstain` → `AbstainResult`. (재계산 없이 매핑.)
- `assemble`:
  - Abstain → `AbstainDTO`.
  - Grounded인데 0건 → `AbstainDTO("no_results")` (가짜 빈 페이지 금지, BR-9 = 비즈니스 규칙 9번).
  - 정상 → 각 레코드를 **카드 7필드로 투영** (`title·authors·year·arxivId·abstractSnippet·relevance·arxivUrl`). `relevance`는 **1-based 표시 순위**, raw RRF 점수는 **비노출**(SEC-9).
  - 저하 모드면 `DegradedResultDTO(mode)`(배너용), 아니면 `SearchResultPageDTO`.

**[내보냄]** `SearchResponse` → **HTTP 200** (검증 실패만 400, 인덱스 장애만 503).

---

## ⑨ publish — 검색 이벤트 발행 (`orchestrator._publish`, 응답 후·비차단)

**[받음]** user_id, query, 결과 카드 수.
**[함]** `SearchExecutedEvent`를 만들어 발행. **fire-and-forget** — 던지고 잊음. try/except로 감싸 **발행이 실패해도 검색 응답엔 영향 0.**
- **fire-and-forget** = 결과를 안 기다리고 던지기만 하는 방식. 기록이 늦거나 실패해도 사용자 응답은 멀쩡.

**[실물]** 배선에 `search_event_bus` 설정 시 `EventBridgeEventPublisher`(AWS EventBridge), 아니면 `InMemoryEventPublisher`(개발). → **U4 Library가 비동기로 받아** `search_history`에 적재.
**[왜]** 이력 저장이 검색 레이턴시 예산(P50 < 3s = 응답 절반이 3초 안)을 잠식 못 하게 분리.

---

## 한 장 요약 (데이터 출처 강조)

```
쿼리 문자열
 ① validator    : NFC 정규화 + 검증 4종              (도메인, I/O 없음)
 ② cost_guard   : U6에서 저하모드 읽기               ← U6 (read-only)
 ③ expander     : 토큰화 + 임베딩 1024d              ← EmbeddingCache → Bedrock(Cohere v3, search_query)
 ④ retriever    : k-NN(vector) ∥ BM25(lexicalTerms) ← OpenSearch docsuri-corpus-v1 (각 top_k=50)
                  → RRF(k=60) 병합 → paperId 디덥
 ⑤ ranker       : 점수순 정렬 → top_n=20             (도메인)
 ⑥ grounding_adapter: enforce 입력 모양 만들기        (도메인)
 ─ gateway seam ─
 ⑦ enforce      : 근거화 검사 pass/block/abstain     ← U6 GroundingEnforcementHook (단일 권위)
 ⑧ assembler    : 카드 7필드 투영(raw점수 비노출)     → SearchResponse
 ⑨ publish      : SearchExecuted 비동기 발행          → EventBridge → U4
```

**갈림길 요약**: 임베딩 장애 → lexical 폴백(계속). 인덱스 장애 → 503(폴백 없음). 무결과·날조 → abstain(200). 검증 실패 → 400.
```
