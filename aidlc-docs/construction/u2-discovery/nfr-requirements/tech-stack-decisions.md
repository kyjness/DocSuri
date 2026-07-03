# tech-stack-decisions.md — U2 Discovery 기술 스택 결정 (ADR, 프로덕션)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U2 Discovery · **트랙**: Track 3(@kyjness) · **일자**: 2026-06-16
**근거**: 계획서(§4 답변 — Q1=A(FastAPI, 합의 전제)·그 외 A) · FD 산출물 · `requirements.md`(C-5 AWS) · U1 `tech-stack-decisions.md`(TD-3/TD-4 [전역])
**스코프**: 단일 프로덕션 트랙. `[전역 계승]`=U1이 PIN한 시스템 결정 상속(재결정 아님) · `[backend-shared]`=backend app-shell 공유 결정(소유자 합의) · 그 외=U2 고유.

> 형식: 결정 · 근거 · 대안 · 전환 비용. 수치/리전/IaC/CI-CD는 NFR Design/Infra.

---

## TD-U2-1 [backend-shared] — API 웹 프레임워크: **FastAPI** _(제안 — app-shell 소유자 합의 전제)_
- **결정**: **FastAPI**(Python). **⚠️ 잠정**: backend 모듈형 모놀리스(단일 런타임·app-shell @ELSAPHABA)의 **공유 결정**이므로 **트랙 사인오프 전까지 확정 아님**. U2는 이 가정 위에서 진행하되 합의 결과 상이 시 재정합.
- **근거**: shared/python 바인딩이 **이미 pydantic v2** → 요청/응답 DTO 검증·직렬화 무드리프트; **async I/O**로 질의 임베딩(Bedrock)+OpenSearch 호출 대기 중첩(NFR-P1); 자동 OpenAPI 스키마.
- **대안**: Flask(동기·경량, async 약함) · Django REST(풀스택, 과중).
- **전환 비용**: app-shell 라우터/DI 결선에 영향 — **backend 전 모듈 공유**라 변경 시 광범위(따라서 합의 선행).

## TD-U2-2 [전역 계승] — API 런타임/언어: **Python**
- **결정**: Python(§5-A 시스템 결정 계승 — backend 단일 런타임).
- **근거**: 공유 런타임(U2/U3/U4/U6-미들웨어)·Hypothesis(PBT)·Bedrock/OpenSearch SDK.
- **전환 비용**: 시스템 전역 — 재논의 아님.

## TD-U2-3 [전역 계승] — 질의 임베딩: **Cohere Embed Multilingual v4 (Bedrock) · 1024 · 코사인 · reader=`search_query`**
- **결정**: TD-3 계승. U2 reader는 **`input_type=search_query`**(writer=`search_document`와 비대칭) — Cohere v4 필수.
- **근거**: U1 writer ↔ U2 reader **동일 임베딩 공간 불변식**(specVersion 일치). **cross-lingual**: 한국어 질의 → 영어 코퍼스(KR↔EN).
- **대안**: 없음(변경 = 전체 코퍼스 재임베딩, 사실상 단방향).
- **전환 비용**: 매우 높음 — VectorSpec 불변.

## TD-U2-4 [전역 계승] — 벡터+lexical 스토어(reader): **OpenSearch**
- **결정**: TD-4 계승. U2.HybridRetriever는 OpenSearch의 **k-NN(ANN) + BM25**를 읽는 **단일 reader**.
- **근거**: 하이브리드(FR-2)·lexical 폴백(US-R2)을 단일 스토어로. 인덱스명·샤드·매핑은 Infra.
- **전환 비용**: 스토어 변경 = 재색인(재임베딩 불요 if VectorSpec 동일).

## TD-U2-5 — OpenSearch 하이브리드 질의 메커니즘: **opensearch-py + 앱 레벨 RRF**
- **결정**: 공식 `opensearch-py` 클라이언트로 k-NN 쿼리 + BM25 쿼리 각각 실행 → **앱 레벨 RRF 병합**(BR-4) → **PaperId 단위 디덥**.
- **근거**: RRF·디덥을 앱 레벨에 두면 mock/real 교체·**결정성(PBT-07)**·튜닝 용이. 점수 스케일 무관(RRF).
- **대안**: OpenSearch 네이티브 하이브리드(search pipeline/normalization processor) — 서버측 병합, 버전·파이프라인 의존(성능 이점은 Infra 재검토 여지).
- **전환 비용**: 낮음(병합 로직 교체) — 단 PBT-07 속성 유지 전제.

