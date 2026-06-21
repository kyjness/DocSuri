# 0장. DocSuri 프로젝트 구성 (전체 토대)

> 학습용 메모. **커밋하지 않는다.** 근거: 리포 실제 트리 + `backend/wiring.py` + 각 모듈 코드.
> 형식: **용어는 코드/문서 그대로 쓰고**, 옆에 괄호·설명으로 뜻을 단다.
> 목적: "검색이 OpenSearch에서 데이터를 가져온다"가 **코드상 어떤 경로로** 일어나는지 보이게 하는 토대.

---

## 1. 한 문장 요약

DocSuri는 **모노레포(monorepo)** = 한 git 저장소 안에 여러 유닛(U1~U7)이 같이 들어있는 구조다. 각 유닛은 각자 부품으로 나뉘어 있고, `backend/`의 **앱셸(app-shell)** = "로직 없는 뼈대 앱"이 그 부품들을 **선택적으로 마운트(mount = 끼워 넣음)** 해서 하나의 FastAPI 백엔드로 묶는다. 각 유닛은 **포트/어댑터(ports & adapters)** 구조라 "순수 로직"과 "외부 인프라(OpenSearch·Bedrock·S3…)"가 분리돼 있다. (이 세 용어는 아래서 하나씩 푼다.)

---

## 2. 디렉터리 지도 (top-level)

```
DocSuri/
├── backend/          ← FastAPI 앱셸 + 백엔드 유닛들의 마운트 지점
│   ├── app.py        ← FastAPI 앱 생성 (create_app)
│   ├── main.py       ← 실행 진입점
│   ├── config.py     ← 환경설정(Settings)
│   ├── wiring.py     ← ★유닛 모듈을 앱에 끼우는 곳(mount_modules)
│   └── modules/
│       ├── accounts/      (U3 인증)
│       ├── discovery/     (U2 검색)
│       ├── library/       (U4 저장·이력)
│       ├── summarization/ (U7 요약)
│       └── ops/           (U6 운영 대시보드/인시던트)
├── ingestion/        ← U1 색인 워커 (사용자 요청 경로 밖, 별도 프로세스)
├── frontend/         ← U5 Next.js 폰 UI
├── ops/              ← U6 IaC(AWS CDK) + 운영 워커
├── shared/           ← ★유닛 간 "계약"의 단일 출처(SSOT)
│   ├── dtos/         ← 요청/응답 JSON 스키마 (DTO = Data Transfer Object, 주고받는 데이터 모양)
│   ├── events/       ← 비동기 이벤트 스키마(SearchExecuted 등)
│   ├── vector-spec/  ← 임베딩 공간 규격 + IndexRecord 스키마
│   └── python/       ← 위 스키마로 생성된 파이썬 패키지 `docsuri_shared`
├── aidlc-docs/       ← AI-DLC 방법론 산출물(기획·설계 문서)
└── tests/
```

**유닛 ↔ 코드 위치 매핑** (헷갈리기 쉬움):

| 유닛 | 코드 위치 | 비고 |
|---|---|---|
| U1 Ingestion | `ingestion/` | 별도 워커 프로세스 (백엔드 앱 아님) |
| U2 Discovery | `backend/modules/discovery/` | `discovery` 패키지로도 import |
| U3 Accounts | `backend/modules/accounts/` | |
| U4 Library | `backend/modules/library/` | |
| U5 Frontend | `frontend/` | 별도 Next.js 앱 |
| U6 Reliability/Ops | `backend/modules/ops/` + `ops/` + `docsuri_ops` 패키지 | 게이트웨이·근거화·비용가드 단일 권위 |
| U7 Summarization | `backend/modules/summarization/` | |

> **앱셸(app-shell)** 더 풀면: 공통적인 것(미들웨어·에러 처리·헬스체크)만 가진 뼈대 앱 + "여기에 유닛을 꽂으세요" 하는 빈 자리. 유닛 하나가 고장 나도(또는 아직 안 만들어졌어도) **그 유닛만 건너뛰고** 앱은 산다. → 모듈 하나가 전체를 침몰시키지 않게.

---

## 3. 한 유닛의 내부 구조 (포트/어댑터 = 핵심 패턴)

U2를 예로, `backend/modules/discovery/src/discovery/` 안은 **역할별 폴더**로 나뉜다:

```
discovery/
├── domain/      ← 순수 로직. 외부 I/O(입출력) 없음. (validator, expander, retriever, ranker…)
├── ports/       ← "인터페이스"만. 어떤 외부 능력이 필요한지 선언 (search_ports.py)
├── adapters/    ← 그 인터페이스의 "실제 구현". OpenSearch·Bedrock 호출 (opensearch_index.py…)
├── cache/       ← 임베딩 캐시 (어댑터를 감싸는 데코레이터)
├── service/     ← 오케스트레이터. domain 조각들을 순서대로 호출 (orchestrator.py)
├── api/         ← FastAPI 라우터 + gateway_seam (HTTP ↔ 도메인 연결)
├── mocks/       ← 인프라 없이 돌리는 가짜 어댑터 + 그 배선(wiring)
└── real_wiring.py ← 진짜 어댑터로 배선
```

### 포트와 어댑터가 뭐냐

- **포트(port)** = "나는 이런 능력이 필요해"라는 **계약(인터페이스)**. 예: `VectorStoreAdapter`는 "`knn_search(벡터, top_k)`를 주면 결과를 돌려준다"는 약속만 정의. *어떻게* 하는지는 모름.
- **어댑터(adapter)** = 그 약속의 **실제 구현체**. 예: `OpenSearchVectorStoreAdapter`는 실제로 OpenSearch에 쿼리를 던진다.
- 도메인 로직(`retriever.py`)은 **포트만 알고 어댑터는 모른다.** 그래서 같은 로직에 **진짜 OpenSearch** 어댑터든 **가짜(mock)** 어댑터든 그대로 꽂을 수 있다 → 인프라 없이 개발·테스트 가능. 이게 **mock-first**(처음부터 가짜로 돌려보며 개발).

