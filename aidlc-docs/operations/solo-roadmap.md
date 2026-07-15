# 유지보수 로드맵 (2026-07)

단독 유지보수 전환(로컬 인프라 이관) 이후의 작업 계획. 두 축으로 구성한다:
(a) 기존 유닛(u1/u2/u7)의 설계 문서 대비 정합성 리뷰 및 결함 수리,
(b) novelty 모듈의 고정 워크플로우를 도구 호출 기반 에이전트 아키텍처로 재설계.

| # | 단계 | 상태 | 내용 |
|---|---|---|---|
| ① | 저장소 정리 | ✅ 완료 | 비프로덕션 문서 제거 (a8003e2) |
| ② | 로컬 인프라 이관 | ✅ 완료 | AWS 관리형 서비스 → 컨테이너 4종(postgres/redis/opensearch/s3proxy) + OpenAI 프로바이더 어댑터, 1,000편 재색인, E2E 검증. 상세: [solo-local-migration.md](solo-local-migration.md) |
| ③ | 유닛 정합성 리뷰 | ⬜ 다음 | u1 ingestion / u2 discovery / u7 summarization — 각 유닛의 frozen 설계 문서 기준으로 리뷰하고 확인된 결함만 수리. **타임박스 1–2일.** 착수 시 이관 이슈 목록(아래) 포함 |
| ④ | research-agent 유닛 설계 | ⬜ | `aidlc-docs/construction/research-agent/`에 기존 유닛과 동일한 형식(functional-design / nfr-design / nfr-requirements)으로 작성. 유닛 명칭은 "Research Ideation Agent" — 코드 모듈 경로는 `novelty` 유지(`research` 경로는 evidence agent의 대화 표면이 사용 중) |
| ⑤ | novelty 코어 재설계 | ⬜ | 고정 상태머신(QUEUED→…→EXPORTING_NOTION)을 도구 호출 루프 기반 에이전트로 교체. 단계: 에이전트 루프 → MCP 연동(arXiv/GitHub/Notion) → 세션 메모리 → 멀티모달 입력(figure crop을 LLM 컨텍스트에 편입). 기존 API 계약·모듈 경로는 유지 |

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
