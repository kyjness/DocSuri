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
| ④ | novelty v2 유닛 설계 | 🔨 진행 중 | 아키텍처 질문지 확정(2026-07-18) 완료. `aidlc-docs/construction/novelty-agent-v2/`에 기존 유닛과 동일한 형식(functional-design / nfr-design / nfr-requirements)으로 작성 + `requirements.md` 소규모 개정 블록(델타 5건: 외부 탐색 메커니즘 중립화·세션 메모리·진행 enum 각주·루프 예산 상한·결정 추적성). 유닛명·코드 경로 모두 `novelty` 유지 — "research*" 명칭은 ⑦ supervisor 명명 후보로 예약(`backend/modules/research/`는 evidence agent의 대화 표면이 사용 중) |
| ⑤ | novelty 코어 재작성 | ⬜ | 고정 상태머신(QUEUED→…→EXPORTING_NOTION)을 **단일 자율 도구 호출 루프**로 모듈 내부 재작성(Q4=A; 루프는 프레임워크 없이 직접 구현, Q5=A). 단계: 에이전트 루프 → MCP 연동(arXiv/GitHub/Notion) → 세션 메모리 → 멀티모달 입력(figure crop을 LLM 컨텍스트에 편입). 기존 API 계약·모듈 경로 유지(Q6=A), 결정 트레이스(도구·질의·종료 사유) 구조화 저장을 루프 도입과 동시 시작 |
| ⑥ | 문헌탐색 에이전트화 | ⬜ | U11 evidence를 **검색 전략만 자율**(어떤 질의로, 어떤 논문을 깊이, 언제 충분한지)인 에이전트로 재작성(Q2=A). 문장 추출·근거표 조립·날조 검사 게이트는 기계식 유지 — C-2 fail-closed 불변. 설계 문서(질문 게이트) 선행 |
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

## 후속 검토 항목

배포 재개(docsuri.org), 전체 코퍼스(30k) 재색인, rerank 로컬 대체, Anthropic API 병행 도입은
[solo-local-migration.md](solo-local-migration.md) §7 미룬 결정 참조.
