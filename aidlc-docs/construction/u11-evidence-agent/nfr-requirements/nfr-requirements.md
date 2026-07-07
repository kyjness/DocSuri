# U11 Evidence Formation Agent — NFR Requirements (비기능 요구사항)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U11 Evidence Formation Agent · **일자**: 2026-06-30
**근거**: FD 산출물(domain-entities.md · business-rules.md · business-logic-model.md) · `requirements.md`(NFR-P6·NFR-C1·NFR-R2·NFR-O1·SEC·QT-8·FR-5·C-2) · 전역 계승(U1~U7 tech-stack).
**고도**: NFR 목표(정책 형태) + 스택 종류. 구체 수치(TTFB·토큰 캡·재시도 횟수·SQS 임계·서킷 임계·Redis TTL)·리전/IaC·CI 설정은 **NFR Design/Infra/Build&Test 이월**.

---

## 1. 컨텍스트 · NFR 동인

U11 = **다논문 근거형성 Agent API 모듈**(배포 ① backend 모놀리스). 검색 SLA(NFR-P1) **비대상**. 핵심 동인:

| 동인 | 내용 |
|---|---|
| **NFR-P6** | Agent 실행 = 다수 LLM 호출(추론·추출) — **스트리밍 first-token + 비동기 잡 오프로드** |
| **NFR-C1** | 비용 상한 — Agent 1회 턴 = 복수 LLM 호출 → 비용 노출 큼. CostGuard 게이트 필수 |
| **NFR-R2** | Bedrock · OpenSearch · S3 · RDS 다중 외부 의존성 격리 |
| **NFR-O1** | Agent 턴 지연·비용·스트리밍 건강도·근거화 결과 관측성 |
| **QT-8** | 근거형성 날조 금지·기권 안전성·소유권 격리 속성 검증 |
| **D5** | EvidenceFormationPort FROZEN 계약 — U12 소비 표면, U11 구현 책임 |

---

## 2. 성능 (NFR-P6)

| 항목 | 요구 (형태) | 근거 |
|---|---|---|
| 스트리밍 first-token | SSE 스트리밍으로 **빠른 TTFB** 구현. Agent 추론 토큰을 점진 전송. | NFR-P6, US-EV2 |
| 동기 경로(단순 분석) | 소수 논문·첨부 없음 — **동기 SSE 스트리밍**으로 완료. | NFR-P6 |
| 비동기 잡(장기 분석) | 다수 논문·첨부 포함 — **SQS 잡 enqueue → TurnPendingResult → 폴링**. Agent 실행은 워커(게이트웨이 타임아웃 회피). | NFR-P6, BR-EV-6 |
| 세션 조회 | 인덱싱된 (ownerId, sessionId) — **DB 조회 수준** 응답. | FR-36, FR-38 |
| 콜드스타트 | **long-running 컨테이너 가정**(콜드스타트 제외). | — |
| 검증 수치 | TTFB·Agent 완료 분포 실측은 **Build&Test**. | NS-1 |

- **스트리밍 타이밍**: 결과 확정(날조 금지 검증) 전까지 최종 claims 미노출 — TTFB와 INV-EV-3(날조 금지) 균형.
- **비동기 잡도 동일 날조 금지·기권 규칙** 적용(BR-EV-1, INV-EV-2, INV-EV-3).

---

## 3. 확장성 (NFR-S 계열)

- **stateless Agent 모듈** — 세션 상태는 RDS(영속), 수평 복제 가능.
- **async I/O**: Bedrock·OpenSearch·S3·RDS 외부 대기 중첩(Agent 내 Tool 호출 병렬 가능).
- **Bedrock 동시 호출 = 계정 쿼터 내**; 초과 시 큐잉/저하. 오토스케일 트리거·쿼터 수치는 Infra.
- **비동기 워커**: Agent 워커 = 별도 배포 단위(Infra 이월, U7 패턴 계승 — TD-E9).

---

## 4. 가용성 (NFR-P6 비-SLA)

