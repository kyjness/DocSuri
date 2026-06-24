# U9 Personalization — Business Logic Model

**Unit**: U9 Personalization  
**Stage**: Functional Design  
**Principle**: 기술 무관. API framework, DB, scheduler, cache, and concrete integration are deferred.

## Components

| Component | Responsibility |
|---|---|
| `BehaviorEventRecorder` | 의미 있는 행동 이벤트 envelope 검증, dedupe, owner-scoped 기록. |
| `UserInterestProfileService` | 관심 프로필 조회, 집계, reset. |
| `PersonalizationSettingsService` | 개인화 on/off, raw log delete, profile reset 처리. |
| `PersonalizationPolicy` | 이벤트 허용 목록, metadata 허용 필드, boost/default 적용 경계. |
| `ProfileAggregator` | 이벤트를 category/keyword/paper/default preference signal로 변환. |
| `PersonalizationReadPort` | U2/U7이 개인화 결정을 읽는 경계. |
| `PersonalizationTelemetryPublisher` | U6로 저하/집계/기록 실패 신호 발행. |

## Use Case: Record Behavior Event

1. Caller는 U3/U6 인증 경로의 `userId`를 포함해 이벤트를 보낸다.
2. Recorder는 개인화 설정이 off인지 확인한다.
3. off이면 이벤트를 기록하지 않고 `Disabled` 결과를 반환한다.
4. Recorder는 `eventType`, `subject`, `metadata`, `dedupeKey`를 검증한다.
5. 허용되지 않은 event type 또는 metadata field는 거부한다.
6. 같은 `dedupeKey` 이벤트가 이미 있으면 중복 성공으로 처리하고 집계에는 한 번만 반영한다.
7. 새 이벤트를 owner-scoped raw event로 기록한다.
8. 기록 실패는 caller의 본 기능 실패로 승격하지 않고 telemetry로 남긴다.

## Use Case: Aggregate Interest Profile

1. Service는 userId의 raw events를 owner-scoped로 읽는다.
2. 삭제 요청 이후의 이벤트만 집계 대상으로 본다.
3. `library_added`, 반복 `paper_opened`, `summary_translation_requested`는 강한 양의 신호로 변환한다.
4. 단일 `paper_opened`, `search_executed`는 약한 양의 신호로 변환한다.
5. `library_removed`는 저장 신호 철회로 처리하고 강한 음의 선호로 보지 않는다.
6. `glossary_updated`와 요약/번역 선택은 기본값 preference로 변환한다.
7. category/keyword/paper weights는 bounded 값으로 정규화한다.
8. 동일 입력 이벤트 집합이면 동일 `UserInterestProfile`을 산출한다.
9. 집계 실패 시 이전 프로필을 유지하거나 기본 비개인화 결과를 제공하고 telemetry로 남긴다.

## Use Case: Get Search Personalization

1. U2는 검색 실행 시 U9에 `userId`와 query context로 개인화 결정을 요청한다.
2. 설정이 off이거나 프로필이 없으면 `enabled=false`와 `reason=disabled/no_profile`을 반환한다.
3. 프로필이 있으면 category/keyword bounded boost만 반환한다.
4. U2는 기존 랭킹 위에 작은 boost만 적용한다.
5. U9 조회 실패 시 U2는 기본 비개인화 검색으로 계속한다.

## Use Case: Get Summary/Translation Defaults

1. U7은 요약/번역 요청 UI 또는 실행 시 U9에 기본값 제안을 요청한다.
2. U9는 summary persona, view, translation scope, glossary version 제안을 반환한다.
3. 사용자가 현재 요청에서 명시적으로 선택한 옵션은 항상 U9 제안보다 우선한다.
4. U9 조회 실패 시 U7은 기존 기본값으로 계속한다.

## Use Case: Set Personalization Enabled

1. 사용자는 owner-scoped 설정 API로 `enabled`를 변경한다.
2. `enabled=false`이면 이후 프로필 사용과 향후 개인화 이벤트 기록을 멈춘다.
3. 기존 raw events와 aggregate profile은 삭제/초기화 API가 호출되기 전까지 보관 정책을 따른다.
4. `enabled=true`이면 이후 이벤트 기록과 프로필 사용을 재개한다.

## Use Case: Delete Behavior Events

1. 사용자는 owner-scoped raw log delete를 요청한다.
2. Service는 해당 userId의 raw behavior events를 삭제 또는 삭제 처리한다.
3. 삭제 이후 집계는 삭제된 이벤트를 입력으로 사용하지 않는다.
4. aggregate profile은 별도 reset 요청이 없으면 다음 집계에서 삭제 효과를 반영한다.

## Use Case: Reset Interest Profile

1. 사용자는 owner-scoped profile reset을 요청한다.
2. Service는 `UserInterestProfile`과 summary/translation defaults를 초기화한다.
3. 이후 개인화 결정은 프로필이 다시 집계되기 전까지 `no_profile` 또는 기본값을 반환한다.

## Failure Model

| Failure | Behavior |
|---|---|
| Missing principal | U3/U6 경로에서 fail closed. |
| Unsupported event type | U9 이벤트 기록만 거부, caller 본 기능은 이미 성공 상태 유지. |
| Metadata validation failure | 해당 event rejected, telemetry 가능. |
| Duplicate event | idempotent success, 집계에는 1회만 반영. |
| Event store failure | caller 본 기능 유지, degraded telemetry. |
| Profile store/aggregation failure | 비개인화 기본 경로 또는 이전 프로필, degraded telemetry. |
| Delete/reset failure | 해당 제어 요청은 실패 응답, 본 검색/요약 기능에는 영향 없음. |

## Testable Properties

| Property | Check |
|---|---|
| DTO roundtrip | BehaviorEvent와 PersonalizationDecision shape 보존. |
| Dedupe stability | 같은 dedupe key 재전송이 프로필을 추가 변경하지 않음. |
| Owner isolation | user A 이벤트가 user B 프로필에 영향 없음. |
| Deterministic aggregation | 이벤트 순서가 달라도 동일 집합이면 동일 프로필. |
| Retention/delete/reset | 삭제/초기화 후 개인화 decision에서 이전 signal 제거. |
| Fail-open default | U9 기록/조회 실패가 U2/U7/U4 성공 경로를 실패시키지 않음. |

## Traceability

| Story / Requirement | Logic |
|---|---|
| US-P1, FR-18 | Record Behavior Event |
| US-P2, FR-18 | record-after-success, library removed subject capture, source anchor event |
| US-P3, FR-19 | Aggregate Interest Profile |
| US-P4, FR-20 | Get Search Personalization |
| US-P5, FR-20 | Get Summary/Translation Defaults |
| US-P6, FR-19/20 | Set Enabled, Delete Events, Reset Profile |
| US-P7, NFR-P4 | Failure Model, TelemetryPublisher |
| QT-7 | Testable Properties |
