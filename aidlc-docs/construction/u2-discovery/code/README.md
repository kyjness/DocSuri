# U2 Discovery — Code Generation 요약 (mock-first + real 어댑터)

**단계**: CONSTRUCTION → Code Generation · **유닛**: U2 Discovery · **트랙**: Track 3(@kyjness)
**근거**: `construction/plans/u2-discovery-code-generation-plan.md`(승인) · FD/NFR Req/NFR Design 산출물
**상태**: ✅ mock-first 생성 완료(2026-06-16) + ✅ **real 어댑터(OpenSearch/Bedrock) 추가·로컬 검증(2026-06-17, 브랜치 `feature/u2-v2`, 크리티컬 패스 ⑥)** · **테스트 43 passed(+1 skip) · 라이브 OpenSearch 통합 3 passed · ruff clean**

> 본 문서는 산출 코드의 **요약(마크다운)**이다. 애플리케이션 코드는 `backend/modules/discovery/`에 있다(aidlc-docs/ 아님).

---

## 생성 위치
- **애플리케이션 코드**: `backend/modules/discovery/` (Track 3 클린 레인)
- **문서**: 본 디렉터리(`aidlc-docs/construction/u2-discovery/code/`)

## 생성 파일 (Step 1~10)

| 영역 | 파일 | 책임 | 트레이스 |
|---|---|---|---|
| 구조 | `pyproject.toml` | 모듈 로컬(uv) — docsuri-shared path dep·pytest·hypothesis·api extra(fastapi) | CG-1 |
| 도메인 | `domain/models.py` | 내부 엔티티(NormalizedQuery·QueryPlan·Candidate·RankedResults·DegradeMode…) | — |
| 도메인 | `domain/validator.py` | 검증·NFC 정규화(다국어) | FR-1·SEC-5·BR-1/2·**PBT-02** |
| 도메인 | `domain/expander.py` | 임베딩(search_query)+lexical 확장; LLM 재작성 없음 | FR-2·BR-3·Q1=A |
| 도메인 | `domain/retriever.py` | k-NN∥BM25 → RRF → PaperId 디덥 | FR-2·BR-4·**PBT-07**·Q2=A |
| 도메인 | `domain/ranker.py` | baseline 점수순 상위 N=20 | FR-3·BR-5·**PBT-03**·Q3/Q10=A |
| 도메인 | `domain/grounding_adapter.py` | to_grounding_input/map_decision (**enforce 미호출**) | FR-5·BR-7/8·**INV-1** |
| 도메인 | `domain/assembler.py` | 카드 7필드·종단 상태·SEC-9 | FR-4/11·BR-6/9/15·**PBT-09**·INV-2 |
| 포트 | `ports/search_ports.py` | Embedding/VectorStore/Lexical/EventPublisher + 격리 예외 | RES-9·NFR-R2 |
| 캐시 | `cache/embedding_cache.py` | read-through·TTL 필수 | NFR-P1/C1·TD-U2-7 |
| 서비스 | `service/orchestrator.py` | 파이프라인(plan_and_retrieve/finalize)·degrade 매트릭스·비차단 발행 | 전 스토리·BR-11/13/14·INV-1/3 |
| API | `api/gateway_seam.py` | **단일 enforce invocation**(게이트웨이 대역) | INV-1 |
| API | `api/router.py` | thin FastAPI 라우터·fail-closed 핸들러 | SEC-15·⏳FastAPI |
| mock | `mocks/{fixtures,adapters,port_stubs,wiring}.py` | KO↔EN cross-lingual+QT-2 픽스처·mock 어댑터·U6 스텁·빌더 | MR-1~4·TD-3 |
| 테스트 | `tests/test_*` | PBT-02/03/07/09·종단 상태·degrade·RES-12 폴트 인젝션 | QT-3/4 |
| **real 어댑터** | `adapters/bedrock_embedding.py` | 질의 임베딩(reader=search_query·dim 검증·실패→EmbeddingUnavailable) | CG-2·MR-4·vector-spec §1 |
| **real 어댑터** | `adapters/opensearch_index.py` | k-NN(cosine)+BM25 리더(IndexRecord 역직렬화·실패→IndexUnavailable fail-closed) | CG-2·MR-4·INV-3·FR-2 |
| **real 어댑터** | `adapters/event_publisher.py` | EventBridge SearchExecuted(논블로킹) | CG-2·BR-14·FR-10 |
| **real 어댑터** | `adapters/settings.py` | env 설정(U1 writer와 동일 env명 → 동일 인덱스/공간) | CG-2·vector-spec §4 |
| **real wiring** | `real_wiring.py` | `build_real_orchestrator`(mock과 동일 시그니처·실 어댑터 주입) | MR-4 |
| **스크립트** | `scripts/seed_local_opensearch.py` | 로컬 OpenSearch 인덱스 매핑+미니코퍼스 시드(검증) | — |
| **real 테스트** | `tests/test_{bedrock_embedding,opensearch_adapter,event_publisher,opensearch_integration}.py` | 어댑터 단위(가짜 클라)+라이브 OpenSearch 통합(auto-skip) | CG-2 |

