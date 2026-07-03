# AIDLC 문서 전수 검토 — 정합성 리메디에이션 (2026-06-30)

## 요약

`aidlc-docs/` 265개 문서를 전수 검토했다(인셉션·공유계약·11개 유닛·상태/프로세스/운영). 산출물 자체는 매우 충실하고 모든 피벗이 날짜 배너로 정직하게 기록돼 있으나, **전역 변경·신규 유닛 편입이 "그때 손댄 문서"에만 반영되고, 그 문서가 의존하는 권위 있는 형제 문서(SSOT·IAM·운영 런북)에는 반영되지 않아** 국소적으로는 맞지만 전역적으로 서로 모순되는 상태다. 코드 버그가 아니라 문서 정합성 문제지만, 일부는 잘못된 조치(부정확한 장애 대응·IAM 거부·추적 불가 요구사항)를 유발한다.

검토 방식: 5개 병렬 리더가 섹션별로 검토 → 상위 구조 결함 2건(U4 충돌·FR-18 중복)은 `requirements.md` 대조로 직접 재확인.

---

## 핵심 문제 — 5개 체계적 패턴 (영향 범위 순)

### 1. 전역 정정 반영 누락 (가장 광범위) — **HIGH**

두 전역 변경이 일부 문서에만 적용되고 부하가 큰 형제 문서에 누락됨.

- **Cohere v3 → v4** (완료 2026-06-24)인데 아직 v3:
  - `construction/infrastructure-design/infrastructure-design.md:24,179` — 모델 ARN + 초록 단일벡터 인덱스 사이징
  - `construction/u1-ingestion/nfr-requirements/nfr-requirements.md:100` — **VectorSpec PIN**(전 시스템 임베딩 공간을 고정하는 writer 핀)
  - `construction/u1-ingestion/nfr-design/nfr-design-patterns.md:186` — **IAM grant의 v3 모델 ARN**(v3 ARN은 실제 라이브가 호출하는 v4 `InvokeModel`을 거부함)
  - `construction/u2-discovery/nfr-requirements/tech-stack-decisions.md:22`, `u2-discovery/code/README.md:68`
- **SES → Resend**(라이브 채널=Resend)인데 U3 설계/인프라 3개 문서가 아직 SES:
  - `construction/u3-accounts/infrastructure-design/infrastructure-design.md:31-35` — *진행 중*으로 표기된 "SES 샌드박스 해제 요청" 워크플로우
  - `construction/u3-accounts/infrastructure-design/deployment-architecture.md:30,40`, `nfr-design/nfr-design-patterns.md:47` — SES 3.0s 타임아웃·소프트폴백

> 산문이 아니라 IAM ARN·임베딩 공간 핀·이메일 런북이라 영향이 큼.

### 2. 연구 에이전트 2유닛 분리 미정합 + 유닛 번호 충돌 — **HIGH**

단일 "U11 Research Agent"가 2유닛(문헌탐색·근거형성 / novelty)으로 분리(2026-06-28)됐으나 레이어 간 정의가 불일치.

- **SSOT 자체에서 `U4`가 두 유닛을 동시 지칭.** `requirements.md:22,79-81`이 문헌탐색·근거형성 에이전트(FR-36/37/38)를 **[U4]**로 태깅 — 그러나 U4는 **이미 라이브인 Library 유닛**. 설계 레이어(`application-design.md`·`services.md`·`unit-of-work.md`)는 동일 에이전트를 **U11**로 번호 매김. (직접 확인)
- **novelty 에이전트가 풀 스토리·풀 요구사항인데 소유 유닛이 없음.** FR-30..35는 `[신규]` 태그뿐(번호 없음), `unit-of-work*.md`·`application-design.md`에 행이 없음. FR 6개·스토리 9개(US-NV1..9)·QT-10·NFR-P5/R3를 가진 기능이 설계 레이어에서 단절돼 사이징/구현 불가.
- `vision.md:78`·`technical-environment.md:116`이 아직 **"U11"을 단일 유닛으로 표기**(분리 전 분류) → 설계리뷰 도구에 폐기된 taxonomy를 공급. 잔여 `U11` 댕글링: `u3-accounts/nfr-design/nfr-design-patterns.md:81`, `designreview-audit.md`(N5).
- `requirements.md:26,279`이 novelty FR의 근거-of-record로 **`requirement-verification-questions-answer-1.md`를 인용 — 해당 파일이 존재하지 않음**(근거 추적 끊김).