- **온디맨드 비-SLA** — 검색(NFR-P1·NFR-A1)과 분리.
- **격리**: U11 장애(Bedrock/OpenSearch/S3)는 **기권/저하**(TurnAbstainResult·TurnErrorResult)로 흡수. **핵심 검색 경로에 영향 없음**.
- 외부 의존성별 장애 처리 정책: §5 신뢰성 참조.

---

## 5. 신뢰성 (RES-9 / NFR-R2)

| 외부 의존성 | 장애 처리 | 결과 |
|---|---|---|
| **Bedrock(LLM)** | 타임아웃 + 재시도(1회) + 서킷브레이커 | TurnErrorResult{ cost_degraded 또는 llm_unavailable } |
| **OpenSearch(U2)** | 타임아웃 → IndexUnavailable 전달 | TurnAbstainResult{ out_of_corpus } |
| **S3(DocModel)** | 개별 논문 DocModel 읽기 실패 → 해당 논문 건너뜀 | 부분 실패 허용 — 나머지 논문으로 계속 |
| **RDS(세션)** | 타임아웃 + 재시도 → 실패 시 에러 | TurnErrorResult |
| **SQS(잡 큐)** | best-effort enqueue — 실패 시 동기 경로 fallback(가능 시) 또는 에러 | TurnErrorResult |

- **fail-closed**(BR-EV-12): LLM 장애·타임아웃·비용 OPEN → 기권 또는 에러. 스택 트레이스·내부 오류 상세 사용자 노출 금지(SEC-9, INV-EV-5).
- **구체 타임아웃·서킷 임계 = NFR Design/Infra**.

---

## 6. 비용 (NFR-C1)

- **기존 $1,600/월 상한 내 흡수** + **U11 별도 텔레메트리 라인**(Agent 턴당 모델·토큰·비용 계상).
- **비용 특성**: Agent 1회 턴 = 복수 LLM 호출(추론 반복 + 추출) — U7 요약 대비 **전형적으로 더 큰 비용 노출**. 페이퍼 수·첨부 유무에 따라 비용 편차 큼.
- **U6 CostGuard 게이트**(BR-EV-7): spend ratio ≥ 0.80(`cost_guard.py warning_ratio`) 도달 시 `get_budget_state()`의 circuit_state가 non-normal → U11 오케스트레이터는 LLM 호출 **직전** 게이트 확인 후 OPEN/저하 → `TurnErrorResult{ errorCode: "cost_degraded" }`. U11은 **비용 판정 재구현·재판정 없음**(U6 단일 권위).
- **LLM 폴백 없음**: 비용 OPEN 시 요약처럼 lexical 폴백 불가(Agent 추론은 LLM 필수) → 모든 non-normal degrade를 일괄 `cost_degraded` 처리.
- Infra 비용표에 U11 라인 추가(설계 입력 §8).

---

## 7. 보안 (SEC)

| 처분 | 소관 | 내용 |
|---|---|---|
| **인증/인가** | 위임(게이트웨이/U3) | SEC-8 — U11은 ctx 신뢰. 소유권 결정 = U3.AuthorizationGuard(INV-EV-1) |
| **레이트리밋·남용 방어** | 위임(U6 게이트웨이) | SEC-11 — 비용 발생 기능(Agent 실행은 단가 높음) |
| **내부 필드 비노출** | U11 직접 | SEC-9/INV-EV-5 — 벡터 점수·청크 ID·LLM 내부 상태·근거화 위반 상세 외부 DTO 비노출 |
| **날조 방어** | U11 직접 | C-2/INV-EV-3 — LLM 추출 지시 구조화: `[지시]|[데이터]<paper>…</paper>` (태그 안은 데이터) |
| **첨부 미저장** | U11 직접 | C-1/INV-EV-4 — 첨부 원시 파일 DocModel 추출 즉시 폐기 |
| **소유권 격리·타인 세션** | U11 직접 | INV-EV-1/SEC-9 — 타인 세션 접근 시도 → 404(존재 여부 비노출) |
| **PII/저작권 로깅** | U11 직접 | SEC-3 — 원문·추출 명제·프롬프트 무분별 로깅 금지 |
| **공급망** | 공유(backend 모노레포) | SEC-10 — 락파일·SCA·SBOM·이미지 핀 |

---

