# unit-of-work-dependency.md — 유닛 의존성 매트릭스

**단계**: INCEPTION → Units Generation · **일자**: 2026-06-15
**근거**: `application-design/component-dependency.md`. 종류: **sync**(동기 호출/REST), **event**(이벤트 백본, 비동기), **lib**(빌드 시 공유 계약/인터페이스 의존).

---

## 의존성 매트릭스 (from → to)

| from \\ to | U1 | U2 | U3 | U4 | U5 | U6 | U7 | U8 | U9 | U11 | shared |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **U1 Ingestion** | — | — | — | — | — | event(인시던트/관측 발행) | — | — | — | — | lib(VectorSpec·DocModel schema·이벤트) |
| **U2 Discovery** | (Corpus 인덱스 read = capability, 코드 의존 아님) | — | — | event(SearchExecuted 발행) | — | lib(근거화·비용 후크 via `shared/ports`) | — | — | sync(프로필 read) + event(search/open) | — | lib(VectorSpec·DTO) |
| **U3 Accounts** | — | — | — | — | — | — | — | — | — | — | lib(DTO) |
| **U4 Library** | — | event(SearchExecuted 소비) | sync(인가 결정 위임) | — | — | — | — | — | event(library add/remove) | — | lib(DTO) |
| **U5 Frontend** | — | sync(REST, 게이트웨이 경유) | sync(REST) | sync(REST) | — | sync(게이트웨이 진입) | sync(REST, 게이트웨이 경유) | sync(REST, 상세보기 경유) | sync(설정/삭제/출처 앵커 event) | sync(REST, 게이트웨이 경유) | lib(DTO) |
| **U6 Reliability/Ops** | event(인제스천 신호 소비) | sync(게이트웨이→U2 핸들러 호출) | sync(authz 위임 호출) | sync(게이트웨이→U4 핸들러) | — | — | sync(게이트웨이→U7 핸들러) | sync(게이트웨이→U8 핸들러) | sync(게이트웨이→U9 핸들러) | sync(게이트웨이→U11 핸들러) | lib(이벤트·ports) |
| **U7 Summarization** | (DocModel/FullText S3 read = capability, 코드 의존 아님) | — | — | — | — | lib(근거화·비용 후크 via `shared/ports`) + event(관측/비용 발행) | — | sync(요약 출처에서 각주 트리 열기) | sync(기본값/profile read) + event(summary/translation/glossary) | — | lib(DTO·ports) |
| **U8 Citation Graph** | — | — | sync(로그인/인가 경로) | sync(노드 저장) | — | lib(레이트리밋·관측 포트) + event(관측 발행) | — | — | — | — | lib(DTO·events) |
| **U9 Personalization** | — | — | sync(로그인/인가 경로) | — | — | lib(관측 포트) + event(저하/집계 신호) | — | — | — | — | lib(DTO·events) |
| **U11 Research Agent** | — | sync(검색 read 경로) | sync(로그인/인가 경로) | (논문 저장 시 U4 계약 재사용·선택) | — | lib(근거화·비용 후크 via `shared/ports`) + event(관측 발행) | (doc-model 파싱·근거화 파이프라인 재사용 = capability/lib) | (외부 학술 API 캐시 패턴 재사용 — 모드 B·차기) | sync(개인화 신호 read, 비차단) | — | lib(DTO·ports) |
| **shared** | — | — | — | — | — | — | — | — | — | — | — (leaf) |

