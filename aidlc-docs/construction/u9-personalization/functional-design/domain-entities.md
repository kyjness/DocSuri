# U9 Personalization — Domain Entities

**Unit**: U9 Personalization  
**Stage**: Functional Design  
**Scope**: 의미 있는 사용자 행동 이벤트, 관심 프로필, 개인화 설정/삭제/초기화, 검색/요약/번역 개인화 결정. 기술 스택과 저장소 구현은 제외한다.

## Entity Model

### BehaviorEvent

사용자별 개인화에 쓰이는 의미 행동 이벤트.

| Field | Required | Rule |
|---|---:|---|
| `eventId` | Yes | 이벤트 고유 ID. |
| `userId` | Yes | owner-scoped 사용자 ID. |
| `eventType` | Yes | `BehaviorEventType` 중 하나. |
| `subject` | Yes | 이벤트 대상 논문, 검색, 요약/번역, 용어집 항목. |
| `occurredAt` | Yes | 도메인 액션 성공 시각. |
| `source` | Yes | `backend` 또는 `frontend_anchor`. |
| `metadata` | No | 이벤트 타입별 허용된 최소 필드만. |
| `dedupeKey` | Yes | 요청/액션 단위 중복 방지 키. |

### BehaviorEventType

v1에서 기록하는 이벤트 타입은 7개로 제한한다.

| Type | Meaning |
|---|---|
| `search_executed` | 검색이 성공적으로 실행됨. |
| `paper_opened` | 논문 상세 또는 전문 보기 진입이 성공함. |
| `library_added` | 논문이 사용자 라이브러리에 저장됨. |
| `library_removed` | 논문이 사용자 라이브러리에서 해제됨. |
| `summary_translation_requested` | 요약 또는 번역 요청이 성공적으로 접수됨. |
| `source_anchor_clicked` | 요약/번역 출처 보기 앵커가 열린 프런트 전용 이벤트. |
| `glossary_updated` | 개인 용어집 선호가 수정됨. |

### BehaviorSubject

이벤트 대상. 원문 전문이나 민감 payload를 담지 않는다.

| Field | Rule |
|---|---|
| `kind` | `paper`, `search`, `summary`, `translation`, `source_anchor`, `glossary`. |
| `paperId` | 논문 관련 이벤트면 arXiv/canonical paper id. |
| `queryHash` | 검색 이벤트에서 원문 질의 대신 정규화/해시된 식별자를 쓸 수 있음. |
| `category` | 알고 있는 arXiv category. |
| `anchorId` | 출처 앵커 식별자. 원문 내용은 저장하지 않음. |

### BehaviorEventMetadata

타입별 최소 metadata만 허용한다.

| Event | Allowed Metadata |
|---|---|
| `search_executed` | result count, top categories, language. |
| `paper_opened` | entry surface, paper category. |
| `library_added` | paper category, saved source. |
| `library_removed` | removed paper id/category captured before delete. |
| `summary_translation_requested` | mode, selected persona, translation scope. |
| `source_anchor_clicked` | anchor id, section kind. |
| `glossary_updated` | glossary version, term count delta. |

### UserInterestProfile

행동 이벤트에서 집계한 사용자별 관심 프로필.

| Field | Rule |
|---|---|
| `userId` | owner. |
| `categoryWeights` | arXiv category별 bounded weight. |
| `keywordWeights` | 키워드별 bounded weight. |
| `paperSignals` | 저장/반복 조회/요약 요청 논문 신호. |
| `summaryPersona` | 최근/우세 요약 persona 기본값. |
| `translationScope` | 최근/우세 번역 범위 기본값. |
| `glossaryVersion` | 적용 가능한 개인 용어집 버전. |
| `updatedAt` | 마지막 집계 시각. |

### InterestSignal

프로필 집계 입력으로 해석된 신호.

| Signal | Rule |
|---|---|
| Strong positive | `library_added`, 반복 `paper_opened`, `summary_translation_requested`. |
| Weak positive | 단일 `paper_opened`, `search_executed`. |
| Retraction | `library_removed`; "싫어요"가 아니라 저장 신호 철회. |
| Preference update | `glossary_updated`, summary persona/scope 선택. |

### PersonalizationSettings

사용자 제어 상태.

| Field | Rule |
|---|---|
| `enabled` | false면 프로필 사용과 향후 개인화 이벤트 기록을 멈춘다. |
| `rawEventsDeletedAt` | 사용자가 raw log delete를 실행한 시각. |
| `profileResetAt` | 사용자가 aggregate/defaults reset을 실행한 시각. |

### PersonalizationDecision

U2/U7이 소비하는 개인화 결정.

| Field | Rule |
|---|---|
| `enabled` | 개인화 적용 가능 여부. |
| `searchBoosts` | category/keyword bounded boost. **계약: 각 boost 값은 반드시 `[-0.1, +0.1]` 범위 내여야 하며, 전체 부스트의 합이 최대 `0.2`를 초과할 수 없다. 이는 기본 검색의 적합성 순위를 극단적으로 뒤집지 않고 미세 조정만 수행하도록 강제하기 위함이다.** |
| `summaryDefaults` | persona/view 기본값 제안. |
| `translationDefaults` | scope/glossary 기본값 제안. |
| `reason` | `profile_available`, `disabled`, `no_profile`, `degraded`. |

### PersonalizationError

사용자 본 기능을 실패시키지 않는 오류.

| Error | Behavior |
|---|---|
| `Disabled` | 비개인화 기본값 반환. |
| `ProfileUnavailable` | 비개인화 기본값 반환. |
| `EventStoreFailure` | 본 요청 성공 유지, 저하 신호 발행. |
| `AggregationFailure` | 이전 프로필 또는 기본값 사용, 저하 신호 발행. |
| `Unauthorized` | U3/U6 경로에서 차단. |

## Testable Properties

| Property | Category | Rule |
|---|---|---|
| Event DTO roundtrip | Round-trip | Serialize/deserialize 후 event type, subject, dedupe key 보존. |
| Dedupe stability | Idempotence | 같은 dedupe key 이벤트는 한 번만 집계 반영. |
| Owner isolation | Security invariant | userId가 다른 이벤트/프로필은 서로 섞이지 않음. |
| Deterministic aggregation | Business invariant | 동일 이벤트 집합은 동일 프로필을 만든다. |
| Delete/reset effect | Privacy invariant | raw log delete와 profile reset 후 개인화 신호가 제거됨. |

## Traceability

| Source | Covered By |
|---|---|
| FR-18 | `BehaviorEvent`, `BehaviorEventType`, `BehaviorSubject` |
| FR-19 | `UserInterestProfile`, `InterestSignal`, `ProfileAggregator` |
| FR-20 | `PersonalizationSettings`, `PersonalizationDecision` |
| NFR-P4 | `PersonalizationError`, fail-open default behavior |
| QT-7 | Testable Properties |
| US-P1..P6 | Event, profile, decision, control entities |
| US-P7 | Error/degradation signals |
