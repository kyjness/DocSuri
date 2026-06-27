# U11 Research Agent — NFR Requirements (비기능 요구사항)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**근거**: 계획서 `u11-research-agent-nfr-requirements-plan.md`(**Q1~Q16 전부 A**) · FD 산출물(`u11-research-agent/functional-design/`) · `requirements.md`(NFR-P5·NFR-C1 Agent·QT-8·RES-9/11·SEC-5/8/9/11·NFR-O1) · 전역 계승(U1/U2/U3/U7 tech-stack) · 아키텍처 게이트 `docmodel-fulltext-index-pivot-plan.md`.
**고도**: NFR 목표(정책 형태) + 스택 종류. 구체 수치(TTFB·K 상한·토큰 캡·타임아웃·서킷 임계)·리전/IaC/CI는 NFR Design/Infra/Build&Test(NS-1). 실험 결정(인덱스 granularity GQ1·랭킹 GQ2·모드 B API)은 미확정.

---

## 1. 컨텍스트 · NFR 동인

U11 = **로그인 필수 온디맨드 대화형 다논문 근거형성 API 모듈**(배포 ① backend 모놀리스 + 긴 분석 비동기 잡 ③). 검색 SLA(NFR-P1) **비대상**. 핵심 동인:
- **NFR-P5**(온디맨드·비차단·진행상태·부분결과) — 다논문 fan-out으로 U7 단건보다 지연 큼.
- **NFR-C1 Agent**(다논문 LLM 호출 신규 라인) — 기존 $1,600 상한 내 흡수·캐시·CostGuard.
- **RES-9/11**(다수 외부 의존[U2 검색·doc-model·Bedrock] 격리·부분결과·AI 인시던트 탐지).
- **QT-8**(근거 정확도·날조 0·기권) — U6 통일 근거화 소비.
- **SEC-5/8/9/11**(owner-scope·첨부 무해화·injection·레이트리밋).

---

## 2. 성능 (NFR-P5 — 온디맨드, NFR-P1 비대상)

| 항목 | 요구(형태) | 근거 |
|---|---|---|
| 캐시 HIT | **즉시 응답**(LLM 0콜·스토어 조회). 동일 단일-턴 분석 재사용. | Q6·BR-RA-12·US-RA5 |
| 첫 분석(MISS) | **스트리밍 first-token(빠른 TTFB)** + 진행상태 노출. 다논문 fan-out으로 수 초~수 분 — **완료 시간 SLA 아님**(NFR-P5). | Q2/Q3·US-RA6 |
| 긴 분석 | 후보 수·토큰 임계 초과 시 **비동기 잡 + 폴링**(게이트웨이 타임아웃 회피, U7 잡 패턴). | Q2·TD-RA-8 |
| 부분결과 | 일부 논문 추출 완료분부터 점진 노출 — 전체 대기 없음(PartialResultDTO). | NFR-P5·US-RA6 |
| 콜드스타트 | long-running 컨테이너 가정(콜드스타트 제외). | — |
| 검증 수치 | TTFB·완료 분포·K 상한·동기↔비동기 임계 **실측·확정 = NFR Design/Build&Test**. | NS-1 |

- **버퍼-검증-스트리밍**(U7 BR-S8 계승): U6 근거화 통과분부터 노출 — TTFB와 날조 0(FR-5)의 균형.

---

## 3. 확장성

- **stateless 모듈 + 수평 확장**(backend 인스턴스 복제). 대화 상태는 스토어(RDS), 인스턴스 무상태.
- **async I/O**: U2 검색·doc-model 읽기·Bedrock·Redis·RDS 외부 대기 중첩. 다논문 fan-out은 **bounded 병렬**(K 상한·동시성 한도 — NFR Design).
- **Bedrock 동시 호출 = 계정 쿼터 내**; fan-out이 쿼터 압박 가능 → 큐잉/저하(RES-8). 오토스케일·쿼터 수치 = Infra.

---

## 4. 가용성 · 신뢰성 (RES-9/11 / NFR-R1·R2)

