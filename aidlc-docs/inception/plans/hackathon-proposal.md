# AI 기반 연구 논문 디스커버리 플랫폼 구축 프로젝트

**주제: DocSuri — 자연어 의도 기반 논문 검색·요약·근거형성 AI 서비스**

**작성일**: 2026. 06. 28.
**작성자**: (본인), 준희, 석현, 화랑

AWS AI School 2기
한국전파진흥협회

---

## 목차

1. 프로젝트 개요
   - 1.1 배경 및 목적
   - 1.2 프로젝트 요약
   - 1.3 시스템 구성 개요
2. 팀 구성 및 역할 분담
3. 요구사항 분석
   - 3.1 기능 요구사항
4. 시스템 설계 및 사용 기술
   - 4.1 시스템 설계 개요
   - 4.2 사용 기술
   - 4.3 전체 시스템 아키텍처
5. 구현 계획 및 기대 효과
   - 5.1 구현 계획
   - 5.2 기대 효과
6. 참고문헌

---

## 1. 프로젝트 개요

### 1.1 배경 및 목적

#### 배경

AI/ML 분야에서는 매일 수백 건의 새로운 논문이 arXiv에 게시된다. 대학원생과 연구자는 주 10시간 이상을 문헌 조사에 할애하지만, 방대한 양을 모두 읽고 트렌드를 파악하기란 불가능에 가깝다. 겨우 찾은 논문도 핵심을 파악하기 위해 추가 시간이 필요하며, 정작 실험 설계와 논문 작성에 투자할 시간이 부족한 상황이다.

기존 도구(Google Scholar, Semantic Scholar, arXiv 직접 검색)는 키워드 매칭에 의존해 연구자의 의도를 이해하지 못하고, 검색 결과를 요약해주거나 여러 논문을 교차 검증해주는 기능이 없다. 또한 기존 LLM 기반 도구들은 할루시네이션(날조) 문제로 학술 맥락에서 신뢰할 수 없다.

#### 목적

본 프로젝트는 LLM과 벡터 임베딩 기술을 활용하여, 연구자가 **자연어로 연구 의도를 입력하면 가장 관련 높은 논문을 찾고, AI가 구조화 요약·번역·다논문 교차확인까지 수행하되 모든 출력에 원문 근거를 부착하고 근거 없으면 기권하는** 신뢰할 수 있는 AI 연구 보조 플랫폼을 구축하는 것을 목적으로 한다.

### 1.2 프로젝트 요약

| 항목 | 내용 |
|------|------|
| **프로젝트명** | DocSuri (독수리) |
| **한 줄 소개** | 자연어로 물어보면, 근거 있는 논문을 찾아주는 AI 연구 보조 |
| **개발 기간** | 2026.06.03 ~ 2026.07.06 (5주) |
| **팀 규모** | 4명 |
| **타겟 사용자** | AI/ML 분야 대학원생·연구자 |
| **핵심 기술** | LLM 기반 요약/번역/Agent, 벡터 시맨틱 검색, Grounding Framework |
| **플랫폼** | 모바일 웹 (폰 우선 반응형) |
| **인프라** | AWS (OpenSearch, S3, SQS, ECS, CDK) |

### 1.3 시스템 구성 개요

DocSuri는 다음 4개 계층으로 구성된다:

| 계층 | 역할 | 핵심 컴포넌트 |
|------|------|--------------|
| **데이터 수집** | 논문 멀티소스 수집·구조화·인덱싱 | Ingestion Pipeline, DocModel, OpenSearch |
| **AI 처리** | 검색·요약·번역·Agent·근거화 | FastAPI Backend, LLM API, Grounding Framework |
| **사용자 인터페이스** | 폰 우선 웹 UI | Next.js Frontend, 리치뷰어 |
| **운영·인프라** | 배포·모니터링·비용 제어 | AWS CDK, CloudWatch, 서킷 브레이커 |

**핵심 흐름 (매직 모먼트)**:
```
연구자가 자연어 의도 입력
    → 시맨틱 검색으로 관련 논문 발견
    → AI 구조화 요약으로 핵심 파악
    → Agent가 다논문 교차확인·비교표 생성
    → 모든 결과에 원문 출처 부착 (근거 없으면 기권)
```

---

## 2. 팀 구성 및 역할 분담