## TD-U2-6 — 질의 임베딩 어댑터(LlmGatewayAdapter): **Bedrock SDK(boto3) — Cohere search_query**
- **결정**: Bedrock 직접 호출(`input_type=search_query`). U6 게이트웨이 경유(component-dependency.md)이나 어댑터는 U2 모듈.
- **근거**: TD-3 정합. **Q1=A/Q3=A로 LLM 질의 재작성·리랭킹 없음** → U2의 LLM/임베딩 호출은 **검색당 질의 임베딩 1회**(NFR-C1 동인 최소).
- **전환 비용**: 낮음(포트 뒤 추상).

## TD-U2-7 — 질의 임베딩 캐싱: **임베딩 캐시(정규화 질의 키 + 명시 TTL)**
- **결정**: 정규화 질의(NFC) 키 기반 임베딩 캐시, **명시 TTL**(만료 없는 키 금지). 결과 페이지 캐시는 **후순위**(신선도·owner 스코프 복잡).
- **근거**: 동일 질의 재임베딩 회피 → NFR-P1 레이턴시·NFR-C1 비용 절감. 캐싱 규약(미스 시 원본 적재).
- **대안**: 결과 캐시(신선도 정책 동반) · 무캐시.
- **전환 비용**: 낮음 — 캐시 스토어(인메모리/Redis 등)·TTL 수치는 Infra.

## TD-U2-8 [전역 계승] — PBT 프레임워크: **Hypothesis**(Python)
- **결정**: TD-8 계승. PBT-02/03/07/09(도메인 제너레이터=다국어 질의·shrinking·시드 재현성).

## TD-U2-9 [backend-shared] — 빌드/의존성 + 공급망(SEC-10): **모노레포 `backend/` + uv + 락파일 + SCA + SBOM + 이미지 다이제스트 핀**
- **결정**: UQ2=A 모노레포 backend; uv(또는 app-shell 합의 도구) + 락파일·SCA·SBOM·`:latest` 금지(SEC-10).
- **근거**: U1(`ingestion/`)과 동형 공급망 자세. **CI 실행은 NFR Design.**
- **전환 비용**: 낮음 — 단 backend 공유 툴링이라 app-shell 합의.

---

## 비용 주석 (NFR-C1) — U2 슬라이스
- **NFR-C1 = $1600/월(시스템 전역, U1에서 확정)**. U2 슬라이스 = **검색당 질의 임베딩 1회**(Bedrock Cohere) + OpenSearch 질의 컴퓨트. **Q1=A/Q3=A로 LLM 재작성·리랭킹 없음** → U2 LLM 비용 동인 최소. **임베딩 캐시(TD-U2-7)로 중복 질의 임베딩 회피.** degradeMode(LEXICAL_ONLY)는 임베딩 생략으로 추가 절감. **U6.CostGuardCircuitBreaker가 시스템 상한 강제**(U2는 getBudgetState 조회·분기만).
- 유닛별 비용 배분·근거화(U6) LLM 비용은 U6/Infra Design.

## 결정 요약 & 후속
- ⏳ **TD-U2-1 웹 프레임워크 = FastAPI(제안)** — **app-shell 소유자(@ELSAPHABA) 합의 대기**(backend-shared).
- ✅ **[전역 계승]**: Python · Cohere search_query · OpenSearch · Hypothesis · NFR-C1 $1600.
- ✅ **U2 고유**: 앱 레벨 RRF(opensearch-py) · Bedrock 질의 임베딩 · 임베딩 캐시(TTL).
- 후속(보류): 캐시 스토어/TTL 수치·배포 타깃/콜드스타트(Infra) · CI 스캔 파이프라인(NFR Design) · NFR-P1 수치 실측(Build & Test).
