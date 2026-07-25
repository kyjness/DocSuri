# 유지보수 로드맵 (2026-07)

단독 유지보수 전환(로컬 인프라 이관) 이후의 작업 계획. 두 축으로 구성한다:
(a) 기존 유닛(u1/u2/u7)의 설계 문서 대비 정합성 리뷰 및 결함 수리,
(b) 두 에이전트 모듈(novelty, 문헌탐색·근거형성)을 자율 에이전트 아키텍처로 재설계 —
최종형은 supervisor–서브 에이전트 구조. 아키텍처 결정:
[requirement-verification-questions-agent-rearchitecture.md](../inception/requirements/requirement-verification-questions-agent-rearchitecture.md) (2026-07-18 확정, Q1~Q8).

## 착수 순서 (2026-07-25 확정)

**⑤2 → ⑤3 → ⑥ → ⑦.** 로드맵 번호 그대로이며, 단계를 건너뛰거나 뒤섞지 않는다.

| 순서 | 작업 | 끝나면 |
|---|---|---|
| ~~1~~ | ~~⑤2 세션 메모리~~ ✅ 완료 (2026-07-25) | novelty 2/3 |
| **2** | ⑤3 멀티모달 — `view_figure` 등록 | **novelty 완료 (3/3)** |
| **3** | ⑥ 문헌탐색 에이전트 — 새로 작성 | 두 에이전트 완성 |
| **4** | ⑦ supervisor 신설 + LangGraph | 멀티 에이전트 완성형 |

**⑤를 먼저 끝내고 ⑥으로 가는 이유**: ⑤1(루프)만 끝난 현재 novelty는 기능이 반쪽이다 —
대화 메시지는 저장되지만 루프가 읽지 않고(`domain/loop.py`에 스티어링 주입 없음), 온디맨드
산출물(방향 제안·실험 계획) 생성 경로가 없다. 이는 v2 기능 정의의 절반에 해당한다
(기능 정의 Q1=X·Q4=B). ⑥은 모듈 전면 재작성이라 기간이 길고, 그동안 반쪽 모듈을 방치하게 된다.
⑤2·⑤3은 루프 코어가 이미 있어 증분이 작다.

**⑤3을 ⑥ 뒤로 미루지 않는 이유**: `view_figure`는 설계상 DocModel/S3 **공용 부품**이므로,
⑥ 게이트의 "figure 도구를 문헌탐색에도 노출할지"가 어떻게 정해지든 도구 자체는 동일하게 만든다
(노출 결정은 레지스트리 등록 여부일 뿐). 미뤄서 절약되는 작업이 없다.

## 단계별 작업 절차

각 단계(⑤2·⑤3·⑥·⑦)를 아래 순서로 돈다. 리뷰는 **커밋 이후**에 돌리고, 지적 반영은
`fix(...)` 별도 커밋으로 남긴다 — 무엇이 리뷰로 바뀌었는지가 이력에 보여야 한다.

| # | 단계 | 비고 |
|---|---|---|
| 0 | **설계 확인** — 해당 유닛의 frozen 설계 문서 대비 범위 확정 | ⑥·⑦은 **질문 게이트 선행**(설계 문서 없이 코딩 금지) |
| 1 | 작업 브랜치 — `feature/<short-kebab>` | `feat/` 아님(CI 거부) |
| 2 | **구현 + 테스트** | 테스트는 구현과 같은 커밋 |
| 3 | 로컬 검증 — `uv run ruff check .` · `uv run pytest` | 서브프로젝트 디렉터리에서 실행 |
| 4 | **로컬 커밋** (기능 단위, 한국어 본문) | push는 아직 |
| 5 | `/simplify` → 반영 → 커밋 | 품질 정리(중복·단순화). **버그는 안 잡음** |
| 6 | `/code-review` → 반영 → 커밋 | 결함 사냥. 5 이후여야 simplify 변경분도 걸린다 |
| 7 | `/security-review` → 반영 → 커밋 | 6과 관점이 다름 — 생략 금지 |
| 8 | **문서 갱신** — 본 로드맵 상태 행 + `aidlc-state.md` | 별도 `docs:` 커밋 |
| 9 | **push + PR** | ⚠️ **사용자 승인 후에만** |

**단계별로 추가되는 검증**:

