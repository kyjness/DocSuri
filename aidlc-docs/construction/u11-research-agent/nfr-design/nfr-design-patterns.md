# U11 Research Agent — NFR Design Patterns (설계 패턴)

**단계**: CONSTRUCTION → NFR Design · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**근거**: 계획서 `u11-research-agent-nfr-design-plan.md`(**Q1~Q14 전부 A**) · NFR Requirements(TD-RA-1~15) · FD(BR-RA·INV-U11) · 아키텍처 게이트 `docmodel-fulltext-index-pivot-plan.md`.
**선례 종합**: U7(저하 3계층·캐시우선·스트리밍↔근거화·real-first) · U2(의존성별 서킷·fail-fast·예산 분해·병렬) · U3(Redis 서킷·fail-closed·외부 API 복원력) · U8(쿼터).
**고도**: 패턴·정책·범위. **수치(타임아웃 ms·TTL·서킷 임계·K 상한·동시성·토큰 캡)·캐시 스토어·배포 타깃·리전은 Infra/Code-gen.**

---

## 1. 복원력 패턴 (Resilience — RES-9/11 / NFR-R1/R2)

### 1.1 의존성별 독립 격리 (Q1=A — U2 1.2 / U3 §1 패턴)
'의존성'은 인프라 프리미티브가 아니라 **U11이 직접 호출하는 실패 도메인** 단위. 한 의존성 장애가 전체로 전파되지 않게 거동을 분리한다.

| 직접 의존(실패 도메인) | 뒤의 인프라 | 서킷/격리 OPEN 시 거동 | 트레이스 |
|---|---|---|---|
| **① 후보 검색** (U2 재사용) | OpenSearch·질의 임베딩(**서킷=U2 내부**) | `AbstainDTO`(후보 0·빈 성공 금지) | RES-9, NFR-R1 |
| **② doc-model 읽기** | S3·캐시·빌드 | 해당 논문 제외 → `PartialResultDTO`(degraded) | RES-9, NFR-R2 |
| **③ Bedrock LLM** | Bedrock(U6 게이트웨이) | 타임아웃+1회 재시도+서킷 → 기권/부분 | RES-9, NFR-R2 |
| **④ U6 근거화·CostGuard** | U6 | fail-closed(근거 불가=기권 / 비용 OPEN=`CostDegradedDTO`) | FR-5, NFR-C1 |
| **⑤ 세션 스토어 / 결과 캐시** | RDS / Redis | RDS→fail-closed(영속 불가 명시 실패) · Redis→영구 폴백/재생성 | NFR-R1, U3 정신 |

> ⚠️ **OpenSearch는 보통 U11 직접 서킷 아님** — U2 검색 재사용 시 OpenSearch 서킷은 U2 소유(U2 NFR Design: 임베딩→lexical, 인덱스→fail-closed). *U11이 공유 인덱스를 직접 질의하면 그땐 U11 직접 의존 — "U2 API 재사용 vs 직접 질의"는 FD Q2 NFR/Code 미정.*

### 1.2 저하 4계층 분리 ⭐ (Q2=A — U7 1.3 확장)
원인·트리거·종단상태·신호가 다른 저하를 **통합하지 않는다**(운영 진단 명확):

| 계층 | 원인 | 트리거 | 종단 상태 | 신호 |
|---|---|---|---|---|
| **비용 degradeMode** | 예산 임계 | U6 `getBudgetState()` OPEN/저하 | `CostDegradedDTO` | RES-11a(비용 폭발) |
| **의존성 서킷** | 검색/doc-model/Bedrock 장애 | 서킷 OPEN(1.1) | 기권 또는 부분 | RES-11(가용성) |
| **fan-out 부분실패** | K 논문 중 일부 추출 실패 | 논문별 실패 | `PartialResultDTO`(degraded 소스) | RES-11c(반쪽 결과) |
| **근거 부재** | 코퍼스밖·근거 없음 | 근거화 abstain | `AbstainDTO` | (정상 동작) |

### 1.3 재시도 정책 (Q3=A — U7 1.1/1.2 분리)
- **Bedrock 호출 장애 재시도**(1회·백오프) ≠ **근거화 1차 실패 재시도**(1회→그래도 실패 시 **항목 기권**). 의미·카운트 별개 → 폭주 방지.
- **정당한 코퍼스밖 기권**은 재시도 없음(정상). 수치는 Infra.

### 1.4 fan-out 부분 실패 (Q4=A — U11 고유 · NFR-P5)
K 논문 중 일부 실패해도 **완료분으로 부분결과**(degraded 소스 명시), 전체 실패·조용한 누락 금지(INV-U11-5·NFR-R1).

---

## 2. 성능 패턴 (Performance — NFR-P5)

### 2.1 캐시 우선 (Q5=A — U7 2.1 / U2 2.2)
- **read-through**(Redis 핫 → 영구) → 미스 → 생성 → **write-through**. 키 = immutable `AgentCacheKey`. **HIT = LLM 0콜 즉시**.
- 무효화 = 키(코퍼스 스냅샷/model/promptVer) 변경 = 신규 객체(stale 없음). **단일-턴 분석만 캐시**(멀티턴 대화는 세션 영속). TTL = Infra.

### 2.2 스트리밍 ↔ 근거화 (Q6=A — U7 2.2 / FR-5)
```
Bedrock 스트림 ─▶ [내부 버퍼](liveness·진행상태) ─▶ 항목/논문별 근거화(U6) ─┬─ pass ─▶ 점진 노출
                                                                            └─ fail ─▶ 1회 재시도 → 항목 기권
```
- **근거 없는 토큰 클라이언트 유출 0**(FR-5 절대 우선). 부분결과는 통과분만.

