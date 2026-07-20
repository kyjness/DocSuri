# 유지보수 로드맵 (2026-07)

단독 유지보수 전환(로컬 인프라 이관) 이후의 작업 계획. 두 축으로 구성한다:
(a) 기존 유닛(u1/u2/u7)의 설계 문서 대비 정합성 리뷰 및 결함 수리,
(b) 두 에이전트 모듈(novelty, 문헌탐색·근거형성)을 자율 에이전트 아키텍처로 재설계 —
최종형은 supervisor–서브 에이전트 구조. 아키텍처 결정:
[requirement-verification-questions-agent-rearchitecture.md](../inception/requirements/requirement-verification-questions-agent-rearchitecture.md) (2026-07-18 확정, Q1~Q8).

| # | 단계 | 상태 | 내용 |
|---|---|---|---|
| ① | 저장소 정리 | ✅ 완료 | 비프로덕션 문서 제거 (a8003e2) |
| ② | 로컬 인프라 이관 | ✅ 완료 | AWS 관리형 서비스 → 컨테이너 4종(postgres/redis/opensearch/s3proxy) + OpenAI 프로바이더 어댑터, 1,000편 재색인, E2E 검증. 상세: [solo-local-migration.md](solo-local-migration.md) |
| ③ | 유닛 정합성 리뷰 | ✅ 완료 | u7(0f5d866·dc778bb) → u1(e90634a) → u2(59ee3b7) — 각 유닛의 frozen 설계 문서 기준 리뷰·확정 결함 수리. 이관 이슈(아래) 전건 처리. u2에서 reader 임베딩 공간 가드(`_meta.embedding` manifest)·의존성별 서킷 브레이커 신설. 잔여 후속: evidence 모듈(제2 리더)의 space guard/프로바이더 스위치 미적용 |
| ④ | novelty v2 유닛 설계 | ✅ 완료 (2026-07-18) | 질문지 3장 확정(아키텍처 Q1~Q8 · 기능 정의 Q1~Q7 · FD 게이트 Q1~Q14) — v2 임무 = **조사 + 여백 분석**(방향 제안·실험 계획은 대화 온디맨드), 완전 자율 루프, 채팅 모드 + 잡 + 대화 스티어링, 원고 위험 신호 폐기, Notion export 유지(승인 게이트). `requirements.md` 개정 블록(FR-30~33·35 개정, FR-34 폐기, FR-44~47 신규) + `construction/novelty-agent-v2/` 설계 세트 8종(functional-design 4 / nfr-requirements 2 / nfr-design 2). 유닛명·코드 경로 모두 `novelty` 유지 — "research*"는 ⑦ supervisor 명명 후보로 예약 |
| ⑤ | novelty 코어 재작성 | 🔶 1/4 | 고정 상태머신(QUEUED→…→EXPORTING_NOTION)을 **단일 자율 도구 호출 루프**로 모듈 내부 재작성(Q4=A; 루프는 프레임워크 없이 직접 구현, Q5=A). 단계: **1) 에이전트 루프 ✅** (2026-07-20, PR #2~#6 — 도메인 코어/포트/게이트·어댑터(redis/postgres/OpenAI + real_wiring 기준선)·API/워커 컷오버·레거시 제거; shared 서킷 브레이커·env·emit_metric 통합 포함) → 2) MCP 연동(arXiv/GitHub/Notion) → 3) 세션 메모리 → 4) 멀티모달 입력(figure crop을 LLM 컨텍스트에 편입). 모듈 경로 유지, API·화면 계약은 새 산출물 기준 재설계(기능 정의 Q7=B), 결정 트레이스(도구·질의·종료 사유) 구조화 저장을 루프 도입과 동시 시작 |
| ⑤a | 정리 보수 | 🔶 축소 재정의 (⑤ 1↔2단계 사이) | ⑤ 2단계 착수 **전에** 끼우는 유지보수 — ③(설계 정합성)·코드 리뷰와는 관점이 다른 별개 작업. (a) **u1 ingestion 정리 ✅ 완료** (2026-07-20, PR #7) — 중복 제거 외에 평문 시크릿 로깅·alias 분기·429 오분류 등 실결함 5건 수리, 테스트 320→355. **u2 discovery·u7 summarization의 동일 전면 정리는 취소**한다(근거는 아래 "⑤a 범위 축소") — 대신 두 유닛에는 **테스트 공백 점검만** 수행: 실입력 픽스처 없이 mock/합성 입력만으로 검증되는 경로를 찾아 필요한 곳에만 픽스처·테스트를 추가한다 (b) ③ 잔여 후속 2건: evidence `real_wiring.py` 리더 정합(임베딩 공간 가드 + 프로바이더 스위치 — discovery 가드 헬퍼 공유), shared `search.schema.json` Scope 설명문 stale 정정(BR-4b 불일치; 재생성 + FE 타입 파급 동반) |
| ⑥ | 문헌탐색 에이전트화 | ⬜ | U11 evidence를 **검색 전략만 자율**(어떤 질의로, 어떤 논문을 깊이, 언제 충분한지)인 에이전트로 재작성(Q2=A). 문장 추출·근거표 조립·날조 검사 게이트는 기계식 유지 — C-2 fail-closed 불변. 설계 문서(질문 게이트) 선행. **⑥ 게이트에서 결정할 항목**: ① **근거 대상 확장** — 근거 검색·추출·앵커(SourceRef)를 문장만이 아니라 DocModel의 표·그림·수식 객체까지 커버하도록 설계(requirements 델타 ⑥ 연동) ② figure/표 조회 도구(DocModel/S3 공용 부품)를 문헌탐색 루프에도 노출할지 |
| ⑦ | supervisor + LangGraph | ⬜ | supervisor가 서브 에이전트(문헌탐색 탐색 워커, 아이디어 생성)를 지휘·병렬 실행하는 멀티 에이전트 완성형(Q1=C). 병렬 배선·에이전트 간 상태 전달에 LangGraph 도입(Q5=A). **미결**: supervisor 구성 방식(⑤ 루프의 계획층 승격 vs 독립 에이전트 위 별도 신설)·전용 UI 모드·서브 활동 노출 수준은 ⑦ 질문 게이트에서 결정 |

## ③ 유닛 리뷰 이관 이슈

로컬 이관 검증 중 발견 (solo-local-migration.md §6):

- refiner legacy `.txt` 경로 — 개행 없는 정규화 전문에서 저작권 패턴 매칭 시 문서 전체가 제거됨 (u7)
- `tests/test_pbt.py::test_pbt_response_to_dict_sec9_all_states` hypothesis 실패 — 이관 이전부터 존재 (u7)
- 요약 출력 언어가 한국어 요구사항과 달리 영어로 나오는 사례 — 프롬프트 언어 강제 보강 또는 모델 변경 실험 (u7)

코드 리뷰 중 발견:

- v2 듀얼라이트 경로의 중복 기록 가능성 (u1)
- arXiv 경로에서 dedup 이전에 doc-model 빌드 수행 (u1)
- Bedrock 스트림 error 이벤트 미처리 (u7)
- LocalCircuitBreaker HALF-OPEN 상태 동시성 (u7)

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

## 후속 검토 항목

배포 재개(docsuri.org), 전체 코퍼스(30k) 재색인, rerank 로컬 대체, Anthropic API 병행 도입은
[solo-local-migration.md](solo-local-migration.md) §7 미룬 결정 참조.
