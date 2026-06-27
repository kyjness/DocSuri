# U11 Research Agent — Frontend Components (Functional Design)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**근거(SSOT)**: `stories.md`(US-RA1·RA2·RA5·RA6), `requirements.md`(FR-24/25·NFR-P5·NFR-U1), `plans/u11-research-agent-functional-design-plan.md`(Q15=B 풀 버티컬).
**원칙**: 기술 무관(프레임워크·상태관리 라이브러리·스트리밍 전송은 NFR/Code). 본 문서는 컴포넌트 구조·props/state·상호작용·검증·API 연동 지점만 정의한다.
**상태**: 🟡 PROVISIONAL. 실제 구현은 **별도 `u11-research-agent-frontend` 트랙**(U7 `u7-summarization-frontend` 선례). 본 FD는 UI 계약.

---

## 1. 컴포넌트 계층

```
ResearchAgentNavEntry (하단 네비 전용 메뉴, 로그인 필수)
  └─ ResearchAgentPage
       ├─ SessionListPanel (좌측/슬라이드 — 과거 세션 재열람·삭제)
       │    └─ SessionListItem[]
       ├─ ModeSelector (문헌탐색·근거형성 / novelty[차기 비활성])
       ├─ ConversationView
       │    ├─ TurnBubble[] (질의 + 응답)
       │    │    └─ AgentResponseRenderer (union 분기)
       │    │         ├─ EvidenceTableView (행=논문·열=주장/방법/결과/한계/출처 + 쟁점 태그)
       │    │         │    ├─ EvidenceCell (표 값·수식 KaTeX·캡션 — doc-model 렌더)
       │    │         │    └─ SourceAnchorLink ("출처 보기" → 리치뷰 locator 점프)
       │    │         ├─ PartialResultBanner (진행상태·degraded 소스)
       │    │         ├─ AbstainNotice / CostDegradedNotice / InputRejectedNotice
       │    └─ ProgressIndicator (NFR-P5 — 수 초~분·부분결과)
       └─ QueryComposer
            ├─ QueryInput (자연어)
            └─ AttachmentUploader (검증·무해화 피드백)
```

---

## 2. 컴포넌트별 props/state

| 컴포넌트 | props | state |
|---|---|---|
| `ResearchAgentPage` | `sessionId?` | `activeSession`, `streaming` |
| `SessionListPanel` | `sessions[]` | `selectedId` |
| `ModeSelector` | `mode`, `noveltyEnabled=false`(차기) | — |
| `ConversationView` | `turns[]` | `pendingTurn` |
| `AgentResponseRenderer` | `response: AgentResponse`(5종 union) | — |
| `EvidenceTableView` | `table: EvidenceTable` | `expandedRow?` |
| `SourceAnchorLink` | `anchor(paperId·locator·label)` | — |
| `ProgressIndicator` | `progress`, `degraded[]` | — |
| `QueryComposer` | `mode` | `text`, `attachments[]`, `errors[]` |
| `AttachmentUploader` | `accept`, `maxSize` | `uploading`, `rejected[]` |

---

## 3. 사용자 상호작용 흐름

1. **진입(US-RA1)**: 하단 네비 → 로그인 게이트(U3/U6) 통과 → `ResearchAgentPage`. 모드 선택 + 질의 입력.
2. **질의 전송**: `QueryComposer` → 모드 파이프라인 라우팅 → `ProgressIndicator` 노출(비차단) → 응답 점진 렌더(스트리밍/폴링).
3. **근거표 열람(US-RA3/RA4)**: `EvidenceTableView` 행별 논문 비교 + 쟁점 태그. 각 셀 "출처 보기" → 리치뷰(doc-model) 해당 locator로 점프·하이라이트.
4. **첨부(US-RA2)**: `AttachmentUploader` 업로드 → 형식/크기 검증 → 거부 시 명확한 오류. 분석 기준 자료로 사용.
5. **부분결과/저하(US-RA6)**: `PartialResultBanner`로 진행상태·degraded 소스 표시. 기권/비용저하/입력거부는 각 Notice.
6. **세션 재열람·삭제(US-RA5)**: `SessionListPanel`에서 과거 세션 선택 재열람; 세션·첨부 삭제/초기화 컨트롤(분리).

---

## 4. 폼 검증 규칙 (프런트 1차 — 서버 BR-RA-2 권위)

- 질의: 빈 입력/과대 길이 거부(프런트 힌트; 서버 정규화·격리 권위).
- 첨부: 허용 형식/크기만(서버 SEC-5/11 재검증 권위). 거부 사유 표시.
- 비로그인: 진입 차단·로그인 유도(SEC-8).

---

## 5. API 연동 지점 (U11 백엔드 계약)

| 컴포넌트 | 호출 | 응답 |
|---|---|---|
| `ResearchAgentPage` 진입 | `listSessions(userId)` | 세션 목록 |
| `SessionListItem` 선택 | `reopenSession(sessionId)` | 세션·턴·결과 |
| `QueryComposer` 전송 | `appendTurn(sessionId, query, attachments)` → `runEvidenceFormation` | `AgentResponse`(스트리밍/폴링·5종 union) |
| `AttachmentUploader` | 첨부 업로드(검증·무해화) | `AttachmentRef` / 거부 |
| `SourceAnchorLink` | 리치뷰 doc-model 조회(locator 점프) | doc-model 렌더(U5/U7-frontend `DocModelViewer` 재사용) |
| 삭제/초기화 | `deleteSession`/`deleteAttachment`/`resetHistory` | ack |

---

## 6. 재사용 · 경계

- **리치뷰 렌더**: `DocModelViewer`(U5/U7-frontend) 재사용 — 출처 앵커 locator 점프·KaTeX 수식·표 컴포넌트·그림 webp. 별도 재구현 금지.
- **진행상태/스트리밍 전송 방식**(SSE/폴링)·상태관리 라이브러리는 **NFR/Code 결정**.
- **novelty 모드 UI**는 차기(비활성 placeholder만 — Q14/BR-RA-17).
- 구현은 별도 `u11-research-agent-frontend` 트랙.
