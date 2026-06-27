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
| D2 | **에이전트 유닛 구성** | **2개 유닛으로 분리**(아래 §4): 문헌탐색·근거형성 유닛 / 연구아이디어 유닛. 후자가 전자를 **포트로 의존**(Tool 소비). *(2026-06-26 승인)* | 담당 분리·단방향 의존·상이한 NFR 프로파일 |
| D3 | **Grounding 위치** | 별도 유닛 신설 없이 **`shared/ports` 확장**. 단일 근거화 철학·단일 인터페이스 + 도메인별 Validator(Search/Summary/Agent) 레지스트리. U6는 게이트웨이/ops 책임 유지. | 코드에 이미 `shared/ports` 존재·순환 방지 |
| D4 | **로드맵 순서** | **엄격한 순차 페이즈** (1→2→…→8). 앞 페이즈 미완이면 다음 페이즈 미착수. **단 D5 예외**. | 사용자 지정 |
| D5 | **페이즈 5·6 병렬** | 페이즈 5·6은 D4 순차의 예외로 **"계약 게이트 병렬 쌍"**. 두 유닛 모두 페이즈 1~4 완료 후 **동시 착수**. 전제: ⓐ 에이전트 Tool 포트 계약·근거 출력 DTO를 `shared/`에 **선행 동결**, ⓑ 6은 5의 **녹화 fixture(golden output)**로 개발, ⓒ 6의 "완료"는 **실제 5와의 통합 게이트 통과 후**에만. | 6은 5의 *구현*이 아니라 *계약*에 의존(U2 Mock 선행 패턴 재사용) |
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

## 3. 로드맵 — 8 페이즈 (엄격 순차, D4)

> 번호 표기 주의: 아래 "U1/U2/U6/U7"은 **현행 유닛 번호를 임시 참조**한 것이다. 신규 인셉션
> (D1)의 unit-of-work 재생성 시 **유닛 번호를 새로 부여**한다. 기존 번호에 끼워맞추지 않는다.

| 페이즈 | 제목 | 담당 | 현행 유닛 참조 | 선행 의존 | 코드 현황 |
|---|---|---|---|---|---|
| **1** | U1 완성 — Corpus 생성 파이프라인 | **준희** | U1 Ingestion | — | arXiv·docmodel·dedup 일부 존재, 멀티소스 신규 |
| **2** | U2 검색 | 본인 | U2 Discovery | 1 | discovery 모듈 존재 |
| **3** | U7 요약/번역 | 본인 | U7 Summarization | 1·2 | summarization 모듈 존재 |
| **4** | Grounding Framework 통합 | 본인 | U6 / `shared/ports` | 2·3 | `shared/ports`·middleware 존재 |
| **5** | 문헌탐색·근거형성 Agent | 본인 | (신규) | 1·2·3·4 | **그린필드** |
| **6** | 연구 아이디어 Agent | **석현** | (신규) | 1·2·3·4 + 5 계약(병렬·D5) | **그린필드** |
| **7** | Corpus 대량 구축 | **준희** | U1 스케일링 | 1 | 1 완성 후 |
| **8** | 검색 품질 개선 | 본인 | U2 개선 | 2 | 2 안정화 후 |

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
Query --> Normalize --> Hybrid Search (Lexical + Semantic) --> Ranking --> Grounding (페이즈 4) --> Search Result
```
**결과**: 검색 안정화 · 검색 API 완성 · Grounding(Search) 완성.

### 페이즈 3 — U7 요약/번역
**목표**: 검색된 논문을 AI가 이해하기 쉽게 제공.
**요약**:
```
DocModel --> Input Refine --> LLM --> Grounding (이때 페이즈 4 동시 적용) --> Cache
```
**번역**: 초록 = Metadata 저장 Abstract 사용 · 본문 = DocModel(v1) 사용.
**결과**: 구조화 요약 · 초록 번역 · 본문 번역 · Cache · 비용 제어.

### 페이즈 4 — Grounding Framework 통합 (D3)
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
유닛 신설 없이 `shared/ports`의 근거화 후크를 도메인별 Validator 레지스트리로 확장한다.

### 페이즈 5 — 문헌탐색·근거형성 Agent (그린필드)
다논문 교차확인 → 근거 비교·정리 → 출처 표기 → 기권. **페이즈 6의 하부 Tool**이 된다.

### 페이즈 6 — 연구 아이디어 Agent (석현, 그린필드)
**목표**: 기존 연구를 분석해 새 연구 아이디어를 제안.
```
연구 주제
     |
     v
[ 문헌탐색·근거형성 Agent (페이즈 5) ]
     |
     v
Research Gap 탐색
     |
     v
미해결 문제 발견
     |
     v
Novelty 분석
     |
     v
실험 아이디어 생성
     |
     v