| 이름 | 담당 역할 | 주요 기여 내용 |
|------|-----------|---------------|
| **본인** | Backend Lead / AI 엔지니어 | 검색 모듈(U2) 개발, 요약·번역 모듈(U7) 개발, Grounding Framework 설계·구현, 문헌탐색 Agent 개발, 전체 백엔드 아키텍처 설계 |
| **준희** | Data Engineer | Corpus 생성 파이프라인(U1) 개발, 멀티소스 수집(arXiv·S.Scholar·OpenAlex), DocModel 구조화, 임베딩·인덱싱 파이프라인, 대량 코퍼스 구축 |
| **석현** | AI Agent 개발 | 연구 아이디어 Agent 개발, Novelty 비교 기능, Research Gap 탐색, Research Proposal 생성 |
| **화랑** | Frontend 개발 | Next.js 기반 UI/UX 구현, 리치뷰어(수식·표·그림 렌더링), 마이페이지, 개인화 표면, 모바일 최적화 |

---

## 3. 요구사항 분석

### 3.1 기능 요구사항

| ID | 기능 | 설명 | AI/LLM 활용 |
|----|------|------|-------------|
| **FR-1** | 자연어 시맨틱 검색 | 자유 텍스트로 연구 의도를 입력하면 하이브리드 검색(Lexical + Vector)으로 관련 논문 Top-20 반환 | Cohere Embed v4 벡터 임베딩 |
| **FR-2** | AI 구조화 요약 | 선택 논문의 전문(DocModel)을 분석해 핵심주장·방법·결과·한계를 구조화 요약, 각 항목에 원문 출처 앵커 부착 | LLM Generation + Grounding |
| **FR-3** | 한국어 번역 | 초록/본문을 원문 구조(섹션·표·수식) 유지한 채 한국어 번역. 전문용어 일관성 보장 | LLM Translation |
| **FR-4** | 대화형 문헌탐색 Agent | 여러 논문을 검색·교차확인해 근거 비교표(논문별 기법·성능·trade-off) 자동 생성 | Multi-hop RAG + Agent |
| **FR-5** | 연구 아이디어 Novelty 비교 | 사용자 연구 주제에 대해 유사 논문 N개를 찾고 겹치는 점/다른 점을 비교 제시 | Agent + 유사도 분석 |
| **FR-6** | Grounding (근거화) | 모든 AI 출력에 검증 가능한 원문 출처를 부착하고, 근거가 불충분하면 날조 대신 기권 | Grounding Validator |
| **FR-7** | Corpus 자동 구축 | arXiv → S.Scholar → OpenAlex 멀티소스 수집, 중복 제거, DocModel 생성, 벡터 인덱싱 | Embedding 파이프라인 |
| **FR-8** | 리치뷰어 | 논문 DocModel을 앱 내에서 수식(KaTeX)·표·그림과 함께 렌더링, 요약 출처 앵커 클릭 시 해당 위치로 점프 | DocModel 파싱 |
| **FR-9** | 인용 그래프 | 논문의 backward references를 트리로 시각화 (1-hop 기본, 2-hop 확장) | 메타데이터 추출 |
| **FR-10** | 개인화 | 사용자 행동 기반 검색 결과 rerank + 요약/번역 기본값 개인화 | 행동 분석 + Boost |
| **FR-11** | 사용자 계정 | 가입·로그인·소셜로그인(Google OIDC)·비밀번호 재설정·계정 삭제 | — |
| **FR-12** | 라이브러리·저장 검색 | 논문 개인 라이브러리 저장, 검색 질의 저장·재실행, 검색 이력 | — |

---

## 4. 시스템 설계 및 사용 기술

### 4.1 시스템 설계 개요

본 시스템은 **모듈러 모놀리스** 아키텍처를 채택한다. 각 기능을 독립 모듈로 개발하되 하나의 FastAPI 런타임에서 구동하여 배포 복잡성을 줄이고, 모듈 간 통신은 내부 함수 호출로 처리해 네트워크 오버헤드를 제거한다.

**설계 원칙**:
- **Grounding First**: 모든 AI 출력은 Grounding Framework를 통과해야 하며, 검증 실패 시 기권
- **DocModel 중심**: 논문 데이터의 단일 진실 원천(SSOT)은 구조화 DocModel (섹션·블록·표·수식·그림)
- **Fail-Closed**: 장애 시 부정확한 결과보다 명시적 에러·기권을 선택
- **폰 우선**: 360px 이상에서 완전히 가독·조작 가능한 UI