### 2.3 bounded 병렬 fan-out (Q7=A — U2 2.3 병렬 + U7 2.3 async)
- 논문별 추출을 **async I/O로 동시 실행하되 동시성 상한**(K·concurrency) → Bedrock 쿼터·비용 폭주 방지. 수치 = Infra.

### 2.4 sync ↔ async 잡 라우팅 (Q8=A — U7 TD-S9 3밴드)
- **소규모=동기 스트리밍 / 대규모=SQS 비동기 잡(폴링→캐시 히트) / OVER_CAP=거절**. 게이트웨이 타임아웃(~29s) 회피. 임계 = Infra/튜닝.

---

## 3. 확장성 패턴 (Scalability)

### 3.1 stateless + 공유 외부 상태 (Q9=A — U7 3.1 / U2 3.1)
- 모듈 **stateless** → backend 인스턴스 수평 복제. 대화/세션=RDS, 결과 캐시=Redis+영구, **서킷 상태 인스턴스 간 공유**(일관). 비동기 워커는 별도 스케일.

### 3.2 fan-out의 Bedrock 쿼터 증폭 (Q10=A — U7 3.2 / RES-8)
- fan-out = 단건의 K배 호출 → **bounded 동시성 + `ThrottlingException` 백오프/큐잉 → 부분/기권**(1.1 흡수). 비동기 잡으로 분산. 쿼터·오토스케일 = Infra. 비용 상한 = U6 CostGuard.

---

## 4. 보안 패턴 (Security · 방어심층 — Q11=A)

| 위치 | 패턴 | 요구 |
|---|---|---|
| 진입 `ConversationInputHandler` | 질의 검증 | SEC-5 |
| `AttachmentIngestor` | 형식/크기 검증·무해화·실행파일 거부 → `InputRejectedDTO` | SEC-5, BR-RA-2 |
| 추출 입력 | **본문 격리** `[지시]┃[데이터]<paper>…</paper>` (인젝션 방어) — 첨부·논문 텍스트는 데이터 | BR-RA-11(U7 BR-S3) |
| 출력 `EvidenceTableAssembler` | **SEC-9 비노출**(캐시키·모델/프롬프트·raw 점수·자산 픽셀 차단) | SEC-9 |
| 자산 서빙 | 그림 단기 **서명 URL**(doc-model엔 assetId 참조만) | SEC-9/12 |
| `ResearchResultStore`(RDS)·첨부(S3) | **owner 스코프**(cross-user 누출 차단)·삭제/초기화 분리 | SEC-8, BR-RA-1/15 |
| 전역 예외 핸들러 | **fail-closed**(일반화·스택 비노출) | SEC-15 |
| 로깅 | 질의/첨부/본문 PII·저작권 무분별 로깅 금지 | SEC-3 |
| **위임** | 인증·레이트리밋 = U6 게이트웨이(이중 방어심층) | SEC-8/11 |

---

## 5. 배포 · 복원력 테스트 (Q13/Q14=A — U7 §5 / U2 §5 / RES-12)

### 5.1 CI 레인 (real-first)
- **항상**: 단위(pytest **테스트 Fixture/Stub** + Hypothesis **PBT-RA1~6**) + ruff + shared 드리프트 가드.
- **별도 게이트**: 통합(실 U2/doc-model/Bedrock/RDS/Redis/S3) — 자격증명(Infra).
- **비동기 Agent 워커·프런트(`u11-research-agent-frontend`) 별도 배포/레인.** ⚠️ **조율 존(`backend/wiring.py`·게이트웨이) = app-shell 사인오프.**

### 5.2 복원력 폴트 인젝션 (RES-12 · QT-8/RES-11 연동)
U2 검색 장애→`Abstain` · doc-model 일부 장애→`Partial` · Bedrock 타임아웃/스로틀→재시도/기권 · 비용 OPEN→`CostDegraded` · 근거화 실패→1회 재시도→항목 기권 · injection 첨부→본문 격리 · fan-out 부분 실패→`Partial`. 실행 = Build&Test/Operations.

---

## 6. 추적성 매트릭스 (패턴 ↔ NFR/BR/검증)

| 패턴 | NFR/요구 | BR/INV | 검증 |
|---|---|---|---|
| §1.1 의존성별 격리 | RES-9, NFR-R1/R2 | BR-RA-4/7/14 | 폴트 인젝션(5.2) |
| §1.2 저하 4계층 | NFR-C1, RES-9/11 | BR-RA-10/14/18 | 폴트 인젝션 |
| §1.3 재시도 분리 | RES-9 | BR-RA-7 | 폴트 인젝션 |
| §1.4/2.x fan-out 부분·병렬 | NFR-P5 | BR-RA-14 | 통합·폴트 인젝션 |
| §2.1 캐시 우선 | NFR-P5, NFR-C1 | BR-RA-12 | PBT-RA4 |
| §2.2 스트리밍↔근거화 | NFR-P5, FR-5 | BR-RA-7 | PBT-RA2·통합 |
| §3 stateless/쿼터 | NFR-S, RES-8 | — | 통합 |
| §4 보안 방어심층 | SEC-3/5/8/9/11/15 | BR-RA-1/2/11 | 단위·통합·보안스캔 |
| §5 CI/복원력 | QT-8, RES-12 | PBT-RA1~6 | CI·폴트 인젝션 |

**커버리지**: NFR-P5·NFR-C1·RES-9/11·NFR-R1/R2·QT-8·SEC-3/5/8/9/11/15·FR-5/11 (미커버 0). granularity(GQ1)·랭킹(GQ2)·수치는 [열림]→Infra/실험.
