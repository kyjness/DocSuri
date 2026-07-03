# U7 Summarization — NFR Design Patterns (설계 패턴)

**단계**: CONSTRUCTION → NFR Design · **유닛**: U7 Summarization · **일자**: 2026-06-19
**근거**: 계획서 `u7-summarization-nfr-design-plan.md`(10문 전수 A) · NFR Requirements(TD-S1~S12) · FD(BR-S1~S14·INV).
**페이즈 3 amendment(2026-06-29, 코드 검증)**: §1.3 비용 degradeMode 임계(ratio ≥0.80)·검색 대비 도메인별 저하 매핑(U7=일괄 기권, lexical 폴백 없음) 명문화 · §2.1 저장 불변식(S3 영구 immutable + Redis TTL 필수) 정합.
**고도**: 패턴·정책·범위. 수치(타임아웃 ms·TTL·서킷 임계·토큰 캡·동시성)는 Infra/Code-gen.

---

## 1. 복원력 패턴 (Resilience — RES-9 / NFR-R2)

### 1.1 Bedrock 호출 격리 (Q1)
- **명시 타임아웃 + 1회 재시도(백오프) + 서킷브레이커** → 장애 시 **기권**(`AbstainDTO`, FR-11 저하 모드).
- **격리**: 캐시 HIT 경로(LLM 0콜)는 Bedrock 장애와 무관(가용성 유지). 검색 경로(U2)와도 분리.
- 재시도 1회로 폭주 방지. 수치(타임아웃/백오프/서킷 임계)는 Infra/Code-gen.

### 1.2 근거화 실패 재시도 (Q2 / BR-S7)
- 결정적 게이트(앵커 실재·수치 일치·스키마·잘림) **1차 실패 → 1회 재생성 → 그래도 실패 시 기권**(fail-closed).
- **정당한 코퍼스밖 abstain**은 재시도 없음(정상 동작).
- **재시도 카운트 분리**: 근거화 재시도(생성 변동 흡수) ≠ Bedrock 장애 재시도(1.1) — 의미·카운트 별개.

### 1.3 저하 3계층 구분 ⭐ (Q3)
세 가지를 **원인·행동·종단 상태·텔레메트리**로 명확히 분리:

| 계층 | 원인 | 트리거 | 종단 상태 | 신호 |
|---|---|---|---|---|
| **비용 degradeMode** | 예산 임계 (spend ratio **≥0.80**) | U6 `get_budget_state()` degradeMode가 non-normal(0.80 `RERANK_OFF`/0.95 `LEXICAL_ONLY`/≥1.0 hard_cap) | `CostDegradedDTO`("AI 요약 일시 중단") | RES-11a(비용 폭발) |
| **의존성 서킷** | Bedrock 장애/타임아웃/스로틀 | 서킷 OPEN(1.1) | `AbstainDTO` | RES-11(가용성) |
| **소스 저하** | 전문 부재/라이선스X | `FullTextSourceAdapter` 미스 | 초록 폴백(+메타) 또는 `SourceUnavailableDTO` | NFR-R2 |

> 셋은 **U6 단일 권위 비용 판정**(degradeMode)과 **U7 의존성 장애**(서킷)와 **데이터 가용성**(소스)으로 책임이 다르다. 통합 금지(운영 진단 모호해짐).
> **검색 신호 재사용·매핑 차이(코드 검증)**: U7은 U6의 동일 `degradeMode` 신호를 소비하되, 검색(U2)이 `RERANK_OFF`/`LEXICAL_ONLY`에서 **부분 저하(lexical 폴백)** 로 계속 응답하는 것과 달리, U7 오케스트레이터(`_is_cost_degraded`)는 **non-normal 전부를 일괄 기권**한다 — 요약/번역은 LLM이 필수라 lexical 대체가 없기 때문. 즉 신호는 공유, **저하 매핑은 도메인별**.

---

## 2. 성능 패턴 (Performance — NFR-P2)

### 2.1 캐시 우선 (Q4 / §11)
- **read-through**(Redis 핫 → S3 영구) → 미스 → 생성 → **write-through**(S3 + Redis).
- 키 = immutable `SummaryCacheKey`. **캐시 HIT = LLM 0콜 즉시**(TTFB 주 경로·비용 0).
- 무효화 = 키(modelVer/promptVer/glossaryVer/seedVer/version) 변경 = 신규 객체(자동, stale 없음). TTL/라이프사이클은 Infra.
- **NFR-C1(중복 호출 방지) 강화**: translate `glossaryVer`=프롬프트-강제 시그니처(요약과 대칭)라, 약한 용어만 편집하거나 사용자 간 약한 용어가 달라도 **동일 공유 베이스**로 de-dup(약한 후치환은 읽기시 오버레이) — 종전 전체 카운터 키가 부르던 사용자별·편집별 동일-산출물 재번역을 제거. seedVer는 시드 편집만 정확히 무효화(무변경 배포는 캐시 유지).
- **동시 map(BR-S6/S18)**: 긴 번역/요약의 청크 map은 바운드 동시 실행(`map_bounded`) — 지연 감소·**비용 중립**(호출 수·산출물 불변). 워커 상한은 Bedrock 스로틀/TPM 대비 보수적(번역>요약 상한, 요약 청크가 큼).
- **저장 불변식(코드 검증)**: S3 = **영구·immutable**(write-through 원천), Redis 핫 = **TTL 필수**(`s3_redis_store.py` `set(..., ex=ttl)` — 만료없는 키 금지). 미스 시 S3 원천 read → Redis backfill. **요약·초록번역·전문번역(DocModel v1) 3종 동일** 저장 모델(키 차원만 상이).