- **온디맨드 비-SLA**(NFR-P5) — 핵심 검색(NFR-P1/A1)과 분리. U11 장애는 **우아한 기권/부분결과**(FR-11)로 흡수, **타 기능 차단 금지**(INV-U11-5·비차단).
- **다중 의존성 격리(RES-9)** — 정책 형태(수치는 NFR Design):
  - **U2 검색 장애** → 후보 0 처리·명시적 `AbstainDTO`(빈 성공 금지).
  - **doc-model 빌드/읽기 장애(일부 논문)** → 해당 논문 제외 + `PartialResultDTO`(degraded 표시), 전체 실패 아님.
  - **Bedrock 장애/타임아웃** → 타임아웃 + 재시도(1회·백오프) + 서킷 → 기권/부분결과(FR-11).
  - **U6 근거화/CostGuard 장애** → fail-closed(근거화 못 하면 기권 — 조용한 오답 금지, NFR-R1).
- **재시도 폭주 방지**: ① 근거화 1차 실패 재시도(U6 계약) ② LLM 호출 장애 재시도(1회) — 분리·상한.
- **부분/조용한 결과 금지(NFR-R1)**: 종단 상태 명시(AgentResponse 5종 union). 근거 없는 항목은 성공인 양 섞지 않고 항목 기권(BR-RA-7).

---

## 5. 비용 (NFR-C1 Agent)

- **기존 $1,600/월 상한 내 흡수** + **Agent 별도 텔레메트리 라인**(모드별 LLM 토큰·비용 계상).
- **bounded 비용 동인**: 다논문 fan-out = `후보 K × 논문당 추출 LLM 호출` + 교차확인 호출. **K 상한**(RES-9)·**캐시 중복 차단**(단일-턴 분석 immutable 키)으로 bound. 동일 질의 재호출·타 사용자 = 캐시 히트(0콜).
- **U6 CostGuard 게이트**(BR-RA-10): `getBudgetState` OPEN/LEXICAL_ONLY → Agent 일시 기권(`CostDegradedDTO`·FR-11) + RES-11a 신호. **비용 판정 재구현 없음**(U6 단일 권위).
- **모드 B(외부 학술 API) 비용**은 차기(미빌드) — 본 사이클 비용표 미포함.
- Infra 비용표에 Agent 라인 + 전문 인덱스 사이징 비용(아키텍처 게이트 — 월 +$100~220 추정·실측은 배포 후).

---

## 6. 보안 (SEC)

| 처분 | 소관 | 내용 |
|---|---|---|
| **인증/인가** | 위임(U6 게이트웨이/U3) | SEC-8 — 로그인 필수·owner-scope; U11은 ctx 신뢰(BR-RA-1) |
| **레이트리밋·남용 방어** | 위임(U6 게이트웨이) | SEC-11 — 비용 발생 기능; 동일 질의 캐시 차단 보조 |
| **첨부 무해화·검증** | U11 직접 | SEC-5 — 형식/크기 검증·제어문자 제거·실행파일 거부 → `InputRejectedDTO`(BR-RA-2) |
| **프롬프트 인젝션 방어** | U11 직접 | 본문 격리 `[지시]┃[데이터]<paper>…</paper>`(U7 BR-S3 계승) — 첨부·논문 텍스트는 데이터 |
| **첨부 역할 한정** | U11 직접 | 첨부는 질의·비교 기준만, 근거 출처 인용 금지(BR-RA-11) |
| **내부 필드 비노출** | U11 직접 | SEC-9 — 캐시키·모델/프롬프트 식별자·raw 점수·자산 픽셀 외부 DTO 비노출 |
| **자산 서빙** | 위임/직접 | SEC-9/12 — 그림 자산 단기 서명 URL(doc-model엔 assetId 참조만) |
| **PII/저작권 로깅** | U11 직접 | SEC-3 — 질의/첨부/논문 본문 무분별 로깅 금지 |
| **owner 격리** | U11 직접 | 세션·결과·첨부 owner-scope(SEC-8)·삭제/초기화 분리(BR-RA-1/15) |
| **공급망** | 공유(backend 모노레포) | SEC-10 — 락파일·SCA·SBOM·이미지 핀 |

---

## 7. 관측성 (NFR-O1 / RES-11)

- **`U6.ObservabilityHub.emit*`** 로 제출(단일 수집): **모드별 호출 수·처리시간·후보 K·기권/저하 비율·외부 의존(U2/doc-model/Bedrock) 오류율·LLM 토큰·비용 라인**. (US-RA7)
- **AI 인시던트 탐지(RES-11)**: (a) 비용 폭발(→ CostGuard·NFR-C1) · (b) 할루시네이션(→ U6 근거화·날조 0·QT-8) · (c) 반쪽 결과(→ PartialResult 비율·NFR-R1). 각 탐지 신호·경보·COE.
- 구조화 로그(requestId 상관·PII 차단 SEC-3)·메트릭·트레이스. 전송/대시보드 = U6/Infra.