### 3. 요구사항 ID 정합성 붕괴 — **HIGH**

- **FR-18이 서로 다른 두 기능을 의미.** `requirements.md:12`(U9)="행동 이벤트 기록", `requirements.md:72`(doc-model)="자체 리치뷰". 두 개정 모두 2026-06-23이고 FR 표는 리치뷰가 선점 → **U9의 "행동 이벤트 기록" 요구사항이 유효 FR 행을 잃음**. 그런데 성공기준 #6(`:194`)은 여전히 "FR-18..20"으로 이를 인용. (직접 확인)
- **v4 마이그레이션 플랜이 잘못된 ID 인용:** `plans/v4-migration-code-generation-plan.md:8`이 "FR-17 (Dual-write)" 구현이라 적었으나 FR-17은 멀티모달 그림·표 요구사항, dual-write는 FR-21.
- **FR-17·FR-21이 `stories.md`에서 고아** 상태인데 커버리지 푸터는 전수 커버를 주장.

### 4. DocModel/앵커 계약이 완전히 안착하지 못함 — **HIGH/MED**

- FROZEN `shared/docmodel.md §3`은 **결정적 Section/Block id** 앵커 타깃을 의무화하나, 런타임 SSOT `shared/dtos/summarization.schema.json`과 U7(`u7-summarization/functional-design/domain-entities.md:130`)은 아직 **레거시 `enum{section,table,figure}` + quote-span + regex-label** 모델을 사용하며 U7은 이를 "불변(백엔드 무변경)"이라 표기. 에이전트 `evidence-formation-port.md §3.6`은 id 기반 앵커를 가정 → **novelty 에이전트의 근거 실재성 검증이 U7 발행 앵커와 정합 불가.**
- `events.md:45`은 getDocModel 폴링 상태를 `PendingDTO`, `docmodel.md §5`+런타임 스키마는 `building` — 공유계약 둘이 동일 상태를 다른 DTO로 기술.
- `SearchExecutedEvent.requestId`(U4 디덥 키로 존재하는 FROZEN 필드)가 U2 엔티티 카드 `u2-discovery/functional-design/domain-entities.md:110`에서 누락. U4는 한 문서에선 `requestId`, 세 문서에선 `timestamp`로 디덥 → 내부 불일치.

> 정정: `dtos.md`는 🔒가 아니라 🟡 PROVISIONAL. 완전 FROZEN은 `vector-spec.md`·`docmodel.md` 뿐, `events.md`/`ports.md`는 부분 동결. 동결 표기 자체도 `00-shared-contracts-overview.md:22`와 파일 헤더 간 불일치.

### 5. 운영 레이어 staleness — **HIGH (운영 위험 최상)**

장애 시 읽는 문서라 운영상 위험이 가장 큼.

- `operations/runbook.md:14` — OpenSearch **2.11**, 인덱스 **`docsuri-papers`** 표기(라이브=**2.19**, alias **`docsuri-corpus`**). 스택 인벤토리(6개)에 이후 추가된 summarization·novelty 스택 누락.
- `operations/operations-placeholder.md`(더 나중인 06-26)가 "런북 없음 / Operations=future scope"라 단언 → 06-18부터 존재하는 runbook과 정면 모순. 이미 라이브인 코퍼스 컷오버를 "not yet production-ready"로 표기.
- `v4-migration/build-and-test-summary.md:38`와 code-gen 플랜이 **삭제된 `backfill_v4` 스크립트**(미서명 403 발생으로 제거됨)를 가리킴. 실제 러너는 `migrate.py`. 런북대로 하면 깨진 스크립트를 실행.