> 핵심: "두 검색을 발행한다"(retriever)는 *포트를 호출*하는 것이고, **진짜 데이터를 어디서 가져오는지는 그때 꽂힌 어댑터**가 정한다. `real_wiring.py`에서 OpenSearch 어댑터가 꽂히면 → 실제 `docsuri-corpus-v1` 인덱스에서 가져온다.

---

## 4. 의존성 주입(DI) + 배선(wiring) — 조립이 일어나는 곳

도메인은 자기가 쓸 어댑터를 **직접 만들지 않는다.** 누군가 **생성자에 넣어준다** — 이걸 **의존성 주입(DI = Dependency Injection)** 이라 한다. 그 "넣어주는" 코드가 `*_wiring.py`(배선).

```python
# real_wiring.py — 진짜 어댑터를 골라 오케스트레이터에 주입
orchestrator = SearchOrchestrationService(
    validator = QueryValidator(),
    expander  = QueryUnderstandingExpander(cache),       # cache는 Bedrock 임베더를 감쌈
    retriever = HybridRetriever(
        OpenSearchVectorStoreAdapter(client, "docsuri-corpus-v1"),  # k-NN
        OpenSearchLexicalIndexAdapter(client, "docsuri-corpus-v1"), # BM25
    ),
    ranker = RelevanceRanker(),
    ...
)
```

`mocks/wiring.py`는 같은 자리에 **가짜 어댑터**를 넣는다. 오케스트레이터(로직)는 한 글자도 안 바뀐다 — 이게 "mock ↔ real 교체가 로직을 안 건드린다"의 의미.

---

## 5. 앱셸이 유닛을 끼우는 법 (`backend/wiring.py`)

`mount_modules()`가 유닛을 **하나씩 선택적으로** 마운트한다. 모듈이 아직 없거나(브랜치 미병합) 설정이 안 됐으면 **그 유닛만 skip(건너뜀)** 하고 나머지는 정상. 예:

- discovery: 환경변수에 OpenSearch+Bedrock가 설정돼 있으면 `build_real_orchestrator`(진짜), 아니면 `build_mock_orchestrator`(가짜).
- summarization(U7): S3 버킷이 설정됐을 때만 마운트(real-first = 진짜 우선, 가짜 배선 없음).

그리고 앱셸은 **U6 단일 권위 3종**(근거화 훅·비용 가드·관측 허브)을 만들어 각 유닛에 **주입**한다. 그래서 U2/U7은 그걸 *호출만* 하고 재구현하지 않는다.
- **단일 권위(single authority)** = "이 기능은 한 곳만 진짜로 가지고 나머지는 빌려 쓴다." 같은 정책을 여러 군데서 따로 구현하면 한 곳만 고쳐지는 사고가 나서, 한 곳에 몰아둔다.

---

## 6. shared/ = 유닛 간 계약의 단일 출처(SSOT)

- **SSOT** = *Single Source Of Truth*, "하나의 진실 출처". 유닛끼리 주고받는 데이터 모양을 **여러 군데 따로 적지 않고** 한 곳(`shared/`)에만 정의한다.

유닛들이 데이터를 주고받을 때 **모양이 어긋나면** 안 되니까, 그 모양을 `shared/`에 JSON 스키마로 한 번만 정의하고 → 거기서 파이썬 타입(`docsuri_shared`)을 **생성**한다. 주요 계약:

- `IndexRecord` (`vector-spec`) — OpenSearch에 저장된 **한 청크(chunk = 논문 조각)의 모양**. U1이 이 모양으로 쓰고(writer), U2가 이 모양으로 읽는다(reader).
- `SearchRequest` / `SearchResponse` (`dtos`) — 검색 요청/응답.
- `SearchExecutedEvent` (`events`) — 검색 후 U4로 보내는 이력 이벤트.
- `vector-spec` 상수 — 임베딩 모델/차원(1024)/거리(cosine)가 writer·reader 동일해야 한다는 **불변식(invariant = 항상 지켜야 하는 약속)**.

---

## 7. 요청 한 건이 흐르는 큰 길 (U2 기준)

```
[U5 브라우저] → [U6 게이트웨이: 인증·rate-limit] → backend 앱
   → discovery 라우터(POST /api/search)            api/router.py
   → gateway_seam.run_search                        api/gateway_seam.py
       → orchestrator.plan_and_retrieve  (① ~ ⑥)        service/orchestrator.py
       → grounding_hook.enforce          (⑦ 근거화 = U6 단일 권위)
       → orchestrator.finalize           (⑧ 조립 + ⑨ 이력 발행)
   → JSONResponse → 다시 게이트웨이 → 브라우저
```

- **게이트웨이(gateway)** = 모든 요청이 통과하는 길목. 여기서 인증·횟수제한 등을 검문. (U6 소유.)
- **seam** = "이음매". 도메인 코어와 바깥(게이트웨이)이 만나는 경계 지점. ⑦ 근거화가 여기서 끼어든다.

이 길 위에서 **도메인 로직(orchestrator)** 은 ①~⑥과 ⑧⑨를 하고, **⑦ 근거화만 바깥(게이트웨이 seam)** 에서 끼어든다. 이 "두 동강" 구조가 U2의 제일 중요한 설계다 — 자세한 건 `u2-discovery.md`.

---

→ 이 토대를 깔았으니, 각 유닛 파일에서 ①~⑨를 데이터 출처까지 따라간다.
```