### 2.2 스트리밍 ↔ 근거화 패턴 ⭐ (Q5 / BR-S8 / FR-5)
§3 구조화 JSON은 앵커·스키마가 **전체 draft에 의존** → 안전 우선:
```
Bedrock 스트림 ──▶ [내부 버퍼](liveness·타임아웃 관리)
                        ▼ 완성 draft
                  GroundingValidator(결정적) ──┬─ pass ─▶ 클라이언트 점진 렌더(통과 필드부터)
                                               └─ fail ─▶ 1회 재시도 → AbstainDTO
```
- **근거 없는 토큰 클라이언트 유출 0**(FR-5 절대 우선). 첫 생성 TTFB = 생성+검증 종속, **즉시 체감은 캐시 HIT가 담당**.
- 내부 스트리밍은 liveness·타임아웃·부분 진행 관리용. 구체 버퍼/부분렌더 전략은 Code-gen.

### 2.3 async I/O
Bedrock·S3·Redis·RDS 외부 호출 async — 온디맨드 동시성 확보(스레드 블로킹 회피).

---

## 3. 확장성 패턴 (Scalability)

### 3.1 stateless + 공유 외부 상태 (Q6)
- 모듈 **stateless**(로컬 인메모리 상태 없음) → backend 인스턴스 수평 복제.
- 캐시/상태 = **공유 외부 스토어**(S3+Redis) → 인스턴스 간 히트율·일관성. 키 immutable로 일관성 보장.

### 3.2 Bedrock 동시성/쿼터 (Q7)
- **async I/O + 계정 쿼터 내 동시 호출**; `ThrottlingException` → 백오프/기권(1.1 경로 흡수). 쿼터·오토스케일 수치는 Infra. 비용 상한은 U6 CostGuard.

---

## 4. 보안 패턴 (Security — 방어심층, Q8)

| 위치 | 패턴 | 요구 |
|---|---|---|
| `SummarizationController`(진입) | 요청 검증 | SEC-5 |
| `InputRefiner` | **본문 격리** `[지시]┃[데이터]<paper>…</paper>` (프롬프트 인젝션 방어) | BR-S3 |
| `ResultAssembler`(출력) | **SEC-9 비노출 필터**(토큰·비용·캐시키·모델/프롬프트 식별자 차단) | INV-3 |
| 전역 예외 핸들러(FastAPI) | **fail-closed**(일반화·스택 비노출) | INV-4·SEC-15 |
| `GlossaryRepository`(RDS) | **owner 스코프**(개인 용어집 cross-user 누출 차단) | SEC-8 |
| 로깅 | 원문/번역/프롬프트 PII·저작권 무분별 로깅 금지 | SEC-3 |
| **위임** | 인증·레이트리밋 = U6 게이트웨이(이중 방어심층) | SEC-8/11 |

---

## 5. 배포 · 복원력 테스트 (Q10 / RES-12 / QT-5)

### 5.1 CI 레인 (real-first)
- **항상 실행**: 단위(pytest, **테스트 Fixture/Stub** + Hypothesis PBT-S1~S5) + ruff + shared 드리프트 가드.
- **별도 게이트 레인**: 통합 테스트(실 Bedrock/S3/Redis/RDS) — 자격증명 필요(Infra 구성), PR 게이트 또는 주기 실행.
- **⚠️ backend 공유 CI/CD — app-shell(@ELSAPHABA)/Infra 조율.**

### 5.2 복원력 폴트 인젝션 (RES-12)
- Bedrock 장애/타임아웃 → 기권(1.1) · 전문 부재 → 초록 폴백(1.3) · 비용 OPEN → `CostDegradedDTO`(1.3) · 근거화 실패 → 1회 재시도→기권(1.2) · 인젝션 입력 → 본문 격리(§4). **QT-5/RES-11 연동**(실행은 Build&Test/Operations).

---

## 6. 추적성 매트릭스 (패턴 ↔ NFR/BR/검증)

| 패턴 | NFR/요구 | BR/INV | 검증 |
|---|---|---|---|
| §1.1 Bedrock 격리 | RES-9, NFR-R2 | BR-S7 | 폴트 인젝션(5.2) |
| §1.3 저하 3계층 | NFR-C1, RES-9, NFR-R2 | BR-S9/S13 | 폴트 인젝션 |
| §2.1 캐시 우선 | NFR-P2 | BR-S1, INV-5 | PBT-S1 |
| §2.2 스트리밍↔근거화 | NFR-P2, FR-5 | BR-S8, INV-4 | PBT-S5·통합 |
| §3 stateless/쿼터 | NFR-S, 가용성 | — | 통합 |
| §4 보안 방어심층 | SEC-3/8/9/11/15 | BR-S14, INV-3/4 | 단위·통합 |
| §5 CI/복원력 | QT-5, RES-12 | PBT-S1~S5 | CI |

**커버리지**: NFR-P2·NFR-C1·RES-9·NFR-R2·QT-5·RES-11/12·SEC-3/8/9/11/15·FR-5/11 (미커버 0).
