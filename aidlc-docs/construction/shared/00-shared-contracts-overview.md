# shared/ 공용 계약 — 개요 (Shared Contracts Overview)

**단계**: CONSTRUCTION → 공용 계약 선행 작성(3 병렬 트랙 precursor) · **일자**: 2026-06-16
**근거**: `unit-of-work.md`(UQ5=A `shared/` 단일 소유) · `application-design/{component-methods,services,component-dependency}.md` · U1 FD/NFR(vector-spec 동결) · `execution-plan.md` 병렬 트랙
**목적**: 3개 병렬 트랙(① U1→U6 ② U3→U4 ③ U2mock→U5)이 **안정 계약에 대해 독립 개발**하도록 공용 인터페이스를 선행 확정.

> **상태 범례**: 🔒 **FROZEN**(확정 — 해당 유닛 FD/NFR 완료, 변경 시 광범위 영향) · 🟡 **PROVISIONAL**(잠정 — 형상은 inception application-design 기준; 해당 유닛 FD에서 정제). 트랙은 FROZEN은 그대로, PROVISIONAL은 "계약 우선" 합의로 개발하고 FD 확정 시 동기화.

---

## 1. 소유권 & 위치
- **소유**: `shared/`는 **단일 소유 공용 레이어**(UQ5=A) — 어느 유닛도 독자 포크 금지. 변경은 공용 계약 PR로만.
- **설계 위치**: 본 디렉터리 `aidlc-docs/construction/shared/`(계약 **명세**). 런타임 패키지(repo-root `shared/`) 코드 생성은 Code Generation 단계.
- **코드 위치(예정)**: `shared/{vector-spec, dtos, events, ports}` (모노레포 UQ2=A).

## 2. 계약 구성 (5)
| 계약 | 파일 | 상태 | 1차 생산자 | 1차 소비자 |
|---|---|---|---|---|
| **VectorSpec + IndexRecord** | `vector-spec.md` | 🔒 FROZEN | U1(writer) | U2(reader) |
| **DTOs**(API↔클라이언트) | `dtos.md` | 🟡 PROVISIONAL | U2/U3/U4 | U5 |
| **Events**(이벤트 백본) | `events.md` | 🟡 일부 FROZEN | U1/U2/U3/U6 | U4/U6 |
| **Ports**(횡단 후크 IF) | `ports.md` | 🟡 일부 FROZEN | U6(구현) | U2/U1(의존) |
| **doc-model**(구조화 문서모델) | `docmodel.md` | 🟡 PROVISIONAL | U1(builder) | U7·U5·에이전트 |

> **doc-model**(2026-06-23 피벗 추가): 요약/번역 입력·자체 리치뷰·에이전트 toolschema의 공용 계약. 게이트=`plans/docmodel-foundation-pivot-plan.md`, 스키마=`shared/dtos/docmodel.schema.json`.

## 3. 트랙별 의존 (precursor 근거)
- **Track ①(U1→U6)**: VectorSpec/IndexRecord(생산) · Events(NewArxiv·인제스천 실패·인시던트) · Ports(Observability emit).
- **Track ②(U3→U4)**: DTOs(account·library·saved-search·history) · Events(AccountCreated·SearchExecuted 소비) · Ports(AuthorizationGuard 결정점).
- **Track ③(U2mock→U5)**: DTOs(search result/card/abstain/degraded) · VectorSpec(reader: 질의 임베딩 동일 공간) · Events(SearchExecuted 생산) · Ports(Grounding·Cost 후크).
- **doc-model(U1→U7/U5/에이전트, 2026-06-23 피벗)**: U1 `DocModelBuilder` 생산(lazy·캐시) → U7 요약 입력·U5 리치뷰·에이전트 소비. 표=데이터·수식=LaTeX·그림=webp 참조.

## 4. 버전·호환 정책
- **VectorSpec 변경 = 전체 코퍼스 재임베딩**(단방향, 고비용) → 사실상 동결. `specVersion` 부여, U1 writer·U2 reader가 동일 `specVersion` 소비 불변식.
- **DTO/Event**: 가산적 진화(필드 추가는 하위호환; 제거/의미 변경은 버전업). 내부 필드 비노출(SEC-9).
- **Ports**: 인터페이스 변경은 공용 PR + 영향 유닛 합의.

## 5. 횡단 규약(전 계약 공통)
- **식별자**: `PaperId`=버전 없는 arXiv ID; `ArxivId`=버전 포함 가능; `ChunkId`=`chunkId(PaperId, ordinal)`(결정적).
- **보안**: DTO는 내부 필드(소유자·점수·디버그) 비노출(SEC-9); 로그 PII/시크릿 금지(SEC-3).
- **상세**: 각 계약 파일 참조.
