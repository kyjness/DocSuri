# U7 Summarization — NFR Requirements (비기능 요구사항)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U7 Summarization · **일자**: 2026-06-19
**근거**: 계획서 `u7-summarization-nfr-requirements-plan.md`(15문 전수 A) · FD 산출물 · `requirements.md`(NFR-P2·NFR-C1·QT-5·RES-9·NFR-R2·SEC) · 전역 계승(U1/U2/U3 tech-stack).
**페이즈 3 amendment(2026-06-29, 코드 검증)**: §6 비용 게이트 임계 정밀화(spend ratio ≥0.80 = `cost_guard.py warning_ratio`) · §2 온디맨드 3종(요약·초록번역·**전문번역** DocModel v1) 동일 영구저장 모델 명문화 · §9 QT-1 충실도 평가 하니스(요약 도메인) 등재. FROZEN `get_budget_state` 무변경.
**고도**: NFR 목표(정책 형태) + 스택 종류. 구체 수치(TTFB·토큰 캡·서킷)·리전/IaC·CI는 NFR Design/Infra/Build&Test.

---

## 1. 컨텍스트 · NFR 동인

U7 = **온디맨드 요약/번역 API 모듈**(배포 ① backend 모놀리스). 검색 SLA(NFR-P1) **비대상**. 핵심 동인: **NFR-P2**(온디맨드 응답) · **NFR-C1**(비용 상한·신규 Sonnet 라인) · **RES-9/NFR-R2**(Bedrock 의존성 격리) · **QT-5**(근거화).

---

## 2. 성능 (NFR-P2 — 온디맨드, NFR-P1 비대상)

| 항목 | 요구 (형태) | 근거 |
|---|---|---|
| 캐시 HIT | **즉시 응답**(LLM 0콜·스토어 조회 수준). 주 경로. | Q7·US-S5 |
| 첫 생성(MISS) | **스트리밍 first-token(빠른 TTFB)** 으로 체감 관리. 완료까지 수십 초 가능(Sonnet 풀논문)이나 **완료 시간은 SLA 아님**. | Q2·Q7 |
| 콜드스타트 | **long-running 컨테이너 가정**(콜드스타트 제외). | Q7 |
| 검증 수치 | TTFB·완료 분포 **실측은 Build&Test**. | NS-1 |

- **버퍼-검증-스트리밍**(BR-S8): 근거화 통과분부터 노출 — TTFB와 날조 0(FR-5)의 균형. 구체 버퍼 전략 수치는 NFR Design/Code-gen.
- **온디맨드 3종 동일 모델**(요약·초록번역·**전문번역**[DocModel v1]): 셋 다 온디맨드 생성 + **영구저장**(S3 permanent immutable + Redis hot **TTL 필수**·만료없는 키 금지, `s3_redis_store.py`) + bounded 과금(§6). 캐시 키 차원만 다름(task·scope·persona·glossaryVer). 전문번역은 검증 결과 이미 동작(정합 확인).

---

## 3. 확장성 (NFR-S 계열)

- **stateless 모듈 + 수평 확장**(backend 인스턴스 복제). 세션 상태 없음.
- **async I/O**: Bedrock·S3·Redis·RDS 외부 대기 중첩(온디맨드 동시성 확보).
- **Bedrock 동시 호출 = 계정 쿼터 내**; 초과 시 큐잉/저하. 오토스케일 트리거·쿼터 수치는 Infra(RES-8). (Q9)

---

## 4. 가용성 (NFR-P2 비-SLA)

- **온디맨드 비-SLA** — 검색(NFR-P1·NFR-A1)과 분리. (Q10)
- **격리**: U7 장애(Bedrock/스토어)는 **우아한 기권/저하**(FR-11)로 흡수, **핵심 검색 경로에 영향 없음**.
- 캐시 HIT 경로 = 스토어 가용성 의존; 생성 경로 = Bedrock 가용성 의존. 별도 높은 SLA 미설정.

---

## 5. 신뢰성 (RES-9 / NFR-R2)

- **Bedrock 의존성 격리**: 명시 **타임아웃 + 재시도(1회) + 서킷브레이커** → 장애 시 **기권**(저하 모드, FR-11). (Q11·BR-S7)
- **재시도 구분**: ① 근거화 1차 실패 재시도(1회, BR-S7) ② LLM 호출 장애 재시도(1회) — 폭주 방지.
- **전문 부재 → 초록 폴백**(BR-S2·NFR-R2). 전문·초록 모두 부재 → `SourceUnavailableDTO`.
- 구체 타임아웃/서킷 임계 = NFR Design/Infra.

---

## 6. 비용 (NFR-C1)

- **기존 $1,600/월 상한 내 흡수** + **U7 별도 텔레메트리 라인**(모델별 토큰·비용 계상). (Q13)
- **bounded 근거**: 온디맨드 + 영구저장 → **"열어본 distinct 논문 × 1회"** 만 과금(재조회·타 사용자 공짜). 요약 Sonnet ≈$0.1~0.2/건, 번역 Haiku ≈$0.01~0.02/건.
- **U6 CostGuard 게이트**(BR-S13): spend ratio **≥0.80**(코드 검증 — `cost_guard.py` `warning_ratio=0.80`·cap $1,600·hard 0.95)부터 `get_budget_state`의 degradeMode가 non-normal(0.80=`RERANK_OFF`, 0.95=`LEXICAL_ONLY`, ≥1.0=hard_cap)이 되고, U7 오케스트레이터는 이를 **요약 일시 기권**(`CostDegradedDTO`, FR-11) + RES-11a 신호로 처분한다. U7은 검색과 달리 **lexical 폴백이 없어**(LLM 필수) 모든 non-normal degrade를 일괄 기권한다. **비용 판정 재구현·재판정 없음**(U6 단일 권위).
- Infra 비용표에 U7 라인 추가(설계 입력 §8).