> U5 사용자 경로는 **U6 게이트웨이를 단일 진입**으로 U2/U3/U4/**U7/U8/U9/U11** 핸들러에 도달한다(표의 U5→U2/U3/U4/U7/U8/U9/U11 sync는 게이트웨이 프런티드).
> **U7은 U2와 동일 의존 패턴**: U1 DocModel/FullText는 capability read(코드 의존 아님), U6 근거화·비용 후크는 `shared/ports` 인터페이스 의존(U6 구현) → U7↔U6 코드 순환 없음.
> **U8은 로그인 필수 상세보기 보조 경로**: U3/U6 인증·게이트웨이 경로를 통과하고, 노드 저장은 U4 Library 계약을 호출한다. 외부 citation API는 U8 내부 어댑터 뒤에 둔다.
> **U9는 비차단 개인화 보조 경로**: U2/U4/U7/U5 성공 경로가 의미 이벤트를 기록하거나 프로필을 읽지만, 실패해도 본 기능은 기본 비개인화 경로로 계속된다.
> **U11은 로그인 필수 온디맨드 대화형 보조 경로**(U7과 동일 의존 패턴): U3/U6 인증·게이트웨이를 통과하고, U6 근거화·비용 후크는 `shared/ports` 인터페이스 의존(U6 구현) → U11↔U6 코드 순환 없음. U2 검색·U7 doc-model/근거화 파이프라인을 재사용하고, 모드 B(차기)는 U8 외부 API 캐시 패턴을 재사용한다. U9 개인화 신호는 비차단 read. U11 실패는 U2 검색 등 본 기능을 막지 않는다.

## 통신 패턴
- **동기 REST**(NFR-P1 읽기 경로): U5 → U6 게이트웨이 → U2/U3/U4/U9 핸들러 → 응답. U4 rerun도 동일 경로 재진입(백도어 금지).
- **온디맨드 상세보기 REST**(NFR-P2/P3): U5 논문 상세보기 → U6 게이트웨이 → U7/U8 핸들러 → 응답. 검색 NFR-P1 비대상.
- **온디맨드 대화형 다논문 분석**(NFR-P5, 비차단): U5 전용 네비 메뉴 → U6 게이트웨이 → U11 핸들러(검색→교차확인→근거 비교 정리→근거화/기권); 긴 분석은 비동기 잡 + 진행상태 폴링. 검색 NFR-P1 비대상.
- **개인화 이벤트/프로필**(비차단): U2/U4/U7/U5 성공 경로 → U9 event recorder/profile API; 실패 시 기본 기능 유지.
- **이벤트 백본**(비동기): source별 스케줄/backfill/rebuild → U1; U2 `SearchExecuted` → U4(이력); 탐지기(비용/할루시네이션/반쪽짜리) → IncidentEventPublisher; U9 저하/집계 신호; 관측성 팬아웃.
- **lib(의존성 역전)**: 횡단 후크(근거화·비용) 인터페이스는 `shared/ports`에 정의, U6가 구현, U2가 인터페이스에 의존 → **코드 순환 없음**.

## 비순환 검증 (코드 의존 그래프)
- `shared`는 leaf(무의존). U1/U2/U3/U4/U5는 `shared`에만 lib 의존.
- U4 → U3: 인가 결정 위임(sync, 단방향).
- U6 → U2/U3/U4: 게이트웨이가 핸들러 호출(런타임 호출, 단방향). U2 → U6는 **코드 의존이 아님**(U2는 `shared/ports` 인터페이스에 의존; U6가 구현) → U2↔U6 코드 순환 없음.
- U2 ↔ U4: `SearchExecuted`는 **event**(비동기) — 코드 순환 아님.
- U2 → U1: Corpus/OpenSearch 인덱스는 **공유 capability**(런타임 데이터 의존), 코드 의존 아님(U1 단일 writer, U2 단일 reader).
- **U7 → U1**: DocModel/FullText는 **공유 capability**(S3 read, 런타임 데이터 의존), 코드 의존 아님(U1 단일 writer, U7 reader). U7 → U6도 `shared/ports` 인터페이스 의존(U6 구현) → U7↔U6 코드 순환 없음(U2와 동형). U6 → U7은 게이트웨이가 핸들러 호출(런타임, 단방향).
- **U8 → U4/U3/U6**: U8은 인증/인가 경로(U3/U6)와 저장 계약(U4)을 런타임 호출한다. U4는 U8을 호출하지 않으므로 코드 순환 없음. U7→U8은 요약 출처에서 각주 트리를 여는 선택적 런타임 호출이며 U8→U7 역호출 없음.
- **U9 → U3/U6**: U9는 로그인/인가 경로(U3/U6)와 관측 포트(shared/U6 구현)에 의존한다. U2/U4/U7/U5는 U9를 호출하지만 U9가 이들을 역호출하지 않아 코드 순환 없음.
- **U11 → U2/U3/U6/U7/U8/U9**: U11은 U3/U6 인증·게이트웨이, U2 검색 read, U7 doc-model/근거화 재사용(capability/lib), U8 외부 API 캐시 패턴(모드 B·차기), U9 개인화 신호(비차단 read)에 의존한다. U6 후크는 `shared/ports` 인터페이스 의존(U6 구현) → U11↔U6 순환 없음(U7과 동형). 어느 유닛도 U11을 역호출하지 않아(U5/U6 게이트웨이만 런타임 단방향 호출) 코드 순환 없음.
- **결론**: 코드 의존 그래프 비순환(DAG) — U7/U8/U9/U11 추가 후에도 유지. 런타임 호출/이벤트는 단방향 또는 비동기로 순환 없음.

## ASCII 흐름도

### 동기 디스커버리 읽기 (NFR-P1)
```text
U5 ──REST──> U6 게이트웨이 ──> U2(질의→검색→랭킹→근거화어댑터→조립) ──> 응답
                  │  (authz는 U3 위임, 근거화/비용 후크 주입)
                  └──> [응답 엣지] U6 GroundingEnforcementHook (단일 권위)
```
### 온디맨드 요약/번역 (U7, NFR-P2 — 검색 SLA 비대상)
```text
U5 ──REST──> U6 게이트웨이 ──> U7(STORE 조회→비용게이트→전문 fetch→정제→LLM→근거화→저장)
                  │  (authz는 U3 위임, 근거화/비용 후크 주입)
                  ├──> [캐시 HIT] Redis/S3 즉시 반환 (LLM 0콜)
                  ├──> [비용게이트 OPEN] 요약 일시 기권(FR-11)
                  └──> [응답 엣지] U6 GroundingEnforcementHook (근거 없으면 기권)
U7 전문 read <── 공유 capability(S3, U1 writer) ;  U7 결과 ──> S3 영구 + Redis 핫
```
### 논문 상세보기 각주 트리 (U8, NFR-P3 — 검색 SLA 비대상)
```text
U5 논문 상세보기 ──REST──> U6 게이트웨이 ──> U8(로그인 확인→snapshot 캐시→citation API→ID 해소→트리 조립)
                                   │
                                   ├──> [캐시 HIT] citation snapshot 즉시 반환
                                   ├──> [API 실패/쿼터] 캐시 우선, 없으면 "인용 정보를 불러올 수 없음"
                                   └──> [노드 저장] U4 Library 저장 계약 재사용
U8 ──관측 event──> U6(조회 수·캐시 적중·429·unresolved 비율·노드 수·지연)
```
### 개인화 이벤트와 프로필 (U9, NFR-P4 — 비차단)
```text
U2/U4/U7/U5 성공 경로 ──event/sync──> U9(이벤트 기록→프로필 집계→설정/삭제/초기화)
                                      │
                                      ├──> [프로필 있음] U2 검색 boost / U7 기본값 제안
                                      ├──> [사용자 off/delete/reset] 비개인화 기본 경로
                                      └──> [U9 실패] 기본 기능 유지 + 저하 신호(U6)
```
### 온디맨드 대화형 다논문 근거형성 (U11, NFR-P5 — 검색 SLA 비대상·비차단)
```text
U5 전용 네비 메뉴 ──REST──> U6 게이트웨이 ──> U11(모드 선택→검색→다논문 교차확인→근거 비교 정리→근거화)
                                   │  (authz는 U3 위임, 근거화/비용 후크 주입)
                                   ├──> [긴 분석] 비동기 잡 + 진행상태/부분결과 폴링
                                   ├──> [비용게이트 OPEN] 일시 기권(FR-11) · 동일 질의 캐시 재사용
                                   ├──> [응답 엣지] U6 GroundingEnforcementHook (근거 없으면 기권)
                                   └──> [결과·세션] owner-scoped 영속 → 전용 메뉴 세션 리스트 재열람
U11 검색 <── U2 read ; doc-model/근거화 <── U7 재사용 ; (모드 B 차기) 외부 학술 API <── U8 캐시 패턴
```
### 인제스천 (이벤트/스케줄)
```text
source별 스케줄/backfill/rebuild ──> U1 워커 ──> (source fetch→FullText/GROBID→DocModel→Block chunk→embed) ──> 공유 Corpus 인덱스(write)
                                                                                                             └─실패─> DLQ/재시도/경보(U6 관측)
```
### 이력·인시던트 (이벤트 백본)
```text
U2 ──SearchExecuted(event)──> U4 SearchHistory
U2/U6 ──근거화 위반/비용 급증/반쪽짜리(event)──> U6 탐지기 ──> IncidentEventPublisher ──> Ops 대시보드
```