## 8. 관측성 (NFR-O1)

- **`ObservabilityHub.emit*`** 로 제출:
  - **메트릭**: Agent 턴 지연(전체·Tool별)·LLM 호출 횟수·입출력 토큰·비용 추정·스트리밍 건강도(first-token 지연·중단율)
  - **이벤트**: 기권 사유(`out_of_corpus`·`insufficient_evidence`·`cost_degraded`)·Tool 호출 순서·근거화 결과(통과/기권)
  - **로그**: requestId 상관 구조화 로그. PII/원문 포함 금지(SEC-3).
- **응답 경로 밖**(fire-and-forget). 발행 실패는 응답에 영향 없음.
- NFR-C1 비용 라인·QT-8 운영 모니터링 표면. U6 단일 권위 소비.

---

## 9. 유지보수성 · 테스트 (QT-8)

### 9.1 real-first 테스트 전략
- **Production Mock Adapter는 구현하지 않는다.** 출하 코드 = 포트 + 실 어댑터 단일본(Bedrock·OpenSearch·S3·RDS·SQS).
- **단위 테스트**: 도메인/오케스트레이션 로직을 **테스트 전용 Fixture/Stub**(출하 어댑터 아님)로 검증 — 허용. + Hypothesis PBT.
- **통합 테스트**: **실 의존성**(Bedrock·OpenSearch·S3·RDS·U6 후크) 대상. 자격증명/엔드포인트 구성 = CI/Infra.
- **QT-8 근거형성 불변식 평가셋**: U11은 출력 표면(claims·기권 결정) 제공, **평가 실행 소유 = U6/OP**.

### 9.2 PBT 속성 (QT-8 / Hypothesis)

| ID | 속성 | 검증 방식 |
|---|---|---|
| PBT-EV-1 | `claims=[]` → 반드시 `state=abstain` (INV-EV-2) | 임의 빈 claims 입력 → TurnAbstainResult 단언 |
| PBT-EV-2 | 임의 `userId`로 타인 세션 조회 시 항상 404 (INV-EV-1) | 세션 소유자 ≠ 요청자 → 404 단언 |
| PBT-EV-3 | `TurnResult` 직렬화에 벡터 점수·청크 ID·LLM 메타 미포함 (INV-EV-5) | 직렬화 출력 필드 열거 단언 |
| PBT-EV-4 | `explicit` scope 결과의 `SourceRef.paperId` ⊆ 명시 집합 (BR-EV-2, INV-EV-3) | 임의 paperIds 입력 → 결과 출처 집합 포함 단언 |
| PBT-EV-5 | `EvidenceResult`·`EvidenceAbstainResult` 직렬화·역직렬화 후 D5 스키마 계약 일치 | JSON 라운드트립 단언 |

차단성/권고 분류는 전역 PBT 정책 계승.

### 9.3 빌드
모노레포 — `backend/modules/evidence_agent/` 독립 pyproject + backend 모놀리스 마운트. 드리프트 가드(shared 계약)·CI 레인은 NFR Design/Infra.

---

## 10. 추적성 매트릭스

| NFR/결정 | 요구사항 | 스토리 |
|---|---|---|
| §2 NFR-P6 스트리밍·비동기 잡 | NFR-P6 | US-EV2, US-EV9 |
| §5 Bedrock·OpenSearch·S3 격리·기권 | RES-9, NFR-R2 | US-EV6, US-EV9 |
| §6 비용 라인·CostGuard | NFR-C1 | US-EV9 |
| §7 보안 처분(인가·비노출·날조·첨부·소유권) | SEC-3/8/9/10/11, C-1/C-2 | US-EV4, US-EV6, US-EV7 |
| §8 관측성 | NFR-O1 | US-EV9 |
| §9 테스트·PBT·근거화 | QT-8, FR-5 | US-EV2, US-EV3, US-EV6 |
| D5 포트 구현(EvidenceFormationPort) | D5 | — (U12 소비) |

**커버리지**: NFR-P6·NFR-C1·NFR-R2·NFR-O1·SEC-3/8/9/10/11·FR-5·C-1/C-2·QT-8·D5·US-EV1~EV9 (미커버 0).
