# 재인셉션 차터 (Re-Inception Charter) — 2026-06

**단계**: INCEPTION 재진입 · **작성일**: 2026-06-26 · **상태**: 초안(차터 확정 대기)
**성격**: 본 문서는 이번 대규모 개편의 **단일 기준점(SSOT 앵커)**이다. 이후 모든 인셉션 산출물
(requirements → user-stories → application-design → unit-of-work)은 본 차터에서 갈라져 나온다.

> **베이스라인 원칙 — 기준은 "코드"다.**
> 현행 `aidlc-docs/` 문서와 실제 코드가 다수 어긋나 있다. 본 재인셉션은 **stale 문서가 아니라
> 실제 코드(`ingestion/`·`backend/`·`shared/`·`ops/`·`frontend/`)를 리버스 엔지니어링한 결과**를
> 사실의 기준으로 삼는다(.aidlc-rule-details/inception/reverse-engineering.md, brownfield).
> 문서와 코드가 충돌하면 코드를 채택하고, 차이를 본 차터의 §2 드리프트 표에 기록한다.

---

## 0. 왜 재인셉션인가

에이전트(문헌탐색·근거형성, 연구 아이디어)를 추가하는 과정에서 기존 구조의 구조적 문제가 다수
드러났다. 부분 수정이 아니라 **유닛 경계·근거화(grounding) 통합·Corpus 파이프라인**을 다시 그리는
범위이므로, AI-DLC를 처음부터 다시 열어 인셉션 산출물을 재생성한다.

---

## 1. 확정 결정 (Decisions)

| # | 결정 | 내용 | 근거 |
|---|---|---|---|
| D1 | **문서 형태** | **신규 인셉션 사이클**. requirements → user-stories → application-design → unit-of-work 재생성. 유닛 경계 자체를 다시 그린다. | 개편 범위가 유닛 경계를 넘어섬 |
| D2 | **에이전트 유닛 구성** | **2개 유닛으로 분리**(아래 §4): 문헌탐색·근거형성 유닛 / 연구아이디어 유닛. 후자가 전자를 **포트로 의존(Tool 소비)** 한다 — **2026-06-28 확정(A)**. (근거 출력 DTO 등 계약 *디테일*은 문헌탐색·근거형성 유닛 질문지에서 확정.) *(2유닛 분리는 2026-06-26 승인)* | 담당 분리·상이한 NFR 프로파일. 단방향 의존(5가 4의 근거 산출을 소비) = 자연스럽고 코드 순환 없음 |
| D3 | **Grounding 위치** | 별도 유닛 신설 없이 **`shared/ports` 확장**. 단일 근거화 철학·단일 인터페이스 + 도메인별 Validator(Search/Summary/Agent) 레지스트리. U6는 게이트웨이/ops 책임 유지. | 코드에 이미 `shared/ports` 존재·순환 방지 |
| D4 | **로드맵 순서** | **엄격한 순차 페이즈** (1→2→…→7). 앞 페이즈 미완이면 다음 페이즈 미착수. **단 D5 예외**. | 사용자 지정 |
| D5 | **페이즈 4·5 병렬 (의존 확정 — A)** | 5→4 의존 **확정(2026-06-28, A)** → 페이즈 4·5는 D4 순차의 예외로 **"계약 게이트 병렬 쌍"**으로 진행. 두 유닛 모두 페이즈 1~3 완료 후 **동시 착수**. 전제: ⓐ 에이전트 Tool 포트 계약·근거 출력 DTO를 `shared/`에 **선행 동결**, ⓑ 5는 4의 **녹화 fixture(golden output)**로 개발, ⓒ 5의 "완료"는 **실제 4와의 통합 게이트 통과 후**에만. | 5가 4 *계약*에 의존(U2 Mock 선행 재사용) |
| D6 | **DocModel 완성형 = 인덱싱 기반** | U1이 수집 시점에 **DocModel 완성형을 eager(전량) 생성**하고, **OpenSearch 인덱싱을 DocModel 기반**으로 한다. → 현재 코드 대비 2가지 전환: ① DocModel 빌드를 **요약 시점 lazy → 수집 시점 eager**, ② 인덱싱 소스를 **full-text 청크 → DocModel(Block) 기반**으로 전환. 기존 lazy 빌드 큐(U7 `SqsDocModelBuildQueue`)의 역할 재정의. | 사용자 지정(페이즈 1 핵심 의도) — rework 방지 위해 명문화 |

---

## 2. 코드 베이스라인 드리프트 (문서 ≠ 코드)