Research Proposal
```
**사용 Tool**: Search · DocModel · Summary · Citation · 문헌탐색·근거형성 Agent.

### 페이즈 7 — Corpus 대량 구축 (준희)
```
AI/ML 최근 1년  -->  최근 5년  -->  전체  -->  타 분야 확장
(필요 시: DocModel 재생성 / Embedding 재생성 / OpenSearch Reindex)
```

### 페이즈 8 — 검색 품질 개선
Chunk 전략 · Embedding 모델 · Hybrid Search · Cross-Encoder Reranker · Learning to Rank ·
Query Expansion · Personalization · Feedback Learning · Click Log 기반 Ranking 개선.

---

## 4. 에이전트 유닛 경계 재설계 (D2 — 승인 / D5 — 병렬)

페이즈 5·6을 **두 유닛으로 분리**하고, 6이 5를 포트로 의존하는 단방향 구조로 간다.

```
연구아이디어 유닛 (석현)  ---- 포트 의존 ---->  문헌탐색·근거형성 유닛 (본인)
  오케스트레이션 / 생성 / novelty                추출 / 근거형성 / 기권
     |
     +-- Tool로도 소비: Search / DocModel / Summary / Citation
     v
  Research Proposal
```

**분리 근거**
- 6번 워크플로우가 5번을 **명시적 Tool로 호출** → 의존 단방향, 코드 순환 없음.
- **담당이 다름**(5=본인, 6=석현) → 유닛=리뷰·소유 경계가 깔끔, 머지 충돌 감소.
- **NFR 상이**: 5는 추출·근거형성(faithfulness·기권 핵심), 6은 생성·novelty(창의성·긴 분석 잡).

**공유는 계약으로**: 세션 모델·근거표 계약·UI 네비는 `shared/`로 공유. D3과 동일하게 포트
인터페이스로 의존을 역전한다.

**대안(기각)**: 한 유닛 모드 A/B 공동소유 — 상충하는 품질 기준이 한 경계에 공존, 소유 모호.

### 4.1 계약 게이트 병렬 실행 (D5)

5·6은 D4 순차의 예외로 **동시 진행**한다. 6은 5의 *완성 구현*이 아니라 *포트 계약*에만 의존하므로
(U2를 Mock API로 선행 개발한 패턴과 동일), 계약을 먼저 동결하면 두 담당이 병렬로 간다.

```
[준비]  shared/ 에 에이전트 Tool 포트 계약 + 근거 출력 DTO 동결 (버전 고정)
           |
           +----------------------------+----------------------------+
           v                                                         v
  본인: 페이즈5 실제 구현                         석현: 페이즈6 구현
  (추출 / 근거형성 / 기권)                        (5의 녹화 fixture 기반)
           |                                                         |
           +----------------------------+----------------------------+
                                        v
  [통합 게이트]  5 실제본 착지  -->  6을 실제 5로 재검증  -->  6 "완료" 인정
```

**전제 조건 (미충족 시 병렬 깨짐)**
1. **포트 계약·근거 출력 DTO 선행 동결** — 5의 evidence 스키마가 흔들리면 6이 깨진다(최대 리스크). 버전 박아 동결.
2. **6은 단순 stub가 아니라 5의 녹화 fixture(golden output)로 개발** — novelty 품질이 5의 실제 근거형성 거동에 의존. 본인이 초기 실제 evidence 산출물을 fixture로 제공.
3. **6의 "완료"는 통합 게이트 통과 후에만** — 실제 5와 결합 전엔 done 아님.
4. **공동 시작점** — 5·6 모두 페이즈 1~4(코퍼스·검색·요약·grounding) 완료가 선행.

---

## 5. 미해결·확인 필요 (다음 단계에서 해소)

requirements 단계 진입 전 사용자/팀 확정이 필요한 항목:

1. ~~**D2 최종 승인** — 에이전트 2유닛 분리(§4) 확정 여부.~~ → **2026-06-26 승인**. 병렬 실행도 D5로 확정.
2. **에이전트 Tool 포트 계약·근거 출력 DTO 동결** — D5 병렬의 선행 조건. requirements/application-design 단계에서 `shared/`에 먼저 확정.
3. **번역 계약 정합** — "본문=DocModel(v1)"이 doc-model 피벗 이후 현행 계약과 일치하는지(코드 확인 필요).
4. **U6 3분산 정리 방향** — `backend/middleware/`·`ops/`·`backend/modules/ops` 경계 재정의.
5. **마이페이지(U10) 코드 정식화 범위** — 현재 `backend/modules/mypage` 코드를 인셉션에 어떻게 편입할지.
6. **신규 유닛 번호 부여 규칙** — 기존 U1~U11/마이페이지와의 번호 충돌 정리.

---

## 6. 다음 단계 (인셉션 산출물 생성 순서)

1. **리버스 엔지니어링** — `aidlc-docs/inception/reverse-engineering/`에 코드 기준 현황(business-overview·패키지·아키텍처) 생성. → §2 드리프트 표 정밀화.
2. **requirements-analysis** — 8 페이즈를 FR/NFR/C로 구조화(`requirements/`).
3. **user-stories** — 페르소나·스토리 갱신.
4. **application-design** — 컴포넌트·서비스·의존 재설계.
5. **units-generation** — 유닛 경계·번호 재부여(§4 반영), 배포 단위 재정의.

> 각 단계는 본 차터를 기준으로 진행하며, 새로 드러난 코드 사실은 §2에 역류 기록(back-sync)한다.
