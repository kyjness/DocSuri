# Evidence Agent v2 (U11) — 기술 스택 결정 (Tech Stack Decisions)

**단계**: CONSTRUCTION → NFR Requirements (재설계 라운드) · **유닛**: U11 · **일자**: 2026-07-28
**전제**: AWS 배포는 은퇴했고 로컬 스택(postgres·redis·opensearch·s3proxy) + OpenAI 프로바이더가 현행이다(`operations/solo-local-migration.md`). 아래 결정은 그 위에서 내린 것이며, 배포 재개 시 어댑터 교체로 흡수한다.

| ID | 결정 | 근거 |
|---|---|---|
| **TD-EV2-1** | 루프는 **프레임워크 없이 직접 구현** | 상속 arch Q5=A. LangGraph는 ⑦ supervisor에서 병렬·상태 전달이 실제로 필요해질 때 |
| **TD-EV2-2** | LLM 호출은 **포트 뒤 어댑터** — 현행 구현은 OpenAI, 프로바이더 교체는 어댑터 추가 | 헥사고날 원칙. novelty가 같은 형태로 이미 돌고 있다 |
| **TD-EV2-3** | 도구 레지스트리는 **allowlist deny-by-default** | novelty `ports/tools.py` 선례 — 어휘 밖 도구가 구조적으로 등록 불가 |
| **TD-EV2-4** | 검색은 **U2 discovery 재사용**(하이브리드 + phrase) | BR-EV-2. 전용 인덱스·랭킹 금지 |
| **TD-EV2-5** | 온디맨드 승격은 **기존 `BUILD_DOC_MODEL` 큐 경로 재사용**(enqueue + bounded polling) | 요구사항 게이트 Q15 재결정(2026-07-28). 큐 계약·워커·reader-triggered 우선순위 큐가 이미 있고 u7이 쓰고 있다. backend 의존성 closure를 늘리지 않고, 파싱 CPU가 ingestion 워커에 이미 격리돼 있다. 코디네이터는 `backend/modules/user_docmodel.py`의 enqueue+poll 패턴을 따른다. **운영 전제**: ingestion 워커 미가동 시 폴링 시간 초과 → 초록 범위로 수렴 |
| **TD-EV2-6** | 승격 취득 경로는 u1의 사다리를 그대로 탄다(ar5iv HTML 우선 → PDF+GROBID 폴백) | u1 `adapters/arxiv.py`. **GROBID는 로컬 compose에 있으나 `profiles: ["ingest"]` 옵트인**이라 기본 `up`에서 빠진다 — `docker compose --profile ingest up -d grobid` + `DOCSURI_GROBID_URL`로 켜야 폴백이 동작하고, 켜지 않으면 초록 범위로 수렴한다 |
| **TD-EV2-7** | 백그라운드 색인은 **기존 잡 큐(redis)** 경유 | 응답 경로와 분리. 실패해도 답변 무영향 |
| **TD-EV2-8** | 세션·턴·트레이스 저장은 **postgres 3테이블** | FD 게이트 Q6=A. 결과는 전용 컬럼(현행 `attachments` JSON 부채 청산) |
| **TD-EV2-9** | 외부 초록 스냅샷 테이블을 **두지 않는다** | FD 게이트 Q5=A. 버전 고정 식별자 + 재취득으로 재현 |
| **TD-EV2-10** | 그림 자산 리더는 **`backend/modules/paper_assets.py`로 공용화한 비전용 리더** 사용 | 요구사항 게이트 Q8. `shared/python`이 아닌 이유: `docsuri-shared`는 pydantic만 의존하는 계약 패키지라 sqlalchemy·boto3 런타임 부품을 넣으면 계약 소비자 전부가 그 의존을 진다. 저장소 선례(`backend/modules/user_docmodel.py`)와 같은 자리. u7 표시용 리더(서명 URL)는 목적이 달라 합치지 않는다 |
| **TD-EV2-11** | 진행 전달은 **SSE**, 비동기 경로는 폴링 | NFR-P6 승계. 트레이스 append가 유일한 원천 |
| **TD-EV2-12** | 첨부는 **기존 `user_docmodel` 공유 coordinator** 재사용 | FD 게이트 Q9=A. 원시 파일 미저장 불변 유지 |
| **TD-EV2-13** | 서킷 브레이커는 **`docsuri_shared.resilience.CircuitBreaker`** 공유 구현 | u7·u2 통합 선례. 의존성별로 하나씩 |
| **TD-EV2-14** | 표면은 **`/api/evidence` 단일 라우터**, `research` 모듈 제거 | 요구사항 게이트 Q6=B·Q7=A |
| **TD-EV2-15** | 테스트는 도구 대역(fake) 기반 결정론 루프 + PBT 8종 + 로컬 게이트 테스트 | QT-8, NFR §9 |

## 조건부 마운트

`backend/wiring.py`의 기존 원칙을 따른다 — 필요한 설정이 없으면 해당 도구가 **등록되지 않고 에이전트 도구 목록이 자연 축소**된다.

| 도구 | 등록 조건 |
|---|---|
| `corpus_search` | 검색 엔드포인트 + 임베딩 설정 |
| `external_search` · `fetch_paper` | 외부 소스 설정(허용 호스트 목록 포함) |
| `read_paper` | DocModel 스토어 설정 |
| `view_figure` | 자산 토글 + postgres(`paper_asset`) |
| `extract_evidence` | LLM 설정 (없으면 유닛 자체가 마운트되지 않는다) |

## 마이그레이션 메모

- `research_jobs`·`research_messages` → `evidence_*` 이관 후 제거. 스키마 변경은 **버전 관리 마이그레이션으로만** 수행한다.
- `shared/dtos/evidence.schema.json` 개정(`anchorType`·`sourceScope`·coverage 확장) → 생성 바인딩 재생성 → FE 타입 파급. 두 지점 모두 CI 드리프트 가드가 있다.
