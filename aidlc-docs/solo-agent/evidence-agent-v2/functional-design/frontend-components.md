# Evidence Agent v2 (U11) — 프론트엔드 컴포넌트 (Frontend Components)

**단계**: CONSTRUCTION → Functional Design (재설계 라운드) · **유닛**: U11 · **일자**: 2026-07-28
**근거**: FD 게이트 Q11=A · `requirements.md` FR-36 v2·FR-40~43·FR-47 · `business-logic-model.md` §5.2·§6 · 기존 U13 Agent Chat Frontend 계약.
**범위 원칙**: 채팅 화면·세션 drawer·첨부 UI **구조는 유지**한다(FR-40~43). 바뀌는 것은 (1) API 경로, (2) 진행 표시, (3) 근거 칩, (4) 확인 범위 문장 — 네 곳뿐이다.

---

## 1. 변경 지도

| # | 대상 | v1 | v2 |
|---|---|---|---|
| 1 | API 경로 | `/api/research/jobs`·`/messages`·`/attachments` (6~7곳) | `/api/evidence/*` |
| 2 | 진행 표시 | 고정 4단계 문구(`scope_resolved`→`papers_fetched`→`extracting`→`validating`) | 거시 상태 + **활동 피드** |
| 3 | 근거 칩 | 출처 = 논문 제목 + 앵커 유무 | + **종류 라벨**(표 3·그림 2·식 4) + **범위 배지**(전문/초록/그림 해석) |
| 4 | 결과 하단 | 없음 | **확인 범위 문장** |

BFF allowlist(`app/bff/[...path]/route.ts`)의 업스트림 경로도 함께 교체한다.

---

## 2. 진행 표시 — 활동 피드

### 2.1 구조
```
[조사 중]                                  ← 거시 상태 (접수/조사 중/정리 중/완료·부분·기권)
 ├ 코퍼스 검색 "protein structure prediction" → 12편
 ├ 2107.06xxx 본문 확인
 ├ 외부 검색 "AlphaFold pLDDT calibration" → 5편
 ├ 2401.00123 본문 가져오는 중…             ← 승격(초 단위) — 체감 지연을 덮는 자리
 ├ 그림 확인: Figure 3 (2107.06xxx)
 └ 근거 3건 확보
```

- 원천은 **결정 트레이스 한 벌**이다(BLM §6). 화면 전용 이벤트를 따로 받지 않는다.
- 기존 U13의 **접을 수 있는 timeline 블록**(FR-42)을 그대로 쓴다 — 새 컴포넌트를 만들지 않고 항목 소스만 트레이스로 바꾼다.
- 재접속·비동기 잡 폴링 시 저장된 트레이스를 읽어 **그때까지의 피드를 복원**한다(v1은 복원 개념이 없었다).

### 2.2 표시 경계 (SEC-9, INV-EV-5)
표시: 도구명(사용자 어휘로 번역), 질의 요약, 건수, 승격·실패 상태.
비표시: 도구 인자 원문, 게이트 탈락 상세, 벡터 점수, 내부 오류 스택.

---

## 3. 근거 칩 — 종류와 범위

### 3.1 종류 라벨 (`anchorType`)
| 값 | 칩 라벨 | 클릭 동작 |
|---|---|---|
| `paragraph`·`list`·`code` | 본문 | 리치뷰의 해당 블록으로 이동 |
| `table` | 표 N | 해당 표로 이동 |
| `figure` | 그림 N | 해당 그림으로 이동 |
| `formula` | 식 N | 해당 수식으로 이동 |

번호는 DocModel의 `anchorLabel`에서 온다. `anchorLabel`이 없으면 종류만 표시하고 이동은 블록 id로 한다.

### 3.2 범위 배지 (`sourceScope`)
| 값 | 배지 | 의미 전달 |
|---|---|---|
| `fulltext` | (배지 없음) | 기본 — 원문 인용 |
| `abstract` | `초록` | 본문을 확보하지 못해 초록 범위에서 인용했다 |
| `figure` | `그림 해석` | 인용문이 아니라 그림을 읽어 얻은 서술이다 |

- **기본값에 배지를 붙이지 않는다** — 대다수가 `fulltext`인데 전부 배지를 달면 신호가 소음이 된다.
- 배지에 툴팁으로 한 줄 설명을 단다(예: *"본문을 가져오지 못해 초록에서 인용했습니다"*).
- 앵커가 없는 출처(`abstract`)는 이동 링크를 렌더하지 않는다 — 깨진 링크를 만들지 않는다.

---

## 4. 확인 범위 문장

결과 하단에 한 줄로 렌더한다. `EvidenceCoverage.examined`/`candidates`/`stoppedReason`에서 구성한다.

| 중단 사유 | 문장 |
|---|---|
| `sufficient` | (표시하지 않음) |
| `budget_exhausted` | 관련 논문 {candidates}편 중 {examined}편까지 확인했습니다. 이어서 확인할까요? |
| `partial_failure` | 관련 논문 {candidates}편 중 {examined}편을 확인했습니다. 일부 논문은 본문을 가져오지 못했습니다. |

- "이어서 확인할까요?"는 **같은 세션의 후속 턴**으로 이어지는 동작이다(새 API 아님).
- 내부 용어(`degraded`·`budget_exhausted`)를 문구에 노출하지 않는다.

---

## 5. 기권·실패 UX (승계)

| 상태 | 표시 |
|---|---|
| `abstain: out_of_corpus` | 관련 논문을 찾지 못했습니다 + 질문 다듬기 제안 |
| `abstain: insufficient_evidence` | 근거로 쓸 만한 내용을 찾지 못했습니다 |
| `abstain: cost_degraded` | 일시적으로 서비스 이용량이 제한되었습니다 + 재시도 경로 |
| `error` | 일반 오류 문구 + 재시도 (내부 상세 비노출) |

FR-43의 실패·저하 표시와 재시도 경로 규약을 그대로 따른다.

---

## 6. 타입 파급

`SourceRef`·`EvidenceCoverage` 개정 → `shared/dtos` 재생성 → `pnpm run gen:types`로 FE 타입 갱신. **드리프트 가드**(`git diff --exit-code types/`)가 CI에서 잡으므로 생성 산출물을 손으로 고치지 않는다.

---

## 7. 추적성

| 컴포넌트 | 요구사항 |
|---|---|
| 활동 피드(§2) | FR-36 v2, FR-42, FR-46 |
| 근거 칩 종류·범위(§3) | FR-47, FR-31 |
| 확인 범위 문장(§4) | FR-37 v2, NFR-R* |
| 기권·실패 UX(§5) | FR-11, FR-43, SEC-9 |
| 경로 교체(§1) | 요구사항 게이트 Q6=B |