**모듈 구성**:
- **U1 Ingestion**: 멀티소스 수집 → DocModel → 청킹 → 임베딩 → 인덱싱
- **U2 Discovery**: 하이브리드 검색 (lexical + kNN vector)
- **U3 Accounts**: 사용자 인증·인가·세션 관리
- **U4 Library**: 개인 라이브러리·저장 검색·이력
- **U7 Summarization**: AI 구조화 요약·번역 (비동기 잡)
- **U8 Citation Graph**: 인용 트리 구축·조회
- **U9 Personalization**: 행동 프로필 집계·개인화 적용
- **Agent (문헌탐색)**: 다논문 교차확인·근거 비교표 생성
- **Agent (연구아이디어)**: Novelty 비교·Research Gap 탐색

### 4.2 사용 기술

| 구분 | 사용 기술 |
|------|-----------|
| **Frontend** | Next.js 14 (App Router · SSR), TypeScript, CSS Modules, KaTeX (수식 렌더링) |
| **Backend** | FastAPI, Python 3.12, SQLAlchemy, Pydantic v2 |
| **검색** | Amazon OpenSearch Service (하이브리드: BM25 lexical + kNN vector 1024d) |
| **임베딩** | Cohere Embed v4 (다국어, 1024차원, specVersion v2) |
| **LLM** | Claude / GPT-4 (구조화 요약·번역·Agent 추론) |
| **데이터베이스** | Amazon RDS PostgreSQL (메타데이터·계정·행동 로그) |
| **오브젝트 저장소** | Amazon S3 (DocModel JSON·논문 자산·이미지) |
| **메시징/큐** | Amazon SQS (요약/번역/DocModel 빌드 비동기 잡) |
| **컨테이너** | Amazon ECR + ECS Fargate |
| **IaC** | AWS CDK (TypeScript) |
| **CI/CD** | GitHub Actions (PR 자동 빌드·테스트·배포) |
| **모니터링** | Amazon CloudWatch (메트릭·로그·알람), 서킷 브레이커 |
| **외부 API** | arXiv API, Semantic Scholar API, OpenAlex API, GROBID (PDF 파싱) |

### 4.3 전체 시스템 아키텍처

텍스트 흐름:

1. 사용자(모바일 웹 브라우저)가 HTTPS로 Frontend(Next.js App Router, SSR, BFF)에 접속한다.
2. Frontend는 same-origin BFF API를 통해 FastAPI 모듈러 모놀리스에 요청한다.
3. FastAPI Backend는 U2 검색, U7 요약/번역, U3 계정, U4 라이브러리, U8 인용 그래프, U9 개인화, 문헌탐색 Agent, 연구아이디어 Agent를 제공한다.
4. AI 출력은 Grounding Framework를 통과해 인덱스 실재성, 원문 앵커, 다논문 교차근거를 검증한다.
5. Backend는 OpenSearch, S3, RDS, Redis, Bedrock/Cohere, SQS를 사용해 조회·저장·비동기 작업을 수행한다.
6. U1 Ingestion Pipeline은 arXiv, Semantic Scholar, OpenAlex에서 수집한 논문을 중복 제거하고, HTML/GROBID 기반 FullText 추출 후 DocModel을 생성한다.
7. U1은 DocModel 블록을 청킹하고 Cohere Embed v4로 임베딩한 뒤 OpenSearch에 색인하고 S3에 저장한다.
8. Scheduler, watermark, retry, DLQ가 인제스천 전 단계를 보호한다.

**Grounding Framework 상세**:
텍스트 흐름:

1. Search Validator는 검색 결과가 실제 인덱스 문서에서 나온 것인지 검증한다.
2. Summary Validator는 요약·번역 출력의 원문 앵커 존재 여부를 검증한다.
3. Agent Validator는 다논문 교차확인 결과가 제공된 근거 안에서만 만들어졌는지 검증한다.
4. 공통 원칙은 근거 없는 주장을 생성하지 않고, 날조 대신 기권하는 것이다.

---

## 5. 구현 계획 및 기대 효과

### 5.1 구현 계획

