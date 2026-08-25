# DocSuri

**논문을 근거로 답하는 연구 보조 서비스.** 검색해서 목록을 주는 것이 아니라, 질문에
**문헌 근거를 붙여 조건부 판단까지** 답한다.

라이브: **https://docsuri.shop** — 데모 배포(로드맵 ⑪, Lightsail 단일 인스턴스)

```
질문 ─▶ 코퍼스 검색 ─▶ 논문 본문 확보 ─▶ 근거 추출 ─▶ 게이트 ─▶ 판단
                 └─ 코퍼스에 없으면 arXiv·S2·OpenAlex 실시간 조회
```

파이프라인 전체는 [`pipeline.md`](pipeline.md)에 있다 — 모듈 4개의 대표 경로를 코드 상수 그대로
따라간다.

---

## 무엇이 다른가

**답이 근거를 못 대면 답을 안 낸다.** 근거 추출과 답변 사이에 결정론 게이트가 있다.

- 인용한 문장이 **원문에 실재하는지** 대조한다(span 검증). 없으면 그 근거를 떨어뜨린다.
- 문장의 **숫자가 근거에 있는지** 본다. 없으면 인용 표시를 잃는다(강등).
- 근거에 **없는 논문**이 답변에 등장하면 답변 전체를 물린다(거부 → 1회 재생성 → 폴백).

**"모르겠다"를 말한다.** 근거를 못 찾으면 지어내지 않고 기권 사유와 다음 행동을 낸다.

**반대 측을 찾아본 뒤에 끝낸다.** 주장·비교형 질문은 `stance=counter` 탐색이 실제로 1회 이상
돌아야 정상 종료를 인정한다 — 프롬프트 당부가 아니라 도구 인자라 트레이스에서 기계로 세어진다.

---

## 모듈

사용자 대면 경로에 있는 넷이다. 각 모듈은 자기 lane에서 따로 검사된다.

| | 모듈 | 하는 일 |
|---|---|---|
| **U1** | `ingestion/` | arXiv 수집 → 파싱(ar5iv HTML → PDF/GROBID) → doc-model → 청킹·임베딩 → 색인 |
| **U2** | `backend/modules/discovery/` | 하이브리드 검색(k-NN + BM25 → RRF → 리랭크), 근거 없는 결과 차단 |
| **U7** | `backend/modules/summarization/` | 요약·번역(map-reduce), 앵커 검증, 개인 용어집 |
| **U11** | `backend/modules/evidence/` | 근거형성 에이전트 — LangGraph 루프, 도구 6종, 판단 층 |

나머지(계정·라이브러리·마이페이지·인용 그래프·개인화·운영·신규성)는 같은 app-shell에 마운트된다.

---

## 스택

| | |
|---|---|
| 백엔드 | Python 3.11 · FastAPI · SQLAlchemy · **모듈러 모놀리스**(헥사고날 포트/어댑터) |
| 프론트 | Next.js(App Router) · TypeScript · **폰 우선** |
| 저장소 | PostgreSQL · Redis · S3 · **OpenSearch**(k-NN + BM25) |
| 모델 | Amazon Bedrock — 임베딩 Cohere embed-v4 · 리랭크 Cohere rerank-v3.5 · LLM Claude |
| 에이전트 | LangGraph(체크포인터 = Postgres) |
| 배포 | Lightsail 단일 인스턴스 + Caddy(TLS) — `ops/deploy/` |

**DTO는 한 곳에서 생성된다** — `shared/dtos/*.schema.json`이 정본이고 파이썬·타입스크립트 타입이
거기서 나온다. 스키마와 코드가 갈리면 CI가 잡는다.

---

## 로컬에서 띄우기

```bash
set -a && . ./.env && set +a          # 반드시 먼저 — 빠지면 s3proxy가 안 뜬다
docker compose -f backend/docker-compose.yml up -d postgres opensearch s3proxy redis elasticmq
./dev.sh                              # 백엔드(:8000) + 프론트(:3000)
```

`.env` 소스가 빠지면 **s3proxy가 아예 안 뜬다.** 일부러 그렇게 해뒀다 — 예전에는 기본값으로
개발 코퍼스가 조용히 마운트됐고, 컨테이너는 healthy로 뜨고 S3 API도 정상 응답해서 어디에도
오류가 안 보였다. 배치는 대상 논문의 대부분을 "없음"으로 건너뛰고 exit 0을 냈다.

파싱할 때만 GROBID를 올린다(`--profile ingest`) — 메모리를 많이 써서 Docling과 동시에 뜨기 어렵다.

## 검사

패키지마다 자기 lane이 있다. CI와 같은 명령이다.

```bash
uv run --project backend pytest tests -c pytest.ini      # 루트 tests/ (U3·U4)
cd backend                       && uv run ruff check . && uv run pytest
cd backend/modules/discovery     && uv run ruff check . && uv run pytest
cd backend/modules/summarization && uv run ruff check . && uv run pytest
cd ingestion                     && uv run ruff check . && uv run pytest
uv run --project backend ruff check backend/modules tests   # evidence 린트는 여기

cd frontend && pnpm exec tsc --noEmit && pnpm run lint && pnpm exec vitest run \
            && pnpm run gen:types && git diff --exit-code types/ \
            && pnpm exec next build
```

두 가지가 조용히 어긋난다.

**`backend`에서 `ruff check .`는 `modules/`를 안 본다**(`extend-exclude`). 모듈은 자기 lane에서
따로 린트된다 — 셸에서 한 번 돌리고 "전부 통과"로 읽으면 안 된다.

**프론트는 `next build`까지 돌려야 한다.** `tsc`도 `vitest`도 **CSS 모듈을 컴파일하지 않는다** —
vitest는 클래스명을 아이덴티티로 목한다. 그래서 CSS 모듈의 오류(없는 클래스 참조, `composes`
순서)는 셋 다 초록인 채 빌드에서만 터진다. 실제로 그렇게 CI를 깼다(2026-08-26).

---

## 문서

| | |
|---|---|
| [`pipeline.md`](pipeline.md) | 모듈 4개의 대표 경로 — 코드 상수 그대로 |
| [`CONVENTIONS.md`](CONVENTIONS.md) | 브랜치·커밋·PR 규약 |
| [`CLAUDE.md`](CLAUDE.md) | 저장소를 훑어서는 안 보이는 규칙 |
| [`aidlc-docs/`](aidlc-docs/) | 설계 결정의 정본 — 요구사항·질문지·유닛별 설계 |
| [`ops/deploy/README.md`](ops/deploy/README.md) | 배포 런북 |