## 핵심 설계 준수
- **INV-1(단일 근거화 게이트)**: orchestrator(도메인 코어)는 `enforce`를 호출하지 않는다. `api/gateway_seam.run_search`(U6 게이트웨이 대역)가 `plan_and_retrieve`와 `finalize` 사이에서 주입된 후크로 단일 호출.
- **INV-2(SEC-9)**: 카드는 7필드(`title·authors·year·arxivId·abstractSnippet·relevance·arxivUrl`)만; raw/RRF 점수·vector·chunkId 비노출. (테스트가 카드 키 집합 검증.)
- **INV-3(fail-closed)**: 인덱스 장애→`SearchUnavailable`(503 일반화); 검증 실패→ValidationErrorDTO. 무매치→명시적 빈 페이지(SearchResultPageDTO·resultCount=0); 근거화 거부→AbstainDTO.
- **cross-lingual(TD-3)**: mock 임베딩이 KO/EN 동의어를 동일 차원에 매핑 → 한국어 질의가 영어 논문 검색(테스트 검증). lexical-only(BM25)는 비-cross-lingual이라 한국어는 무매치 → 빈 페이지(resultCount=0).
- **fail-fast(Q1)**: 임베딩 장애→lexical 폴백(저하), 인덱스 장애→fail-closed.

## 보안/복원력 준수 요약 (FD/NFR 고도)
- **SEC-5**(검증)·**SEC-9**(카드 7필드·일반화 에러)·**SEC-15**(fail-closed)·**SEC-3**(PII 로깅 금지 정책) = 반영(테스트 일부 검증).
- **SEC-8 인증·SEC-11 레이트리밋** = U6 게이트웨이 위임(U2 미구현, 경계 준수). **SEC-10 공급망** = backend 공유 CI(NFR Design).
- **RES-9/NFR-R2**(타임아웃·서킷·폴백) = 정책·폴백 경로 구현(수치는 Infra). **RES-12** = 폴트 인젝션 테스트.
- **PBT-02/03/07/09** = 차단성 속성 전부 테스트(Hypothesis).

## 검증
```
cd backend/modules/discovery
uv run pytest                                            # 43 passed (+1 skip; 통합 auto-skip)
uv run ruff check src tests                              # All checks passed
# 라이브 OpenSearch(로컬 docker) 통합:
docker compose -f ../../docker-compose.yml up -d opensearch
export DOCSURI_OPENSEARCH_ENDPOINT=http://localhost:9200 DOCSURI_OPENSEARCH_USE_SSL=0 DOCSURI_OPENSEARCH_VERIFY_CERTS=0
uv run --extra real python -m discovery.scripts.seed_local_opensearch
uv run --extra real pytest tests/test_opensearch_integration.py   # 3 passed (k-NN·BM25·하이브리드)
```

## mock → real 전환 (✅ 완료, 2026-06-17)
- `ports/search_ports.py` 인터페이스 뒤 mock을 real로 교체 완료: OpenSearch(opensearch-py k-NN/BM25)·Bedrock(boto3, Cohere v4 search_query)·EventBridge 발행. 계약(`SearchResponse`)·도메인 로직 불변(MR-4). 전환은 `real_wiring.build_real_orchestrator` ↔ `mocks.wiring.build_mock_orchestrator` 선택(어댑터만 교체).
- **app-shell 마운트 토글**: `backend/wiring.py::_mount_discovery`가 env(`DOCSURI_OPENSEARCH_ENDPOINT`+`DOCSURI_BEDROCK_MODEL_ID`)로 real/mock 선택. 실 근거화 hook은 양 모드 공통(INV-1). ⚠️ 조율존 변경 — app-shell 소유자 사인오프 필요.
- U6 포트 스텁(`mocks/port_stubs.py`) 중 **근거화 hook은 실 U6로 교체됨**(PR #51). 비용·관측성은 잠정 스텁(U6 프로세스 싱글턴 노출 시 교체; U2는 advisory read-only).
- **⏳ 잔여(후속/Infra)**: 실 OpenSearch 클러스터·Bedrock 접근·이벤트 버스 프로비저닝(공유 인프라 = U1 보류 인프라 + 시스템 횡단), 캐시 스토어(분산), 정량 수치. env로 분리되어 코드는 비차단.