| 주차 | 기간 | 마일스톤 | 담당 | 산출물 |
|------|------|----------|------|--------|
| **W1** | 06/03 ~ 06/08 | Corpus 파이프라인 + 검색 안정화 | 준희(U1), 본인(U2) | arXiv 수집 → DocModel → OpenSearch 인덱싱 동작, 검색 API 응답 확인 |
| **W2** | 06/09 ~ 06/15 | 요약/번역 + Grounding | 본인(U7, Grounding), 화랑(UI 기본 구조) | 구조화 요약·번역 API 동작, Grounding 검증 계층 완성, 프론트 검색 화면 |
| **W3** | 06/16 ~ 06/22 | Agent 개발 + 멀티소스 확장 | 본인(문헌탐색), 석현(연구아이디어), 준희(S.Scholar·OpenAlex) | Agent 프로토타입 동작, 멀티소스 수집 추가 |
| **W4** | 06/23 ~ 06/29 | 통합 + Frontend 완성 | 전원 | 전체 기능 통합, 리치뷰어·마이페이지·인용 그래프·개인화 UI 완성 |
| **W5** | 06/30 ~ 07/06 | QA + 데모 준비 | 전원 | 버그 수정, 성능 최적화, 데모 시나리오 확정, 발표 자료 작성 |

**데모 시나리오** (발표 시 시연 흐름):
1. 홈 화면에서 "diffusion models for protein structure prediction" 입력
2. 검색 결과 Top-5 확인 (제목·연도·관련도 점수)
3. 논문 1편 선택 → AI 구조화 요약 (핵심주장·방법·한계 분리)
4. "출처 보기" 클릭 → 리치뷰에서 원문 해당 위치로 점프
5. 한국어 번역 (구조 보존 상태)
6. Agent에게 "이 분야 주요 3편 비교해줘" → 근거 비교표 생성
7. 인용 그래프에서 핵심 참고문헌 탐색
8. 관심 논문 라이브러리에 저장

### 5.2 기대 효과

#### 정량 효과

| 지표 | 현재 (기존 도구) | 목표 (DocSuri) |
|------|-----------------|---------------|
| 주간 문헌 조사 시간 | 10시간+ | 5시간 이하 (50% 절감) |
| AI 출력 할루시네이션 | 불확실 | 0건 (Grounding 검증) |
| 검색 Top-5 적중률 | — | 80%+ (평가셋 기준) |
| 검색 응답 시간 | — | < 3초 (P95) |
| 요약 생성 시간 | — | < 15초 |

#### 정성 효과

- **연구 생산성 향상**: "찾는 시간"을 줄이고 "읽고 생각하는 시간"에 집중
- **논문 접근성 강화**: 한국어 구조화 번역으로 비영어권 연구자의 문헌 이해도 향상
- **문헌 리뷰 효율화**: Agent의 근거 비교표로 다논문 비교 시간 대폭 단축
- **AI 신뢰성 확보**: Grounding Framework로 학술 맥락에서 LLM 활용의 신뢰 기반 제시

#### 차별화 포인트

1. **"절대 거짓말하지 않는 AI"** — 근거 없으면 날조 대신 기권하는 명시적 정책
2. **구조화 논문 이해** — 표 숫자·수식·그림까지 AI가 "볼 수 있는" DocModel 기반
3. **멀티소스 Corpus** — 단일 소스 한계 돌파 (arXiv + Semantic Scholar + OpenAlex)
4. **다단계 Agent** — 단순 RAG가 아닌 다논문 교차확인·Research Gap 탐색

#### 향후 확장 계획

| 단계 | 내용 |
|------|------|
| v1.1 | Corpus 5년 확장 + 타 학문 분야(NLP, CV, Bio 외) |
| v1.2 | 추천 시스템 고도화 (개인화 학습) |
| v2.0 | 연구실 내 협업 기능 (공유 라이브러리·주석) |
| v2+ | 실험 재현성 자동 검증, 논문 작성 보조 |

---

## 6. 참고문헌

1. Lewis, P. et al. (2020). "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks." *NeurIPS 2020*.
2. Cohere. (2024). "Embed v4: Multilingual Embeddings with Matryoshka Representations." Cohere Documentation.
3. Gao, L. et al. (2023). "Retrieval-Augmented Generation for AI-Generated Content: A Survey." *arXiv:2402.19473*.
4. Semantic Scholar API Documentation. Allen Institute for AI.
5. OpenAlex Documentation. OurResearch.
6. arXiv API Documentation. Cornell University.
7. GROBID — GeneRation Of BIbliographic Data. GitHub.
8. Amazon OpenSearch Service Developer Guide. AWS Documentation.