리버스 엔지니어링으로 확인한 **문서와 실제 코드의 차이**. 본 표는 재인셉션 진행 중 계속 갱신한다.

| 영역 | 현행 문서 주장 | 실제 코드 | 처리 |
|---|---|---|---|
| 연구 에이전트 | U11 인셉션 완료(PR #170) | `backend/modules/`에 `research_agent` **모듈 부재** | 코드 기준 **그린필드**로 인셉션 |
| U1 수집 소스 | "arXiv OA AI/ML 슬라이스" | **존재**: arXiv 어댑터 = **HTML 우선 → PDF 폴백**(`arxiv.py`, SourceTier ar5iv/native_html)·**단일 소스 watermark**(`postgres.py` `watermark` 테이블, `get/advance/reset_watermark`, name="arxiv")·`docmodel/`·`full_text_extraction.py`·dedup. **부재**: Semantic Scholar/OpenAlex/GROBID 어댑터·**cross-source watermark**·DLQ/scheduler 운영 표면 | 멀티소스·cross-source watermark·운영 표면 **신규 구축**(HTML 우선·단일 watermark는 재사용) |
| 마이페이지(U10) | "타 팀원 구현 중·미반영" | `backend/modules/mypage` **코드 존재** | 코드 기준으로 유닛 정식화 |
| U6 위치 | 게이트웨이(`backend/middleware/`) + ops 워커(`ops/`) | 추가로 `backend/modules/ops`도 존재 → **3군데 분산** | 재인셉션 때 경계 정리 |
| `shared/ports` | 근거화·비용 후크 인터페이스 | 코드 존재 확인 | D3(grounding 확장)의 기반으로 채택 |

> **정밀판**: `aidlc-docs/inception/reverse-engineering/code-baseline-2026-06.md` (2026-06-26 1차 패스).
> 패키지 맵·페이즈별 코드 현황·에이전트 소비 계약 인벤토리·`shared/ports` 상태·설계 긴장점을 코드에서 확인.

---

## 3. 로드맵 — 7 페이즈 (엄격 순차, D4)

> 번호 표기 주의: 아래 "U1/U2/U6/U7"은 **현행 유닛 번호를 임시 참조**한 것이다. 신규 인셉션
> (D1)의 unit-of-work 재생성 시 **유닛 번호를 새로 부여**한다. 기존 번호에 끼워맞추지 않는다.
>
> **로드맵 갱신(2026-06-28)**: ① 기존 페이즈 3(요약/번역)·4(Grounding)를 **하나로 병합**(함께 진행 —
> 요약 LLM 단계에 grounding이 곧바로 종속되므로 분리 진행 이득이 적음), 이후 번호 한 칸씩 당김.
> ② 페이즈 4(문헌탐색·근거형성) 담당을 **화랑님**으로 변경.

| 페이즈 | 제목 | 담당 | 현행 유닛 참조 | 선행 의존 | 코드 현황 |
|---|---|---|---|---|---|
| **1** | U1 완성 — Corpus 생성 파이프라인 | **준희님** | U1 Ingestion | — | arXiv·docmodel·dedup 일부 존재, 멀티소스 신규 |
| **2** | U2 검색 | 유진님 | U2 Discovery | 1 | discovery 모듈 존재 |
| **3** | U7 요약/번역 + Grounding Framework 통합 | 유진님 | U7 Summarization / U6 / `shared/ports` | 1·2 | summarization·`shared/ports`·middleware 존재 |
| **4** | 문헌탐색·근거형성 Agent | **화랑님** | (신규) | 1·2·3 | **그린필드** |
| **5** | 연구 아이디어 Agent | **석현님** | (신규) | 1·2·3 + **4 계약**(의존 확정 A·병렬·D5) | **그린필드** |
| **6** | Corpus 대량 구축 | **준희님** | U1 스케일링 | 1 | 1 완성 후 |
| **7** | 검색 품질 개선 | 유진님 | U2 개선 | 2 | 2 안정화 후 |

### 페이즈 1 — U1 완성 (Corpus 생성 파이프라인)
**목표**: AI가 사용할 Corpus를 자동 구축하는 파이프라인 완성.
**수집(순위대로 중복제거)**:
```
arXiv             :  HTML 우선, 없으면 PDF      (존재)
Semantic Scholar  :  PDF (GROBID)               (신규)
OpenAlex          :  PDF (GROBID)               (신규)
       |
       v
  Source별 중복 제거
       |
       v
  FullText 추출
       |
       v
  DocModel 완성형 생성
       |
       v
  Chunk  -->  Embedding
       |
       v
  OpenSearch 저장  +  S3 저장
```
**운영**: Scheduler 주기 수집 · Watermark 기반 증분 갱신 · Retry/DLQ · 버전 관리.
**결과**: 최근 AI/ML 1년 Corpus 구축 완료. U2/U7/Agent 데이터 기반 완성.

> **D6 갭 주의 (현재 코드 ≠ 목표)**: 현재 U1 인덱싱은 **full-text 청크 기반**이고 DocModel은
> **요약 시점 lazy 빌드**(U7 `SqsDocModelBuildQueue` → U1 워커)다. D6은 이를 **수집 시점 eager
> DocModel 완성형 + DocModel 기반 인덱싱**으로 전환한다. 청킹 전략(Block 구조)·코퍼스 전량 빌드
> 비용·lazy 큐 역할이 함께 바뀌므로, 페이즈 1 requirements에서 청킹·비용·버전 정책을 함께 확정한다.

### 페이즈 2 — U2 검색
**목표**: 원하는 논문을 빠르고 정확하게 찾는다.
```
Query --> Normalize --> Hybrid Search (Lexical + Semantic) --> Ranking --> Grounding (페이즈 3) --> Search Result
```
**결과**: 검색 안정화 · 검색 API 완성 · Grounding(Search) 완성.

### 페이즈 3 — U7 요약/번역 + Grounding Framework 통합 (D3)
**목표**: 검색된 논문을 AI가 이해하기 쉽게 제공하고, 그 출력의 근거화를 단일 프레임워크로 통합한다.
> **병합 이유(2026-06-28)**: 요약 LLM 출력은 생성 직후 grounding 검증에 곧바로 종속되므로, 요약/번역과
> Grounding 통합을 **한 페이즈에서 함께** 진행한다.

**요약**:
```
DocModel --> Input Refine --> LLM --> Grounding (통합 프레임워크 동시 적용) --> Cache
```
**번역**: 초록 = Metadata 저장 Abstract 사용 · 본문 = DocModel(v1) 사용.

**Grounding 통합 (D3)** — 유닛 신설 없이 `shared/ports`의 근거화 후크를 도메인별 Validator 레지스트리로 확장:
```
Grounding Framework   (철학 하나 / 인터페이스 하나 ; shared/ports)
    |
    +--> Search  Validator
    |
    +--> Summary Validator
    |
    +--> Agent   Validator
         (도메인별 분리)
```
**결과**: 구조화 요약 · 초록 번역 · 본문 번역 · Cache · 비용 제어 · 단일 Grounding 프레임워크(Search/Summary/Agent Validator).

### 페이즈 4 — 문헌탐색·근거형성 Agent (화랑님, 그린필드)
**목표**: 다논문을 교차확인해 근거를 비교·정리하고, 근거가 없으면 기권하는 대화형 연구 보조. (5→4 의존 확정[A] → **페이즈 5의 하부 Tool**이다.)
- **구체 파이프라인·방식은 인셉션 질문지(requirements)로 결정** — 본 차터는 목표·경계만 고정한다.
- **UI 방식(유효)**: 네비 전용 진입의 **채팅 형식**, 모드만 다르게 (문헌탐색·근거형성 모드).

### 페이즈 5 — 연구 아이디어 Agent (석현님, 그린필드)
**목표**: 기존 연구를 분석해 새 연구 아이디어를 제안.
- **페이즈 4(문헌탐색·근거형성 Agent) 의존 = 확정(A, 2026-06-28)**: 새 아이디어의 novelty/Research Gap 판단에 4의 근거 산출이 입력이므로 4를 **Tool로 재사용**한다. 계약 *디테일*(근거 출력 DTO·포트)은 4 유닛 질문지 후 `shared/`에 동결.
- **구체 파이프라인·방식(novelty 분석·Research Gap 탐색 등)은 미확정** — 이후 인셉션 질문지로 결정한다.

### 페이즈 6 — Corpus 대량 구축 (준희님)
```
AI/ML 최근 1년  -->  최근 5년  -->  전체  -->  타 분야 확장
(필요 시: DocModel 재생성 / Embedding 재생성 / OpenSearch Reindex)
```

### 페이즈 7 — 검색 품질 개선
Chunk 전략 · Embedding 모델 · Hybrid Search · Cross-Encoder Reranker · Learning to Rank ·
Query Expansion · Ranking Personalization · Feedback Learning · Click Log 기반 Ranking 개선.

> **백로그 (페이즈 2 이월, 2026-06-29)**:
> - **연도/메타데이터 facet 필터** — 검색창의 정렬(관련도순/최신순) 옆에 연도 선택(전체/2026/2025…). 클라이언트 top-N 필터가 아니라 **백엔드 facet**으로: `SearchRequest`에 연도 필터 추가 → `HybridRetriever`가 OpenSearch `year` 필드로 필터 재질의 → 전체=전체 정렬, 연도 선택=그 연도 결과에 관련도/최신순 정렬. (페이즈 2에서 "검색 기능 추가"라 범위 밖으로 이월.)
> - **상세 라우트 소스 중립 *식별자*** — 상세 **헤더**의 소스 표시·링크아웃은 페이즈 2에서 소스 중립화 완료(`PaperMetaDTO`/`PaperMetaVM` +sourceName/sourceUrl·`PaperDetailIsland` 렌더, 카드와 일치). **잔여**: 라우트 *키* 자체(`/paper/{id}`가 `arxivId` 기반)는 비-arXiv 전용 논문(arXiv 미수록) 대비 소스 중립 id 필요(U2 코드리뷰 #3 — id/라우트 부분만 이월).

---

## 4. 에이전트 유닛 경계 재설계 (D2 — 2유닛 분리 승인 / 의존 방향 — 확정 대상)

> **의존 확정 주의(2026-06-28)**: **2유닛 분리·5→4 단방향 의존 모두 확정(A)**. 본 §4·§4.1이 그 설계다.
> 단 근거 출력 DTO 등 **계약 디테일**은 문헌탐색·근거형성 유닛 질문지 후 `shared/`에 동결한다.

페이즈 4·5를 **두 유닛으로 분리**하고, 5가 4를 포트로 의존하는 단방향 구조로 간다(의존 확정 A).

```
연구아이디어 유닛 (석현님)  ---- 포트 의존 ---->  문헌탐색·근거형성 유닛 (화랑님)
  오케스트레이션 / 생성 / novelty                추출 / 근거형성 / 기권
     |
     +-- Tool로도 소비: Search / DocModel / Summary / Citation
     v
  Research Proposal
```

**분리 근거** (의존 방향과 무관하게 2유닛 분리를 지지)
- 5번 워크플로우가 4번을 **Tool로 호출**(의존 확정 A) → 의존 단방향·코드 순환 없음.
- **담당이 다름**(4=화랑님, 5=석현님) → 유닛=리뷰·소유 경계가 깔끔, 머지 충돌 감소.
- **NFR 상이**: 4는 추출·근거형성(faithfulness·기권 핵심), 5는 생성·novelty(창의성·긴 분석 잡).

**공유는 계약으로**: 세션 모델·근거표 계약·UI 네비는 `shared/`로 공유. D3과 동일하게 포트
인터페이스로 의존을 역전한다.

**대안(기각)**: 한 유닛 모드 A/B 공동소유 — 상충하는 품질 기준이 한 경계에 공존, 소유 모호.

### 4.1 계약 게이트 병렬 실행 (D5) — *5→4 의존 확정(A) 적용*

(5→4 의존이 확정(A)되었으므로 아래 실행 패턴을 적용한다.)
4·5는 D4 순차의 예외로 **동시 진행**한다. 5는 4의 *완성 구현*이 아니라 *포트 계약*에만 의존하므로
(U2를 Mock API로 선행 개발한 패턴과 동일), 계약을 먼저 동결하면 두 담당이 병렬로 간다.

```
[준비]  shared/ 에 에이전트 Tool 포트 계약 + 근거 출력 DTO 동결 (버전 고정)
           |
           +----------------------------+----------------------------+
           v                                                         v
  화랑님: 페이즈4 실제 구현                       석현님: 페이즈5 구현
  (추출 / 근거형성 / 기권)                        (4의 녹화 fixture 기반)
           |                                                         |
           +----------------------------+----------------------------+
                                        v
  [통합 게이트]  4 실제본 착지  -->  5를 실제 4로 재검증  -->  5 "완료" 인정
```

**전제 조건 (미충족 시 병렬 깨짐)**
1. **포트 계약·근거 출력 DTO 선행 동결** — 4의 evidence 스키마가 흔들리면 5가 깨진다(최대 리스크). 버전 박아 동결.
2. **5는 단순 stub가 아니라 4의 녹화 fixture(golden output)로 개발** — novelty 품질이 4의 실제 근거형성 거동에 의존. 화랑님이 초기 실제 evidence 산출물을 fixture로 제공.
3. **5의 "완료"는 통합 게이트 통과 후에만** — 실제 4와 결합 전엔 done 아님.
4. **공동 시작점(구현)** — 4·5 **구현**은 페이즈 1~3(코퍼스·검색·요약+grounding)이 **가용**해진 뒤 착수.

### 4.2 착수 타이밍 — 인셉션 문서 vs 구현 (2026-06-28 명확화)

두 트랙을 분리해서 본다. "4가 먼저"는 **코드 선착**이 아니라 **계약 선착**이라는 뜻이다.

- **인셉션 문서(requirements·user-stories·application-design·units)**: 계약·설계 레벨이라 **코드 가동이 필요 없다.**
  페이즈 1~3의 *계약/요구사항*이 안정되면 **1~3 구현과 병행해 4·5 문서를 저술해도 된다**(소비할 DocModel/Search/Summary/grounding 계약은 이미 코드에 존재). → **"1~3 진행하면서 4·5 문서 작성" = 가능.**
- **4 문서가 5 문서보다 꼭 먼저인가?** 아니다 — 두 문서는 대체로 병행 가능. 단 **5→4 의존이 확정(A)** 이므로 5 설계가 4의 **근거 출력 계약(evidence DTO·Tool 포트)** 에 잠긴다 → 그 **계약 골격만 4 쪽에서 먼저 합의·동결**돼야 한다(나머지 5 자체 설계는 동시 진행).
- **5 담당(석현님)이 독립적으로 진행 가능한가?** 5의 *자체 범위*(오케스트레이션/novelty/생성)는 독립 진행 가능. **4의 인터페이스 부분만** 4의 *계약*(코드 아님)에 종속 — 4의 완성 구현을 기다릴 필요는 없다. 독립 채택 시엔 그 종속도 없다.
- **구현 병렬 착수 시점**: 페이즈 1~3 가용 **+** 에이전트 Tool 포트·evidence DTO **동결**(의존 A) + 4의 초기 golden fixture 제공 → 그때부터 4·5 동시 구현, 통합 게이트에서 5를 실제 4로 재검증.
- **질문지·user-stories 작성 절차**: 4·5의 인셉션 질문지·요구사항·user-stories는 **각 유닛 오너(4=화랑님·5=석현님)가 각자 병렬로** 작성한다 — 한 사람이 상대 문서를 먼저 대필할 필요 없음. **공동 선행이 필요한 것은 "공유 계약"뿐**(에이전트 Tool 포트·근거 출력 DTO·세션 모델·근거표·UI 네비 = `shared/`). 의존 확정(A)이므로 그 공유 계약(특히 4의 근거 출력 DTO)만 공동 선행하면 나머지는 각자 병렬.

---

## 5. 미해결·확인 필요 (다음 단계에서 해소)

requirements 단계 진입 전 사용자/팀 확정이 필요한 항목:

1. ~~**D2 최종 승인** — 에이전트 2유닛 분리(§4) 확정 여부.~~ → **2026-06-26 2유닛 분리 승인 + 2026-06-28 5→4 의존 확정(A)** → D5 계약게이트 병렬 적용. (계약 *디테일* 동결은 문헌탐색·근거형성 유닛 질문지 후.)
2. **에이전트 Tool 포트 계약·근거 출력 DTO 동결** — D5 병렬의 선행 조건. requirements/application-design 단계에서 `shared/`에 먼저 확정.
3. **번역 계약 정합** — "본문=DocModel(v1)"이 doc-model 피벗 이후 현행 계약과 일치하는지(코드 확인 필요).
4. **U6 3분산 정리 방향** — `backend/middleware/`·`ops/`·`backend/modules/ops` 경계 재정의.
5. **마이페이지(U10) 코드 정식화 범위** — 현재 `backend/modules/mypage` 코드를 인셉션에 어떻게 편입할지.
6. **신규 유닛 번호 부여 규칙** — 기존 U1~U11/마이페이지와의 번호 충돌 정리.

---

## 6. 다음 단계 (인셉션 산출물 생성 순서)

1. **리버스 엔지니어링** — `aidlc-docs/inception/reverse-engineering/`에 코드 기준 현황(business-overview·패키지·아키텍처) 생성. → §2 드리프트 표 정밀화.
2. **requirements-analysis** — 7 페이즈를 FR/NFR/C로 구조화(`requirements/`).
3. **user-stories** — 페르소나·스토리 갱신.
4. **application-design** — 컴포넌트·서비스·의존 재설계.
5. **units-generation** — 유닛 경계·번호 재부여(§4 반영), 배포 단위 재정의.

> 각 단계는 본 차터를 기준으로 진행하며, 새로 드러난 코드 사실은 §2에 역류 기록(back-sync)한다.
