# solo-agent — 두 에이전트 문서

novelty(차별화 판정)와 evidence(문헌탐색·근거형성) 두 에이전트의 질문지·설계 문서를 모아둔
폴더다. 단독 유지보수 사이클에서 만들어졌고, 팀 시절 AI-DLC 산출물(`../construction/`,
`../inception/`)과 섞이지 않게 분리했다.

## 무엇이 여기 있나

| 경로 | 내용 |
|---|---|
| `requirement-verification-questions-agent-rearchitecture.md` | 2026-07-18 아키텍처 질문지 (Q1·Q5는 2026-08-21 재확정 — 독립 에이전트 2개 · LangGraph) |
| `requirement-verification-questions-novelty-v2-function.md` | novelty v2 기능 정의 질문지 (2026-07-18) |
| `requirement-verification-questions-evidence-agent-v2.md` | evidence v2 질문 게이트 (2026-07-28) |
| `plans/` | 유닛 설계 계획서(질문 게이트) 4종 |
| `novelty-agent-v2/` · `evidence-agent-v2/` | 각 유닛의 설계 세트(FD 4 / NFR-req 2 / NFR-design 2) |

v1 frozen 기준선(`../construction/novelty-agent/`, `../construction/u11-*`)은 옮기지 않았다 —
팀 시절 산출물이고 대조용으로만 쓴다.

## 문서의 권위

**결정은 질문지의 `[Answer]:`에만 생긴다.** 대화에서 오간 방향, 설계 문서의 서술, 로드맵의
계획은 결정이 아니다. 설계 문서가 질문지와 어긋나면 질문지가 이긴다.

현행 코드의 동작을 적을 때는 **결정과 구분해서** 적는다 — "이렇게 하기로 했다"와 "지금 이렇게
돼 있다"는 다르다. 후자는 언제든 문항의 대상이 될 수 있다.

## 진행 상태 (2026-08-15)

- **미정**: 두 에이전트의 최종 구조(arch Q1), 프레임워크 채택(arch Q5), 그리고 현행 질문지의
  전 문항.
- **되돌린 것**: supervisor + LangGraph 도입 단계는 로드맵에서 제거됐다. 두 에이전트를 각자의
  목적에 맞게 완성하는 것이 현재 작업이다.
- 로드맵 상의 위치: `../operations/solo-roadmap.md`.