- 에이전트 단계(⑤2·⑤3·⑥·⑦) → `backend/CLAUDE.md`의 **에이전트 루프 체크리스트**
  (루프 상한·도구 결과의 신뢰 경계·트레이스·중단 안전성)를 7단계에서 함께 본다.
- 공유 스키마를 건드렸으면 → `cd shared/python && uv run python tools/generate.py --check`
- FE 타입이 파급되면 → `pnpm run gen:types && git diff --exit-code types/`
- 게이트 테스트가 걸리는 유닛이면 → 로컬 스택을 띄우고 **스킵 0**을 확인한다
  (스킵은 통과처럼 보인다 — "게이트 레인" 절 참조).

**리뷰 결과가 서로 어긋나면 코드가 arbiter다** — 리뷰 지적을 그대로 믿지 말고 재감사 후
해결/기각을 근거와 함께 기록한다(③ 잔여 4건 처리 방식).

| # | 단계 | 상태 | 내용 |
|---|---|---|---|
| ① | 저장소 정리 | ✅ 완료 | 비프로덕션 문서 제거 (a8003e2) |
| ② | 로컬 인프라 이관 | ✅ 완료 | AWS 관리형 서비스 → 컨테이너 4종(postgres/redis/opensearch/s3proxy) + OpenAI 프로바이더 어댑터, 1,000편 재색인, E2E 검증. 상세: [solo-local-migration.md](solo-local-migration.md) |
| ③ | 유닛 정합성 리뷰 | ✅ 완료 | u7(0f5d866·dc778bb) → u1(e90634a) → u2(59ee3b7) — 각 유닛의 frozen 설계 문서 기준 리뷰·확정 결함 수리. 이관 이슈(아래) 전건 처리. u2에서 reader 임베딩 공간 가드(`_meta.embedding` manifest)·의존성별 서킷 브레이커 신설. 잔여 후속(evidence 제2 리더 정합)은 ⑤a(b)에서 해소 |
| ④ | novelty v2 유닛 설계 | ✅ 완료 (2026-07-18) | 질문지 3장 확정(아키텍처 Q1~Q8 · 기능 정의 Q1~Q7 · FD 게이트 Q1~Q14) — v2 임무 = **조사 + 여백 분석**(방향 제안·실험 계획은 대화 온디맨드), 완전 자율 루프, 채팅 모드 + 잡 + 대화 스티어링, 원고 위험 신호 폐기, Notion export 유지(승인 게이트). `requirements.md` 개정 블록(FR-30~33·35 개정, FR-34 폐기, FR-44~47 신규) + `construction/novelty-agent-v2/` 설계 세트 8종(functional-design 4 / nfr-requirements 2 / nfr-design 2). 유닛명·코드 경로 모두 `novelty` 유지 — "research*"는 ⑦ supervisor 명명 후보로 예약 |
| ⑤ | novelty 코어 재작성 | 🔶 2/3 | 고정 상태머신(QUEUED→…→EXPORTING_NOTION)을 **단일 자율 도구 호출 루프**로 모듈 내부 재작성(Q4=A; 루프는 프레임워크 없이 직접 구현, Q5=A). 단계: **1) 에이전트 루프 ✅** (2026-07-20, PR #2~#6 — 도메인 코어/포트/게이트·어댑터(redis/postgres/OpenAI + real_wiring 기준선)·API/워커 컷오버·레거시 제거; shared 서킷 브레이커·env·emit_metric 통합 포함) → **2) 세션 메모리 ✅** (2026-07-25) — 잡 내 멀티턴: 대화 스티어링을 다음 decide 시점에 주입(BLM §6, 드레인 위치는 예산 검사 통과 후 — 앞에 두면 예산이 거부한 턴에서 지시가 유실된다) + 종단 잡의 온디맨드 산출물 생성 경로(BLM §5). 저장은 `agent_step.execute_save` 하나만 통과하고(BR-RA2/RA6), 잡 상태는 바뀌지 않으며(BR-RA5), 한 턴은 `max_turn_steps`로 제한된다(NFR-NV2-7). 메시지 `kind`는 서버가 확정(위조 표면 제거) — 별도 의도 분류기는 두지 않고 결과는 답장의 `resulting_artifact_ref`가 담는다. u5 대화 UI 동반(차단 해제·스티어링 안내·bounded 제안 카드). 선행 결함 2건 수리: 어댑터 간 `artifact_id` 불일치, 큐 nack 부재 → **3) 멀티모달 ⬜** — `view_figure` 등록(figure/수식 crop을 LLM 컨텍스트에 편입). **MCP는 고정 단계에서 해제**(2026-07-25 개정 — 아래) — 외부 탐색 어댑터를 MCP로 교체할 필요가 실제로 생기는 시점에 도입한다. 모듈 경로 유지, API·화면 계약은 새 산출물 기준 재설계(기능 정의 Q7=B), 결정 트레이스(도구·질의·종료 사유) 구조화 저장을 루프 도입과 동시 시작 |
| ⑤a | 정리 보수 | ✅ 완료 (2026-07-25, PR #7·#14) | ⑤ 1단계 직후에 끼운 유지보수 — ③(설계 정합성)·코드 리뷰와는 관점이 다른 별개 작업. (a) **u1 ingestion 정리 ✅ 완료** (2026-07-20, PR #7) — 중복 제거 외에 평문 시크릿 로깅·alias 분기·429 오분류 등 실결함 5건 수리, 테스트 320→355. **u2 discovery·u7 summarization의 동일 전면 정리는 취소**한다(근거는 아래 "⑤a 범위 축소") — 대신 두 유닛에는 **테스트 공백 점검만** 수행: 실입력 픽스처 없이 mock/합성 입력만으로 검증되는 경로를 찾아 필요한 곳에만 픽스처·테스트를 추가한다 (b) **③ 잔여 후속 2건 ✅ 완료** (PR #14): evidence `real_wiring.py` 리더 정합(임베딩 공간 가드 + 프로바이더 스위치 — discovery 가드 헬퍼 공유, `7d1e630`), shared `search.schema.json` Scope 설명문 stale 정정(BR-4b 불일치; 재생성 + FE 타입 파급 동반, `6b7431c`) (c) **게이트 테스트 미실행 ✅ 해소** (PR #7) — 아래 "게이트 레인" 참조 |
| ⑥ | 문헌탐색 에이전트화 | ⬜ | U11 evidence를 **검색 전략만 자율**(어떤 질의로, 어떤 논문을 깊이, 언제 충분한지)인 에이전트로 **새로 작성**(Q2=A, Q4=A 상속 — 기존 `orchestrator.py` 고정 파이프라인은 승계 대상이 아니다). 문장 추출·근거표 조립·날조 검사 게이트는 기계식 유지 — C-2 fail-closed 불변. **자율/기계식 경계**: 질의 설계·깊이 판단·종료 판단은 에이전트, 앵커 실재성·수치 정합 검증은 게이트. 설계 문서(질문 게이트) 선행. **⑥ 게이트에서 결정할 항목**: ① **근거 대상 확장** — 근거 검색·추출·앵커(SourceRef)를 문장만이 아니라 DocModel의 표·그림·수식 객체까지 커버하도록 설계(requirements 델타 ⑥ 연동) ② figure/표 조회 도구(DocModel/S3 공용 부품)를 문헌탐색 루프에도 노출할지 |
| ⑦ | supervisor + LangGraph | ⬜ | supervisor가 서브 에이전트(문헌탐색 탐색 워커, 아이디어 생성)를 지휘·병렬 실행하는 멀티 에이전트 완성형(Q1=C). 병렬 배선·에이전트 간 상태 전달에 LangGraph 도입(Q5=A). **supervisor는 별도 신설**한다 — novelty를 계획층으로 승격하는 안은 기각(2026-07-25, 아래 "supervisor 구성 방식"). novelty·evidence는 둘 다 서브로 남고, 각자의 단독 진입점(잡·채팅)도 유지된다. **⑦ 질문 게이트에서 결정**: supervisor의 도구/서브 경계, 전용 UI 모드, 서브 활동 노출 수준, LangGraph 도입 범위 |

## 개정 (2026-07-25) — MCP 고정 슬롯 해제 · supervisor 구성 방식

### MCP — ⑤ 2단계 고정 슬롯 해제

**MCP 도입은 독립적으로 결정된 적이 없다.** 관련 문항을 되짚으면:

- 아키텍처 Q1=C의 **선택지 설명문**에 역량 목록(`Tool Calling·Planning·Memory·MCP·멀티 에이전트`)으로
  딸려 들어온 것이 유일한 상위 근거다. 최종 구조를 고르는 문항이지 MCP 도입 문항이 아니다.
- FD 게이트 Q5는 **"MCP를 쓴다"를 전제하고 위치만** 묻는다(포트 뒤 어댑터 vs 루프 직결).
- FD 게이트 Q3은 외부 arXiv 검색을 "⑤ 2단계(MCP)로 미룬다"고만 답한다.

즉 "쓸 것인가"를 정면으로 물은 문항이 없는 채로 로드맵에 고정 단계가 생겼다. 해제한다.

해제 근거(도입을 금지하는 것이 아니라 **고정 일정에서 빼는 것**):

- 외부 도구 3종이 **이미 어댑터로 구현돼 있다** — `adapters/external/github.py`,
  `datasets.py`, arXiv 클라이언트는 u1 ingestion. MCP 교체로 늘어나는 기능은 0.
- 서드파티 MCP 서버에 **GitHub·Notion 자격증명을 위임**하게 된다. `tech-stack-decisions.md`가
  "서버는 신뢰 경계 밖"이라 적어둔 인식이 맞다면, 그 결론은 배포 환경에서 프로세스를 늘리지
  않는 쪽이다.
- 프라이버시 방어선(payload allowlist)은 어느 경우든 **우리 어댑터가 강제**하므로, MCP는
  지켜야 할 경계를 늘릴 뿐 줄이지 않는다.

**따라서**: 외부 탐색 포트의 구현을 MCP로 교체할 **필요가 실제로 생기는 시점**(도구 공급처를
자주 갈아끼우게 되거나, 자작 유지비가 교체비를 넘을 때)에 그때의 근거와 함께 도입한다.
FR-31의 "메커니즘 중립화"는 그대로 유효하다 — 포트 뒤 어댑터라는 위치(Q5=A)도 유효하다.
바뀐 것은 **일정뿐**이다.

### supervisor 구성 방식 — 별도 신설 (novelty 승격 기각)

⑦의 미결이던 "⑤ 루프의 계획층 승격 vs 별도 신설"을 **별도 신설**로 확정한다.

승격안(novelty 루프가 evidence 에이전트를 서브로 호출하며 supervisor 역할을 겸함)을 기각하는 근거:

- **역할 혼재** — novelty의 임무는 조사 + 여백 분석이다. 여기에 타 에이전트 지휘를 얹으면 하나의
  자율 루프가 프롬프트·예산·종료 조건을 두 목적에 걸쳐 갖게 된다. 종료 판정이 특히 모호해진다
  ("내 산출물 완성"과 "부하 작업 종료"가 다른 조건).
- **진입점 상실** — 문헌탐색·차별화는 각각 독립된 사용자 진입점(채팅 표면·잡)을 갖는 기능이다.
  승격안에서는 문헌탐색 단독 사용이 novelty 하위로 묻힌다. 별도 신설이면 기존 두 진입점을
  유지한 채 "주제만 던지면 알아서" 진입점이 하나 늘어난다.
- **확장 경로** — 서브가 추가될 때(요약·인용 그래프 탐색 등) 별도 신설은 서브만 붙이면 되지만,
  승격안은 novelty를 계속 부풀린다.
- **Q1=C 원문과의 정합** — "supervisor가 서브 에이전트들(문헌탐색 탐색 워커, **아이디어 생성**)을
  지휘"이므로 novelty도 서브다. 승격안은 확정된 답과 어긋난다.

용어 경계도 함께 고정한다 — **도구**는 스스로 판단하지 않는 부품(검색·요약·DocModel·figure 조회),
**서브 에이전트**는 스스로 판단하는 단위(문헌탐색·차별화). supervisor는 주로 서브 지휘와 결과
종합을 맡고, 저수준 도구는 서브가 쥔다. 구체 배선은 ⑦ 질문 게이트에서 정한다.

## ③ 유닛 리뷰 이관 이슈

로컬 이관 검증 중 발견 (solo-local-migration.md §6):

- refiner legacy `.txt` 경로 — 개행 없는 정규화 전문에서 저작권 패턴 매칭 시 문서 전체가 제거됨 (u7)
- `tests/test_pbt.py::test_pbt_response_to_dict_sec9_all_states` hypothesis 실패 — 이관 이전부터 존재 (u7)
- 요약 출력 언어가 한국어 요구사항과 달리 영어로 나오는 사례 — 프롬프트 언어 강제 보강 또는 모델 변경 실험 (u7)

코드 리뷰 중 발견 — **4건 전부 재감사 후 해결 확인(2026-07-25, 코드가 arbiter)**:

- ~~v2 듀얼라이트 경로의 중복 기록 가능성 (u1)~~ ✅ — 쓰기는 단일 인덱스 chunkId upsert
  (`adapters/aws.py` bulk_upsert, `_id=chunkId`) + `delete_stale_chunks`로 멱등, 마이그레이션은
  v2 인덱스에만 쓰고 alias cutover는 **쓰기와 분리**된 원자적 repoint(테스트
  `test_opensearch_switch_alias_cutover_is_separate_from_write`). 라이브 이중 기록 경로 없음.
- ~~arXiv 경로에서 dedup 이전에 doc-model 빌드 수행 (u1)~~ ✅ — `application.py::_index_paper`가
  `build_doc_model()`를 dedup 단락·`begin_upsert` claim **이후**에만 호출(deferred lambda, BLM §0.3).
- ~~Bedrock 스트림 error 이벤트 미처리 (u7)~~ ✅ — `adapters/bedrock_llm.py::_stream_tool_input`이
  out-of-band error 이벤트(`"chunk" not in event`)와 in-band error frame(`type=="error"`) 모두 raise →
  retry→LlmUnavailable→abstain.
- ~~LocalCircuitBreaker HALF-OPEN 상태 동시성 (u7)~~ ✅ — per-unit 브레이커 4종을 스레드 안전한 공유
  `docsuri_shared.resilience.CircuitBreaker`로 통합(single-probe·stale-success·probe-slot 만료).

## ⑤a 범위 축소 (2026-07-20)

당초 계획은 u1 → u2 → u7에 같은 전면 정리를 1회씩 돌리는 것이었으나, u1 실시 후 u2·u7분은 취소한다.

u1에서 실제로 값이 나온 것은 중복 제거 자체가 아니라 **테스트가 없던 자리에서 나온 결함**이었다:
`safe_log_dict`의 API 키·연락처 평문 로깅, `migrate`/`reembed`의 alias 분기, OpenAI 어댑터의 429
재시도 불가 분류, 그리고 테스트가 0건이던 컴포넌트 3종(Postgres control-plane·circuit breaker·
redaction 헬퍼). 순수 중복 제거분은 배포가 은퇴한 현 시점에서 회수 시점이 불분명하다 —
유지보수 비용은 그 코드를 다시 만질 때 절감되는데 u1은 당분간 재작업 계획이 없다.

따라서 u2·u7에는 같은 비용을 들이지 않고, 값이 나온 관점만 옮긴다: **실입력 없이 검증되는 경로가
어디인지 점검하고, 그 자리에만 픽스처·테스트를 추가한다.** 정리는 두 유닛을 다시 만질 때
그 작업에 곁들인다.

u1 정리 패스의 부산물로 실논문 회귀 픽스처(ar5iv HTML·GROBID TEI·PDF)와 세 경로 회귀 테스트가
생겼다. 배포 은퇴로 사라진 "실제 논문이 온전히 파싱되는가"의 육안 확인을 대체하며,
파싱→청킹까지 `uv run pytest`만으로 검증된다. 갱신 절차는 `ingestion/tests/fixtures/SOURCES.md` 참조.

**⑤a(a) 테스트 공백 점검 종결 (2026-07-25).** u2·u7의 실입력/silent-degradation 경로를 감사한
결과 로드맵이 우려한 지점은 이미 커버되어 있어 **신규 u2/u7 테스트는 불필요**하다:
u2 discovery는 fake-client 어댑터 단위 + 실 OpenSearch 통합 게이트 + golden recall + PBT,
u7 summarization은 `refine_doc_model`(표·수식·캡션·앵커 id + PDF/GROBID `latex=None` image-only
회귀 `test_refine_doc_model_skips_image_only_formula` + U1 정규화 개행 없는 전문의 copyright 삭제
회귀 `test_single_line_full_text_survives_copyright_match`), grounding `real_corpus` 평가, 실 게이트
(`test_assets_rds_real`·`test_integration_real`의 S3 왕복)로 모두 검증된다. **이번 패스에서 실제로
드러난 "테스트 0" 공백은 u11 evidence `real_wiring`**(제2 리더)였고, ⑤a(b)-1 정합과 함께 단위
테스트를 신설해 닫았다.

## 게이트 레인 — 확인 후 전건 해소 (2026-07-20)

u1 정리에서 `PostgresControlPlaneStore`가 "테스트 없음"이 아니라 **게이트 뒤에서 아무도 안 도는 상태**
였던 것이 드러나, 저장소 전체의 env 게이트 테스트를 점검했다. 결과는 `ci.yml`에 `services:` 블록이
아예 없어 **게이트 테스트가 CI에서 하나도 실행되지 않는 상태**였다. 스킵은 통과처럼 보이므로 이
공백은 드러나지 않는다. **PR #7에서 전부 해소.**

| 게이트 | 유닛 | 조치 | 결과 |
|---|---|---|---|
| `test_control_plane_real.py` | u1 | postgres 서비스 + 마이그레이션 적용 | 362 passed, **스킵 0** |
| `test_assets_rds_real.py` | u7 | postgres 서비스(테스트가 자체 DDL 생성) | 309 passed, **스킵 0** |
| `test_integration_real.py` | u7 | **AWS → 로컬 스택으로 재작성** (아래) | 동일 레인에서 실행 |
| `test_opensearch_integration.py` | u2 | opensearch 서비스 + `real` extra(원인 2겹) | 138 passed, k-NN/BM25가 실클러스터 상대 |
| `test_novelty_v2_queue.py` | u12 | redis 서비스 | 384 passed — 잡 큐 락·visibility timeout 실검증 |

u7 `test_integration_real.py`는 은퇴한 AWS를 가리키고 있어 **로컬 스택(S3 호환 엔드포인트/redis/
postgres)으로 재작성**했다. 어댑터는 무수정 — boto3가 `AWS_ENDPOINT_URL_S3`를 인식하는 것이 ②단계에서
이 대체를 택한 이유다. 빌드 스모크만 있던 것에 **실제 왕복**을 추가했다: `S3RedisSummaryStore.get`과
`S3FullTextSource.get_full_text`가 모든 예외를 삼켜 `None`을 반환하므로, 버킷 오설정·엔드포인트 불통·
키 파생 드리프트가 캐시 미스와 구분되지 않고 읽기 경로가 조용히 영구 열화된다. 쓰고 다시 읽어야만
증명된다. (`bare_paper_id` 변이로 새 단언이 실제로 실패하는 것까지 확인.)

**정정 (2026-07-21)**: 위 왕복 테스트 3건은 신설 직후부터 CI에서 스킵되고 있었다 —
`boto3.client()`가 프로세스 전역 `DEFAULT_SESSION`에 자격증명을 **해석 시점에 캐시**하는데,
같은 레인의 `test_assets_rds_real.py`가 monkeypatch로 가짜 키를 넣은 상태에서 먼저 클라이언트를
만들면서 그 캐시를 오염시켰다. monkeypatch는 env를 되돌리지만 이미 해석된 자격증명은 되돌리지
못한다. 스킵은 통과로 보이므로 "왕복이 검증된다"는 위 서술이 그동안 사실이 아니었다.
`tests/conftest.py`의 autouse 픽스처로 테스트마다 세션 슬롯을 비워 해소(307+3스킵 → **310 통과,
스킵 0**). 같은 진단을 다시 늦추지 않도록 `ci.yml`의 모든 pytest 호출에 `-rs`를 붙여 스킵 사유를
로그에 남긴다. AWS 자격증명을 monkeypatch하는 테스트는 저장소 전체에서 그 파일 하나뿐이다.

**여전히 게이트로 남은 1건**: `backend/tests/test_citation_graph.py`의 계약 테스트 — 라이브 Semantic
Scholar API + API 키가 필요하다. CI에 넣으려면 저장소 시크릿이 필요하고 외부 API 장애가 CI를 흔들게
되므로 **넣지 않는다**(판단 종결, 후속 아님).

## 후속 검토 항목

배포 재개(docsuri.org), 전체 코퍼스(30k) 재색인, rerank 로컬 대체, Anthropic API 병행 도입은
[solo-local-migration.md](solo-local-migration.md) §7 미룬 결정 참조.