---

## 수정 체크리스트

**먼저 (잘못된 조치 위험):**
- [ ] **U4 충돌 해소** + novelty 에이전트에 실제 유닛 번호·설계/스토리맵 행 부여; 문헌탐색 에이전트 번호를 requirements↔design 간 back-sync(U4는 점유됨 → 새 번호 필요)
- [ ] **FR-18 정리**(행동 이벤트 기록 ID 복원) + v4 마이그레이션 **FR-17→FR-21** 인용 정정 + 누락된 `requirement-verification-questions-answer-1.md` 참조 해소
- [ ] **운영 레이어 정정**: runbook OpenSearch 버전/인덱스·스택 목록; `operations-placeholder.md` 삭제 또는 전환; v4 백필 런북을 `migrate.py`로 재지정
- [ ] **v3→v4·SES→Resend 스윕**: 시스템 인프라 `infrastructure-design.md`, U1 VectorSpec PIN, U1 IAM ARN, U3 인프라/NFR (배포 아티팩트)

**다음 (추적성/계약):**
- [ ] **DocModel 앵커 모델**(id 기반 vs enum/regex)을 `docmodel.md`·`summarization.schema.json`·U7·evidence 포트 간 일치 — 무엇이 진실인지 확정 후 나머지 정합
- [ ] `SearchExecutedEvent.requestId`를 U2 카드에 복원 + U4 디덥 키를 `requestId`로 통일
- [ ] 시스템 `infrastructure-design.md` **인덱스 사이징** 정정(논문당 1벡터/초록-only로 계산 — 라이브는 ~1.5M 전문 청크 → 비용/용량 헤드룸 주장이 실질적으로 과소)
- [ ] `vision.md`/`technical-environment.md` 유닛 표 + `aidlc-state.md:7` **stale "현재 단계" 라인** 갱신(U1 Corpus에서 워크플로우 종료라 주장하나 이후 novelty 에이전트가 풀 사이클 수행)

**위생 (낮음, 저비용):**
- [ ] 폐기된 **피벗 플랜** 스탬프(`docmodel-foundation-pivot`·`docmodel-fulltext-index-pivot`이 배포 완료인데 아직 🟡 DRAFT-승인대기) + §0 배너 뒤에서 구behavior(arXiv-only/lazy-DocModel/auto-LOCKED)를 서술하는 유닛 FD 본문 back-sync
- [ ] 커버리지 갭: **U10 마이페이지 인셉션 커버리지 전무**(배포됐는데 FR/스토리 없음); U8 `code/` 요약 없음; U2 `infrastructure-design/` 없음; build-and-test 문서가 U1에만 존재
- [ ] 루트의 일회성 질문 문서(`next-steps-questions.md`·`track2-*`)와 2026-06-15 "21 스토리/6 유닛" 플랜 문서 아카이브 — staleness 배너 없이 폐기된 로드맵을 광고 중

---

## 메타 노트

이 프로젝트는 stale 텍스트를 고치는 대신 **날짜 우선순위 배너**("이 절이 충돌하면 최신 절이 우선")에 의존한다. 정직한 패턴이지만 이제 충분히 깊게 쌓여, 정확성이 모든 독자가 모든 배너를 추적하는 데 달려 있다 — 그리고 권위 있는 spec/IAM/ops 문서가 바로 배너를 못 받은 문서들이다. 위 ~12개 부하가 큰 문서를 1패스 back-sync하면 대부분의 부채가 해소된다.

---

*검토 도구: Claude Code (Opus 4.8). 265개 문서 / 5개 병렬 섹션 리더 / 상위 2건 직접 재확인.*
