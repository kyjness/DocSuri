# U9 Personalization — Business Rules

**Unit**: U9 Personalization  
**Stage**: Functional Design

## Business Rules

### BR-P1 — Meaningful Events Only

U9 v1은 `search_executed`, `paper_opened`, `library_added`, `library_removed`, `summary_translation_requested`, `source_anchor_clicked`, `glossary_updated`만 기록한다. Hover, scroll, 일반 클릭 전체 수집, 페이지 체류 시간은 제외한다.

### BR-P2 — Owner-Scoped Data

모든 이벤트, 프로필, 설정, 삭제/초기화 요청은 userId 기준 owner-scoped다. 다른 사용자의 이벤트와 프로필은 조회, 집계, 삭제 대상에 섞이지 않는다.

### BR-P3 — Record After Success

행동 이벤트는 도메인 액션 성공 후 확정 기록한다. `library_removed`는 삭제 전 논문 ID를 확보하고 owner 검증 및 삭제 성공 후 기록한다.

### BR-P4 — Minimal Metadata

metadata는 이벤트 타입별 허용 목록만 저장한다. 원문 전문, 앵커 주변 원문, credential, 내부 토큰, 불필요한 클릭 payload는 저장하지 않는다.

### BR-P5 — Dedupe

동일 `dedupeKey` 이벤트는 한 번만 집계에 반영한다. dedupeKey가 불완전한 경우 사용자, event type, subject, 근접 시간창으로 중복을 제한한다.

### BR-P6 — Profile Signal Semantics

저장, 반복 조회, 요약/번역 요청은 강한 양의 신호다. 단순 조회와 검색은 약한 양의 신호다. `library_removed`는 저장 신호 철회이며 강한 음의 선호가 아니다.

### BR-P7 — Deterministic Bounded Aggregation

동일 입력 이벤트 집합은 동일 `UserInterestProfile`을 만든다. category, keyword, paper weights는 bounded range 안에 있어야 한다.

### BR-P8 — Bounded Search Personalization

U9는 U2의 최종 검색 순위를 직접 결정하지 않는다. U9는 기존 랭킹 위에 적용할 작은 category/keyword boost만 제공한다.

### BR-P9 — Defaults Are Suggestions

요약/번역 개인화는 기본값 제안이다. 사용자가 현재 요청에서 고른 persona, view, translation scope, glossary 선택이 항상 우선한다.

### BR-P10 — Personalization Off

개인화 off 상태에서는 프로필 사용과 향후 개인화 이벤트 기록을 멈춘다. 기존 raw events와 profile은 별도 삭제/초기화 요청이 없으면 보관 정책을 따른다.

### BR-P11 — Delete and Reset Are Separate

행동 로그 삭제는 raw behavior events를 제거한다. 프로필 초기화는 aggregate profile과 defaults를 제거한다. 두 작업은 owner-scoped이며 독립적으로 실행할 수 있다.

### BR-P12 — Raw Event Retention

원시 행동 이벤트는 기본 90일 보관 정책의 대상이다. 보관 만료 또는 삭제 요청 이후 이벤트는 새 프로필 집계 입력으로 사용하지 않는다.

### BR-P13 — Fail Open to Default

이벤트 기록, 프로필 조회, 집계 실패는 검색/요약/번역/라이브러리 본 기능 실패로 승격하지 않는다. 기본 비개인화 경로를 사용하고 저하 신호를 남긴다.

### BR-P14 — No Separate Recommendation List

U9 v1은 별도 추천 논문 목록을 만들지 않는다. 개인화 표면은 검색 결과의 작은 boost/rerank와 요약/번역 기본값 제안으로 한정한다.

### BR-P15 — Telemetry Separation

U9 사용자 행동 데이터는 U6 운영 텔레메트리와 통합하지 않는다. U6에는 실패율, 집계 실패, 폴백 수 같은 운영 신호만 보낸다.

## Response and Decision Rules

| Decision | Rule |
|---|---|
| `profile_available` | enabled=true이고 집계 프로필이 존재함. |
| `disabled` | 사용자가 개인화를 껐음. |
| `no_profile` | 설정은 켜져 있으나 usable profile이 없음. |
| `degraded` | U9 저장소/집계/조회 실패로 기본값 사용. |

## QT-7 Property Requirements

| ID | Property |
|---|---|
| PBT-P1 | BehaviorEvent DTO roundtrip preserves event type, subject, metadata, dedupeKey. |
| PBT-P2 | Dedupe stability: duplicate events do not change profile twice. |
| PBT-P3 | Owner isolation: user A events never affect user B profile. |
| PBT-P4 | Deterministic aggregation for the same event set. |
| PBT-P5 | Delete/reset remove previous personalization signals from decisions. |
| PBT-P6 | Fail-open default: U9 read/record failure returns non-personalized decision. |

## Security Compliance

| Rule | Status | Rationale |
|---|---|---|
| SECURITY-05 | Compliant | Event envelope, metadata allowlist, bounds and type validation defined. |
| SECURITY-08 | Compliant | Owner-scoped events, profile, settings, delete/reset. |
| SECURITY-09 | Compliant | Metadata excludes raw content, credentials, tokens, internal details. |
| SECURITY-14 | Compliant | User delete/reset controls are explicit. |
| SECURITY-15 | Compliant | U9 failure degrades to default behavior without exposing internals. |
| SECURITY-01/02/04/06/07/10/11/12/13 | N/A at FD | Identity provider, IAM, network, dependency, monitoring and runtime controls are NFR/Infra/Code concerns. |

## Resiliency Compliance

| Rule | Status | Rationale |
|---|---|---|
| RESILIENCY-01 | Compliant | U9 dependencies and user impact are documented in unit artifacts. |
| RESILIENCY-05 | Compliant | U9 emits operational degradation signals to U6. |
| RESILIENCY-09 | Compliant | U9 dependency failures are explicit and fail open to default. |
| RESILIENCY-10 | Compliant | Profile/event store failure behavior is defined. |
| RESILIENCY-02/03/04/06/07/08/11/12/13/14/15 | N/A at FD | DR, deployment, health checks, and incident runbooks are NFR/Infra/Ops concerns. |

## PBT Compliance

| Rule | Status | Rationale |
|---|---|---|
| PBT-01 | Compliant | PBT-P1..P6 properties identified for code generation. |
| PBT-02/03/07/08/09 | Deferred | Enforced in Code Generation/NFR Requirements per partial PBT mode. |
| PBT-04/05/06/10 | Advisory/N/A | Current partial mode does not block on these; deterministic aggregation and dedupe are still captured. |

## Traceability Matrix

| Requirement / Story | Rules |
|---|---|
| FR-18 | BR-P1, BR-P2, BR-P3, BR-P4, BR-P5 |
| FR-19 | BR-P6, BR-P7, BR-P10, BR-P11, BR-P12 |
| FR-20 | BR-P8, BR-P9, BR-P10, BR-P13, BR-P14 |
| NFR-P4 | BR-P13, BR-P15 |
| QT-7 | PBT-P1..PBT-P6 |
| US-P1 | BR-P1, BR-P3, BR-P4, BR-P13 |
| US-P2 | BR-P3, BR-P4, BR-P6 |
| US-P3 | BR-P6, BR-P7, BR-P12 |
| US-P4 | BR-P8, BR-P13, BR-P14 |
| US-P5 | BR-P9 |
| US-P6 | BR-P10, BR-P11 |
| US-P7 | BR-P13, BR-P15 |