---

## 7. 보안 (SEC)

| 처분 | 소관 | 내용 |
|---|---|---|
| **인증/인가** | 위임(게이트웨이/U3) | SEC-8 — U7은 ctx 신뢰 |
| **레이트리밋·남용 방어** | 위임(U6 게이트웨이) | SEC-11 — 비용 발생 기능 |
| **내부 필드 비노출** | U7 직접 | SEC-9 — 토큰·비용·캐시키·모델/프롬프트 식별자 외부 DTO 비노출(BR-S14) |
| **프롬프트 인젝션 방어** | U7 직접 | 본문 격리 `[지시]┃[데이터]<paper>…</paper>`(BR-S3) — 태그 안은 데이터 |
| **PII/저작권 로깅** | U7 직접 | SEC-3 — 원문/번역/프롬프트 무분별 로깅 금지 |
| **개인 용어집 격리** | U7 직접 | owner 스코프(사용자별 비공개, SEC-8) — RDS 저장(Q4) |
| **공급망** | 공유(backend 모노레포) | SEC-10 — 락파일·SCA·SBOM·이미지 핀 |

---

## 8. 관측성 (NFR-O1)

- **`ObservabilityHub.emit*`** 로 **토큰·비용·지연·persona·task·근거화 결과(통과/기권)** 제출. (Q15)
- NFR-C1 비용 라인·RES-11 신호·QT-5/US-S6 운영 모니터링 표면. 구조화 로그·메트릭·트레이스. U6 단일 권위 소비.

---

## 9. 유지보수성 · 테스트 (QT-5 / PBT / real-first)

### 9.1 real-first 테스트 전략 (Q14)
- **Production Mock Adapter는 구현하지 않는다.** (출하 코드에 mock/인메모리 대역 없음.)
- **단위 테스트**: 도메인/오케스트레이션 로직을 **테스트 전용 Fixture/Stub**(출하 어댑터 아님)로 검증 — 허용. + Hypothesis PBT.
- **통합 테스트**: **실 의존성**(Bedrock·S3·Redis·U6 후크·U1 전문) 대상. 자격증명/엔드포인트 구성 = CI/Infra.
- **QT-5 근거화 평가셋**(요약/번역 케이스): U7은 출력 표면(앵커·기권 결정) 제공, **평가 실행 소유 = U6/OP**.
- **QT-1 충실도 평가 하니스(요약 도메인, 신규)**: `summarization/eval/`(`run_grounding_eval`·`sweep_numeric_threshold`·시드 케이스) — 라벨(faithful/fabricated) 케이스를 `GroundingValidator`에 돌려 **false_pass(날조 누출)·false_abstain(과민 기권)** 분류·집계, 순수·결정적 CI 회귀. **held-out 라벨 코퍼스 = OP/팀 소유**(시드는 스캐폴드). **수치 임계 재보정(2026-06-29)**: 실제 arXiv 논문 8건의 Results/Table 수치를 발췌한 코퍼스(`eval/real_corpus.py`)로 스윕 — confident 안전 평지=[0.25, 0.51], 0.5는 상단 끝(0.60 프랙션 실 날조 케이스 존재로 그 위는 불가), 14/14 무누출·무과민기권. **결정: `_NUMERIC_MISMATCH_THRESHOLD=0.5` 유지**(0.45는 "절반 미검증=날조" 정책 채택 시에만 우월하나, 구성 draft가 운영 matcher-miss를 과소평가 → 과민기권 위험으로 보류). matcher 정밀화는 완료. 회귀=`tests/test_real_corpus.py`.

### 9.2 PBT 속성 (QT-4 / Hypothesis)
PBT-S1(캐시 키 결정성/멱등) · PBT-S2(정제 멱등·보존 콘텐츠 불변) · PBT-S3(후치환 멱등) · PBT-S4(`SummaryResponse` 라운드트립·비노출) · PBT-S5(앵커 검증 건전성). 차단성/권고 분류는 전역 PBT 정책 계승.

### 9.3 빌드
모노레포 — `backend/modules/summarization/` 독립 pyproject + backend 모놀리스 마운트. 드리프트 가드(shared 계약)·CI 레인은 NFR Design/Infra.

---

## 10. 추적성 매트릭스

| NFR/결정 | 요구사항 | 스토리 |
|---|---|---|
| §2 NFR-P2 캐시/스트리밍 | NFR-P2 | US-S5 |
| §5 Bedrock 격리·기권 | RES-9, NFR-R2, FR-11 | US-S3, US-S5 |
| §6 비용 라인·CostGuard | NFR-C1, RES-11a | US-S6 |
| §7 보안 처분 | SEC-3/8/9/10/11 | US-S4(용어집), US-S6 |
| §8 관측성 | NFR-O1, RES-11 | US-S6 |
| §9 테스트·근거화 | QT-5, QT-4, QT-1 | US-S3, US-S6 |
| 모델 바인딩·생성 | FR-12/13, C-2 | US-S1, US-S2 |

**커버리지**: NFR-P2·NFR-C1·QT-5·RES-9·NFR-R2·NFR-O1·SEC-3/8/9/10/11·FR-11~14·US-S1~S6 (미커버 0).
