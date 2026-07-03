# docmodel-fulltext-index-pivot-plan.md — 전문 통합 인덱스 + eager doc-model 전환 게이트

**단계**: CONSTRUCTION → 교차 아키텍처 결정 게이트 · **일자**: 2026-06-24 · **상태**: ✅ **확정·배포 완료**(전문 통합 인덱스 + eager doc-model 전환 라이브 — OpenSearch alias `docsuri-corpus`, ~1.5M 전문 청크; 구 🟡 DRAFT 표기 정정 2026-06-30, `aidlc-suite-review` PR #280)
**계기**: U11 Research Agent(연구 에이전트) Functional Design — 다논문 근거형성이 **본문(표·수식·그림 캡션 포함) 단위 찾기·근거**를 요구.
**선례(형식)**: `docmodel-foundation-pivot-plan.md`(doc-model 도입 게이트). 본 문서는 그 후속 결정.
**SSOT 영향 원장**: `aidlc-state.md`.

> **참고(PR #232, 2026-06-28)**: 본 plan이 인용하는 `FR-22`·`QT-8` 등 구 u11 연구 에이전트 ID는 PR #232에서 **폐기**되었다(에이전트가 2유닛으로 재구성됨). 본 문서는 당시 결정의 **역사 기록**으로 보존하며, 인용 ID는 그 시점 기준이다.

> 이 결정은 **본인(kyjness)이 이슈 #120 개설 + PR #136 리뷰·승인으로 확정했던 "검색 인덱스=제목+초록만"(Q2=C→B)** 과, doc-model 피벗의 **D6(doc-model lazy 생성)** 을 **의식적으로 되돌린다**. 되돌림이므로 별도 게이트로 명시·승인한 뒤 FD/코드로 내려간다(설계 스탠스: 기존은 기본값, 목표가 요구하면 blast-radius 명시 후 변경).

---

## 1. 결정 (확정안 — 승인 시 D로 고정)

- **DF-1 전문 통합 인덱스**: OpenSearch 검색 인덱스를 **"제목+초록만" → "전문 전체(제목+초록+본문)"** 로 전환한다(초록을 본문으로 *교체*가 아니라 **포함 + 본문 추가** — 초록 기반 topic 검색 recall 손실 없음). **U2 검색·U11 에이전트가 단일 인덱스 공유**(에이전트 전용 별도 인덱스 안 만듦 — 서브시스템 분기 회피).
- **DF-2 eager doc-model**: doc-model을 **전 논문 인제스트 시 eager 생성**한다(D6 lazy 되돌림). **doc-model은 이미 제목·초록(meta) + 본문(sections, 표=데이터·수식=latex·그림 캡션)을 담는다**(코드 검증: `builder.py`·`parser.py` — 빌더에 제목/초록 추가 불필요). 색인은 **Index Projection**: `DocModel → 검색 가능 콘텐츠(제목·초록·문단·표·수식·그림 캡션)를 검색용 레코드로 투영 → OpenSearch`(JSON 문자열화가 아니라 필드 투영). 표/수식/캡션이 **찾기·근거에 first-class**.
- **DF-3 근거화 U6 통일 (확정)**: 근거 추출·앵커는 **구조화된 locator 사용**(최종 granularity는 GQ1에서 확정 — block/section/document 중 미정). **근거화는 U6 단일 권위로 통일** — U6 공유 계약이 검색 enforce + 문서충실도(단일 논문 / 다논문)를 포괄하도록 업그레이드하고, **U7이 따로 둔 근거화(`AnchorVerdict`)도 이 계약으로 이관·수정한다**(선택 아님; blast-radius=`shared/ports.md`·U6 FD·**배포된 U7 FD/코드+회귀**). 상세는 U11 FD Q7. *(인덱스 전환과는 독립 트랙이나 같은 U11 사이클에서 함께 진행.)*
- **DF-4 `982f64a` 승격**: 미승인 복원 커밋 `982f64a`(전문 본문 임베딩 복원)를 폐기/revert가 아니라 **본 게이트로 정식 승격**해 *제대로* 수행한다(소스=doc-model·infra resize·비용 갱신·테스트/문서 정합).
- **DF-5 검색 hit 반환 (최소 보장 + 권장 옵션)**: 검색 hit는 **최소 `paper_id`(+score)** 를 반환한다. **`block_id` locator(`section·block_id·score`)는 권장 최적화 옵션**(있으면 추출이 해당 블록부터 시작 → 토큰↓·속도↑·비용↓·앵커 사전확보; locator=**시드**, 추출은 섹션까지 확장). **확정 아님** — locator 가능 여부는 색인 granularity(아래 GQ1)에 종속하므로 지금 block_id를 못박지 않는다(향후 block/section/document dense 선택지 보존).
- **DF-6 doc-model 완전성 (논문 전체 담기)**: doc-model이 "논문 내용 전체"를 담도록 **가산적(forward-compat)** 보강한다 —
  - **(a) 각주(footnote) 포함**: 현재 parser가 drop(인라인 오염 방지). → **out-of-flow 별도 블록/앵커로 추출**(인라인 미주입). 이유: 각주에 **코드/데이터 공개 사실·단서·추가 결과** 등 실제 근거가 숨음(FR-22 "코드/데이터 공개 사실 추출"과 정합); 버리면 사각지대. *(블록 타입/notes 필드 가산 — U1/shared 사인오프.)*
  - **(b) 서지 메타 보강**: doc-model `meta`에 **저자·발행일·arXiv 카테고리** 추가(현재 title/abstract만). doc-model이 **출처 표기까지 자급**(코퍼스 별도 조회 불요). *(가산.)*
  - **(c) 구조화 인용(출처논문)은 범위 밖**: 참고문헌 *섹션 텍스트*는 본문 블록으로 포함되나, **인용 링크/그래프는 U8 citation_graph(FR-15/16) 영역 → v1 U11 미포함**(차기 U8 연동).

---

## 2. 근거 (왜 되돌리나)

- 이슈 #120이 명시한 **"passage-level 검색이 간판 기능이면 전문 임베딩 정당화"** 조건이 **연구 에이전트로 발동**. #136 결정 당시엔 에이전트가 의제에 없었다.
- 에이전트의 핵심 가치(다논문 방법·결과·한계 교차확인)는 **본문에 묻힌 단서**(특정 데이터셋·기법·수식·표 수치)로 논문을 찾고 근거화하는 것 → 초록만으론 recall 부족(사용자 확인).
- 표/수식/그림 캡션을 근거로 쓰려면 평문이 아닌 **구조화(doc-model)** 가 필요(표=데이터·수식=latex). doc-model을 색인 소스로 쓰면 **전문 표현이 하나로 통일**(검색·근거·요약·리치뷰 공유) — 별도 본문 청킹 파이프라인 불요.

---

## 3. Blast-radius (영향 받는 기존 산출물·코드)

| 영역 | 변경 | 소유/조율 |
|---|---|---|
| **U1 인제스천** | doc-model eager 생성(인제스트 hot path에 결정적 파싱 추가)·전문 색인 투영 복원. `Chunker`/`IndexRecord`/`processors.py`·BR-2/5/6/7/21·`u1-ingestion-functional-design-plan.md` Q2 배너 갱신 | U1 트랙 |
| **U2 검색** | 전문 인덱스 위 검색 → recall·랭킹 의미 변화. U2 FD·테스트·QT-2 평가셋 영향 | U2 트랙(@kyjness) |
| **인프라/비용** | OpenSearch 노드 등급↑(전문 벡터 RAM). `infrastructure-design §1/§5` 사이징·**NFR-C1 비용 라인** 갱신 | infra |
| **doc-model 계약/스키마** | D6(lazy)→eager 전제. **DF-6 가산 스키마**: 각주 블록(또는 notes 필드)·meta에 저자/발행일/카테고리. `construction/shared/docmodel.md`·`docmodel.schema.json`·`docmodel-foundation-pivot-plan.md` 정합 | shared |
| **doc-model 파서/빌더** | DF-6(a) 각주 out-of-flow 추출(현 drop 반전)·DF-6(b) meta 저자/발행일/카테고리 채움. `ingestion/.../docmodel/parser.py`·`builder.py` | U1 트랙 |
| **U7 요약** | ① doc-model eager화로 `getDocModel` `building` 상태가 인덱스 논문엔 사실상 해소(경미). ② **★근거화 이관★ — U7 자체 `AnchorVerdict`를 U6 공유 근거화 계약으로 이관·수정**(배포된 코드 변경 + 회귀; DF-3·U11 FD Q7) | U7 트랙 |
| **v4 마이그레이션(진행 중)** | 전문 임베딩이 마이그레이션 재임베딩 비용·범위↑ | 조율 |
| **U11** | 본 결정 위에 FD/코드 진행(소비자) | U11 |

---

## 4. 비용 (이슈 #120 가정 기반 **추정** — 실측은 배포 후 관측)

> 가정(#120): OA 적격 N≈70k(50~150k)·초록 ~300tok·전문 ~9,000tok·~18청크/논문·Cohere $0.0001/1K·k-NN ~4.5KB/벡터.

| 항목 | 초록만(현행) | 전문(본 전환) |
|---|---|---|
| 임베딩 1회 | ~$2 | **~$63** (재인덱싱·v4 마이그레이션마다 반복) |
| k-NN RAM | ~0.3–0.47 GB | **~5.7 GB**(블록 단위) → 섹션 단위면 ↓ |
| OpenSearch 월 증분 | — | **+$100~220/월** (16GB급, 노드 수·Multi-AZ면 ×2~3) — **추정, 실측은 배포 후** |
| doc-model eager 생성 | — | 결정적 CPU 파싱(LLM 아님) ~수$ 1회 + S3 저장 ~$0.2/월 |

- **비용 성격**: 월간 동인은 **OpenSearch 노드 등급**. NFR-C1($1,600/월 상한)의 ~6~14% 추가. DF-5(섹션 단위·BM25 혼합)로 완화 가능.
- 정확한 월 증분은 **현 배포 OpenSearch 토폴로지**에 의존 — 본 게이트는 추정치로 기록, NFR/Infra에서 확정.

---

## 5. SSOT back-sync 목록 (승인 후 수행)

- [ ] `aidlc-state.md` — 본 전환 항목 등재(#136/D6 되돌림 근거·blast-radius).
- [ ] U1: `business-logic-model`/`business-rules`(BR-2/5/6/7/21·Q2 배너) — 전문 색인·eager doc-model 정합.
- [ ] `infrastructure-design §1/§5` + **NFR-C1** — 노드 사이징·비용 라인.
- [ ] `shared/docmodel.md`·`docmodel.schema.json`·`docmodel-foundation-pivot-plan.md` — D6 lazy→eager + **DF-6 가산 스키마(각주 블록·meta 저자/발행일/카테고리)** 정합.
- [ ] `ingestion/.../docmodel/parser.py`·`builder.py` — DF-6 각주 추출·meta 보강(코드↔스키마 정합·테스트).
- [ ] U2 FD/테스트/QT-2 — 전문 검색 의미.
- [ ] **근거화 U6 통일(DF-3)** — `shared/ports.md`(근거화 계약: 검색+문서충실도) · U6 FD · **U7 `AnchorVerdict` 이관·수정 + 회귀**(배포 코드).
- [ ] `982f64a` — 본 게이트 참조로 정식화(코드↔문서 정합 검증).
- [ ] v4 마이그레이션 계획 — 전문 재임베딩 반영.

---

## 6. 열린 질문 (코드 전 확정)

- **GQ1 (열림 — 실험으로 결정)**: 색인 granularity = **document dense / section dense / block dense** (및 lexical[BM25] 혼합 여부). 어느 것도 미확정 — section dense만으로 충분할 수도, block dense가 필요할 수도 있어 **평가(QT-8/recall·비용) 결과로 결정**. block_id locator(DF-5) 가능 여부가 여기에 종속. 비용 방향만 참고: block dense=k-NN RAM 최다(#120 지렛대), block BM25=싸게 locator. **지금 특정 안으로 기울이지 않음.**
- **GQ2 (열림 — 랭킹 전략)**: 단일 공유 인덱스는 **이미 결정(DF-1)**. 남은 문제는 **검색 랭킹 전략** — title/abstract/body(섹션) **필드별 boost 가중치**, U2 일반 검색 vs U11 에이전트의 **랭킹 프로파일 공유/분리**, 질의 유형(topic/passage)별 가중. → NFR/실험.
- **GQ3**: eager doc-model 백필 전략(기존 코퍼스 ~70k 일괄 생성 vs 점진) — 인제스트 처리량·비용.
- **GQ4**: 비-HTML(~9%) 폴백 논문의 표/수식 색인 한계(PDF 폴백 시 구조 약함) 처리.

---

## 7. 다음 절차
1. 본 게이트 **사용자 승인**(DF-1~5·비용·blast-radius).
2. 승인 후 §5 back-sync + U11 FD Part 2 진행.
3. GQ1~4는 NFR/Infra 라운드에서 확정.
4. 커밋·푸시·PR은 사용자 승인 후.