---

## 8. 유지보수성 · 테스트 (QT-8 / PBT / real-first — Q13·Q15=A)

### 8.1 real-first 테스트 전략 (Q15=A, U7 TD-S12 계승)
- **Production Mock Adapter는 구현하지 않는다.** 출하 코드 = 포트 + 실 어댑터 단일본(U2 검색·doc-model·Bedrock·RDS·Redis·S3·U6 후크).
- **단위 테스트**: 도메인/오케스트레이션을 **테스트 전용 Fixture/Stub**으로 검증(출하 어댑터 아님) + Hypothesis PBT.
- **통합 테스트**: 실 의존성 대상(자격증명/엔드포인트 = CI/Infra).
- **프런트(`u11-research-agent-frontend`) 병렬**: 핵심 경로 real-first 유지하되, 프런트는 **계약(shared DTO)용 mock 픽스처**로 병렬 — 계약 불변 스왑(MR-4식). (Q15=A 혼합 여지는 프런트 한정)
- **QT-8 평가셋**(근거 정확도·날조 0·기권·출처 유효성): U11은 출력 표면 제공, **평가 실행 소유 = U6/OP**(QT-1 동일 체계).

### 8.2 PBT 속성 (Hypothesis — QT-8 6종, FD §3)
PBT-RA1(`AgentResponse` 5종 union 라운드트립·비노출) · PBT-RA2(기권 안정성 — 근거 없으면 항상 기권·날조 0) · PBT-RA3(owner isolation) · PBT-RA4(캐시 키 immutability/dedupe·버전 무효화) · PBT-RA5(부분결과 불변 — 완전≠부분) · PBT-RA6(출처 locator 실재). 차단성/권고 분류 = 전역 PBT 정책 계승.

### 8.3 빌드
모노레포 `backend/modules/research_agent/` 독립 pyproject + backend 모놀리스 마운트. 긴 분석 비동기 워커 = 별도 배포(Infra). 프런트 = 별도 트랙. 드리프트 가드(shared 계약)·CI 레인 = NFR Design/Infra. **조율 존**(`backend/wiring.py`·게이트웨이) 변경은 app-shell 사인오프.

---

## 9. 실험·평가로 이연 (확정 안 함 — Q8/Q9/Q14=A "열어둠")

- **인덱스 granularity (GQ1)**: document/section/block dense(+lexical) — recall·비용 평가로 결정. block_id locator는 granularity 종속 옵션.
- **랭킹 전략 (GQ2)**: title/abstract/body boost·U2/U11 랭킹 프로파일 공유/분리·질의유형(topic/passage)별 — 실험.
- **K 상한·동기↔비동기 임계·타임아웃·서킷 수치** — NFR Design/튜닝.
- **모드 B 외부 학술 API** — 차기 사이클(미빌드).
- 전문 통합 인덱스·eager doc-model 사이징/비용 — **아키텍처 게이트** + U1/U2/infra 조율.

---

## 10. 추적성 매트릭스

| NFR/결정 | 요구사항 | 스토리 |
|---|---|---|
| §2 성능·캐시·스트리밍·비동기 | NFR-P5 | US-RA3, US-RA6 |
| §4 다중 의존성 격리·부분결과·기권 | RES-9, NFR-R1/R2, FR-11 | US-RA4, US-RA6 |
| §5 비용 라인·CostGuard·캐시 | NFR-C1 Agent, RES-11a | US-RA7 |
| §6 보안 처분 | SEC-3/5/8/9/11 | US-RA1, US-RA2, US-RA7 |
| §7 관측성·AI 인시던트 | NFR-O1, RES-11(a/b/c) | US-RA7 |
| §8 테스트·근거화·real-first·shared DTO | QT-8, Q15/Q16 | US-RA4, US-RA7 |
| 근거화 U6 통일·추출 경계 | FR-5, QT-8, C-2 | US-RA3, US-RA4 |
| 영속·삭제·전용 진입 | FR-25, SEC-8 | US-RA5 |

**커버리지**: NFR-P5·NFR-C1 Agent·QT-8·RES-9/11·NFR-R1/R2·NFR-O1·SEC-3/5/8/9/10/11·FR-5/11·FR-22~25·US-RA1~7 (미커버 0). 모드 B(US-RA8)=차기.
