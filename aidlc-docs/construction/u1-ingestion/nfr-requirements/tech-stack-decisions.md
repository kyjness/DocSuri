# tech-stack-decisions.md — U1 Ingestion 기술 스택 결정 (ADR, 프로덕션)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U1 Ingestion · **일자**: 2026-06-16
**근거**: 계획서 프로덕션 답변 배너 · FD 산출물 · `requirements.md`(C-5 AWS) · [[project-aws-integration-spike]]
**스코프**: 단일 프로덕션 트랙(데모 폐기). `[전역]`=U2~U6 상속. **팀 리뷰 대상**(특히 TD-3·TD-4).

> 형식: 결정 · 근거 · 대안 · 전환 비용. 수치/리전/IaC는 Infra Design.

---

## 0. U1 Corpus 기술 스택 우선 적용 개정 (2026-06-26)

> **우선순위**: 본 섹션은 2026-06-26 U1 Corpus NFR Requirements의 최신 결정이다. 아래 TD-3의 Cohere v3, arXiv-only source, lazy DocModel, section/full-text indexing 설명과 충돌하면 **본 섹션을 우선한다**. `shared/vector-spec/vector-spec.yaml`의 `specVersion: v2`가 active vector contract다.

### TD-C1 — 수집 소스 어댑터: 기존 Python worker + source별 HTTP adapters

- **결정**: U1은 기존 Python ingestion worker 안에서 arXiv, Semantic Scholar, OpenAlex adapter를 둔다. 새 항상-on 서비스는 만들지 않는다.
- **근거**: source별 rate limit/watermark만 다르고 pipeline은 동일하다. 별도 service split은 운영 표면만 늘린다.
- **대안**: source별 독립 마이크로서비스. 기각: phase-1에 과함.
- **전환 비용**: 낮음. adapter 추가와 source config 확장.

### TD-C2 — PDF 구조 추출: containerized internal GROBID

- **결정**: Semantic Scholar/OpenAlex PDF와 arXiv PDF fallback은 internal-only GROBID container로 TEI/structure를 추출한다. raw PDF는 transient input으로만 둔다.
- **근거**: 요구사항이 PDF(GROBID)를 명시했고, 외부 SaaS 호출보다 비용/보안/재현성이 낫다.
- **대안**: 단순 PDF text extraction. 기각: section/table/formula 구조 손실. 외부 GROBID SaaS. 기각: raw PDF 외부 전송·비용·가용성 위험.
- **전환 비용**: 중간. Infra Design에서 ECS task/sidecar/service 중 하나로 배치하면 된다.

### TD-C3 — DocModel parser: 기존 HTML parser stack + GROBID TEI parser

- **결정**: arXiv HTML은 기존 TD-16 방향(lxml/BeautifulSoup + MathML->LaTeX)을 유지하고, PDF/GROBID 결과는 TEI XML parser로 같은 DocModel schema에 매핑한다.
- **근거**: 두 경로 모두 deterministic parser이며 LLM 추출을 쓰지 않는다.
- **대안**: LLM extraction. 기각: 표/수식 환각과 비용 폭주.
- **전환 비용**: 중간. parserVersion/sourceTier를 DocModel provenance에 기록한다.

### TD-C4 — Embedding VectorSpec: Cohere Embed v4 / specVersion v2 / 1024 / cosine

- **결정**: active contract는 `shared/vector-spec/vector-spec.yaml`의 Cohere Embed v4(Bedrock), `specVersion=v2`, 1024 dimensions, cosine, writer `search_document`, reader `search_query`다.
- **근거**: v4 migration is already landed in repo config and CDK. U1 Corpus는 모델 교체가 아니라 DocModel Block source/index generation 전환이다.
- **대안**: 새 embedding model 도입. 기각: full re-embed와 U2 reader 재검증이 필요해 phase-8 품질 개선 작업으로 미룬다.
- **전환 비용**: 모델/spec 변경은 전체 Corpus re-embed. 본 단계에서는 변경하지 않는다.

### TD-C5 — OpenSearch generation/alias: 기존 OpenSearch 유지

- **결정**: DocModel Block 기반 새 index generation을 OpenSearch에 만들고 alias cutover한다.
- **근거**: OpenSearch는 이미 vector + BM25 lexical + per-paper delete 요구를 충족한다. 새 store는 필요 없다.
- **대안**: Aurora pgvector/FTS. 기각: 이미 OpenSearch production path가 있고 phase-1 scope에 store migration은 불필요.
- **전환 비용**: generation 생성 + reindex/re-embed. alias rollback으로 완화한다.

### TD-C6 — Scheduler/Queue/DLQ: EventBridge + SQS/DLQ 유지

- **결정**: periodic collection은 EventBridge Scheduler, retry/reprocess는 SQS + DLQ를 사용한다.
- **근거**: 기존 TD-5/TD-6과 일치하며 source별 jobs와 DLQ replay를 가장 작게 구현한다.
- **대안**: Airflow/Step Functions. 기각: phase-1에는 orchestration surface가 과하다.
- **전환 비용**: 낮음. Infra Design에서 queue names, DLQ retention, IAM을 정한다.

### TD-C7 — Artifact storage: private S3 + existing metadata store

- **결정**: normalized FullText, DocModel JSON, assets, generation manifest는 private S3에 저장한다. source provenance/source watermark는 existing control-plane DB에 둔다.
- **근거**: S3는 이미 전문/자산 저장 결정이고, raw PDF non-storage rule과 맞는다.
- **대안**: raw PDF cache. 기각: C-1/§12 위반.
- **전환 비용**: 낮음.

### TD-C8 — Cost guard: $1600 account budget + U1 per-run hard stop

- **결정**: account/app cap은 existing AWS Budget $1600/month를 따른다. U1 Corpus job은 per-run budget guard를 가져 비용 초과 전 신규 fetch/GROBID/embed/index work를 보류한다.
- **근거**: eager Corpus는 사용량 비례가 아니라 선불성 batch cost다. budget guard 없이 전량 backfill을 돌리면 팀 우려대로 비용이 먼저 터진다.
- **대안**: 사후 알림만. 기각: eager backfill에는 늦다.
- **전환 비용**: 낮음. NFR Design에서 metric과 stop condition을 구체화한다.

---

## TD-1 — 워커 언어/런타임: **Python**
- **근거**: ML/임베딩/arXiv(arxiv.py·OAI-PMH) 생태계, Hypothesis(PBT), 선행 사례(사이클 1 Python). 
- **대안**: TS/Node(프런트 통일). 폴리글랏(워커 Python·API 별도).
- **전환 비용**: 워커는 독립 배포(DQ1)라 API 언어와 분리 가능 — 낮음. (API 언어는 U2~U4 NFR Requirements.)

## TD-2 — arXiv 접근: **OAI-PMH(시드 하베스트) + Atom 질의 API(증분)**
- **근거**: 풀 슬라이스 수십만(Q1=D) 시드는 OAI-PMH(`set=cs`, resumptionToken) 대량 하베스트 적합; 일 증분은 Atom API(updated 기준 Q7=A). RES-8 보수 쿼터(예양 지연). **이 프로토콜 한도가 TD-있음: RES-9 타임아웃/재시도 수치(nfr-requirements §3) 근거.**
- **대안**: Atom API 단독(소규모엔 단순하나 수십만 하베스트엔 부적합).
- **전환 비용**: 낮음(어댑터 교체).

## TD-3 [전역] — 임베딩 모델 + VectorSpec: **Cross-lingual 임베딩(Cohere Embed Multilingual v3, Bedrock) · 1024차원 · 코사인** _(2026-06-16 팀 결정 Titan→cross-lingual)_
- **근거**: **한국어 사용자/팀이 영어 arXiv 코퍼스를 질의** → cross-lingual 모델이 한국어 질의와 영어 논문을 동일 벡터 공간에 매핑(KR↔EN 검색). Titan V2(영어 최적)는 한국어 질의 열위. Cohere Embed Multilingual v3는 Bedrock 제공·100+ 언어·1024차원으로 **AWS 트랙·기존 VectorSpec(1024·코사인) 그대로 유지**.
- **가정(팀 확인됨, 2026-06-16)**: **cross-lingual 질의 가정 확정.** (영어 전용이었다면 Titan V2로 충분했으나 팀이 cross-lingual 채택 — 한국어 질의 대응.) cross-lingual은 KR·EN 모두 처리.
- **교차 유닛**: U2 질의 임베딩이 **동일 모델** 사용(VectorSpec 불변식); **QT-2 관련도 평가셋에 한국어 질의 포함**해 cross-lingual 검색 품질 검증 필수.
- **대안**: Bedrock Titan V2(영어 최적, spike 검증); 자체 호스팅 다국어 오픈 모델(multilingual-e5 / BGE-M3, GPU 운영).
- **전환 비용**: **매우 높음 — VectorSpec 변경 = 전체 코퍼스(수십만) 재임베딩**. 사실상 단방향. → 본 단계 PIN. 현 Bedrock 다국어 모델 가용성/단가 확인 권장.

## TD-4 [전역] — 벡터+lexical 스토어: **OpenSearch** _(팀 결정 2026-06-16)_
- **요건(3종 모두 필수)**: (i) ANN 벡터 검색 + (ii) BM25/FTS lexical(U2 하이브리드 FR-2·비용 서킷 lexical 폴백 US-R2) + (iii) **per-paperId 멱등 삭제/tombstone**(FD Q13=B·BR-14·INV-1).
- **근거**: OpenSearch는 k-NN ANN + BM25 + 신뢰성 문서 삭제를 **단일 스토어**로 충족; Bedrock KB 백킹으로도 일반적; TD-3 임베딩(Cohere Embed Multilingual v3, 1024·코사인)과 정합.
- **대안**: **Aurora PostgreSQL(pgvector+FTS)** — 단일 스토어·트랜잭션 삭제·최저 운영비; **S3 Vectors + Bedrock KB**(spike 산출)는 **벡터-ANN 전용** → 동반 lexical 스토어 필요 + 삭제 최종일관성 검증 필요(요건 ii·iii 미충족).
- **전환 비용**: 스토어 변경 = 재색인(재임베딩은 불요 if VectorSpec 동일). **팀 결정 필요**: OpenSearch(권장) vs Aurora pgvector vs S3 Vectors+동반.

## TD-5 — 스케줄러: **EventBridge Scheduler**(증분) + 수동 CLI(triggerFullRebuild)
- **근거**: 관리형 cron(일 1회 US-I2). 시드/재구축은 운영 수동 트리거(AS-5 런북).
- **전환 비용**: 낮음(스케줄 트리거 어댑터).

## TD-6 — 큐/DLQ: **SQS + DLQ**
- **근거**: 재시도·소진 격리(US-I3·BR-16/17), 이벤트 경로(Q12=B) 백본. 관리형·at-least-once.
- **전환 비용**: 낮음(포트 뒤 추상화).

## TD-7 — 오브젝트 스토리지(OA 전문 보관): **S3**
- **근거**: Q2=C 전문 보관(BR-20·StoredFullText), **공개 차단(SEC-9)** + at-rest 암호화(SEC-1), 재구축·재처리 재사용(RES-2).
- **전환 비용**: 낮음.

## TD-8 — PBT 프레임워크: **Hypothesis**(Python)
- **근거**: TD-1 종속; PBT-08 차단성(P1/P3/P4/P5)·도메인 제너레이터·shrinking·시드 재현성.

## TD-9 — 패키징: **컨테이너(이미지 다이제스트 핀, SEC-10)**
- **근거**: 재현 빌드·SEC-10(`:latest` 금지). **실배포 타깃(ECS/Fargate vs Lambda)·오토스케일·리전은 Infra Design**.
- **전환 비용**: 런타임 타깃은 Infra에서 확정.

## TD-10 — 빌드/의존성 + 공급망(SEC-10): **모노레포 `ingestion/` + uv/poetry + 락파일 + SCA + SBOM**
- **근거**: UQ2=A 모노레포; SEC-10 락파일·취약점 스캔·SBOM 산출(스캔 **CI 실행**은 NFR Design).
- **전환 비용**: 낮음.

---

## 멀티모달 자산 추출 ADR (FR-17 — 표시 전용, 2026-06-22 확장)

> 상속: TD-1 Python·TD-7 S3·TD-8 Hypothesis·TD-9 컨테이너·TD-10 패키징. TD-3/4(임베딩·OpenSearch)는 **무관**(자산 검색 비대상). NFR 계획 Q1~Q7=A.
>
> **피벗 재검토 (2026-06-23, doc-model — SSOT=`construction/plans/docmodel-foundation-pivot-plan.md`)**: 표시 전용 → **콘텐츠 1급화**. **표 = PDF 크롭(TD-12) 폐기 → HTML 구조화 데이터**(D8); **수식 = MathML→LaTeX**; HTML 결정적 파서 스택 신규(**TD-16**). **그림 webp 추출·정규화(TD-13/14/15)는 유지**(doc-model이 `assetId`로 참조). PDF 크롭(TD-11)은 **최후 폴백**으로 강등.

## TD-11 — PDF 페이지 크롭(page-crop) 도구: **permissive 스택 휴리스틱** (Q1=A)
> **피벗 강등 (2026-06-23, D8/Q6)**: doc-model 전환으로 page-crop은 **HTML 전무(~9%) 논문의 최후 폴백**으로 강등(`native HTML → ar5iv → e-print LaTeX → (최후) PDF`). 주 추출은 HTML 파서(TD-16). **표는 더 이상 크롭하지 않음**(데이터로, TD-12) — page-crop은 PDF밖에 없는 논문의 **그림** 확보용으로만 유지.
> **정정 (2026-06-22, Code Generation Q1=A)**: 초안의 **PyMuPDF(fitz)는 AGPL-3.0**라 "프로덕션·공개 모바일 웹"에 전파 위험 → **permissive 스택으로 대체**: **`pypdfium2`(Apache-2.0/BSD-3, PDF 렌더) + `pdfplumber`/`pdfminer.six`(MIT, 텍스트·rect·캡션 레이아웃)**. 알고리즘(내장 이미지 객체 + 캡션 근접 매칭 + page-crop)은 동일.
- **근거**: 내장 이미지 객체 + 캡션("Figure N"/"Table N") 근접 영역 크롭을 **CPU·ML 없이** 수행. permissive 라이선스, 오프라인 배치·$1600 전역 상한에 적합. distinct 논문×버전 1회(BR-22)라 처리량 bounded.
- **대안**: ~~PyMuPDF(AGPL — 기각)~~; 레이아웃 분석 ML 모델(pdffigures2[Java]/deepfigures[GPU]) — 검출 정밀도 우수하나 컴퓨트·운영 복잡도↑.
- **전환 비용**: 낮음 — 추출은 `AssetExtractor` 뒤 추상화. 정밀도 부족 시 차기 사이클 ML 검출로 교체(재추출은 NEW/CHANGED 재처리로 흡수).

## TD-12 — doc-model 구조화 추출: **arXiv HTML 결정적 파싱(표=데이터·수식=LaTeX) + 그림=HTML/e-print 그래픽**, PDF 크롭은 최후 폴백 (재검토 2026-06-23, D1/D8)
> **재검토 사유**: 기존 결정(표=PDF 크롭)은 표를 **이미지**로 박제 → 텍스트 에이전트·요약에 표 숫자가 깜깜이(근거형성이 표 충실도에 의존). doc-model 피벗에서 **표를 데이터로 승격**(D8).
- **근거**: 표/수식은 소스 HTML에 **데이터로 존재**한다. ar5iv/native HTML의 `<table class="ltx_tabular">`에서 **행/열(rows/cols) 구조 결정적 추출**(스파이크: 표 보유 시 전부 `ltx_tabular`). 수식은 `<math>`(MathML, HTML 보유분 94%) → **LaTeX 변환**(TD-16). 그림은 HTML `<img>` 또는 e-print(`/e-print/{id}`) tarball의 `\includegraphics` 그래픽 직접 취득(**원본 화질**) → **webp 정규화(TD-13) 유지**, doc-model이 `assetId`로 참조. 커버리지: HTML(native+ar5iv) 90%(Q1 스파이크).
- **표=PDF 크롭 폐기(D8)**: 표 이미지는 텍스트 에이전트에 깜깜이; LLM 추출도 금지(표 숫자 환각, D1) → **결정적 HTML 파싱만**.
- **폴백 사다리(Q6)**: `native HTML → ar5iv → e-print LaTeX → (최후) PDF 파싱(TD-11)`. HTML 전무 ~9%에서만 PDF 단계 발동; 그때 표가 크롭으로만 잡히면 webp 이미지로 두되 **주 표현은 데이터**.
- **대안**: ~~표=PDF 크롭(기존 TD-12 — 기각, D8)~~; LaTeX→이미지 TeX 컴파일(복잡·비용 과다); LLM 표 추출(환각 — 기각 D1).
- **전환 비용**: 중. 표 경로가 PDF 크롭 → HTML 파서로 전환(신규 `DocModelParser`, TD-16). 그림·webp·저장(TD-13/14/15)은 불변 재사용.

## TD-16 — doc-model HTML 파서 스택: **lxml/BeautifulSoup(HTML·표) + MathML→LaTeX 변환** (피벗 2026-06-23, D1)
- **근거**: 결정적 파싱(**LLM 추출 금지**, D1). HTML/XML = **`lxml`**(빠름·견고, XPath로 `ltx_*` 클래스 타겟) + 보조 **`BeautifulSoup`**(관용 파싱·구조 손상 내성). 표 `ltx_tabular`/`<table>` → rows/cols + colspan/rowspan 보존. 수식 `<math>`(MathML) → **LaTeX 변환**(예: `mathml-to-latex`/XSLT류, permissive). 그림 참조 → `assetId` 매핑(기존 자산 연결, 재추출 0). 전부 결정적(동일 HTML→동일 doc-model, P7).
- **입력 보안**: 외부 HTML = **파싱 공격 표면** → 안전 파서·**엔티티 확장/외부 DTD 차단**·문서 크기 상한(billion-laughs 가드, TD-15 정신 상속). 외부 fetch는 fail-closed(BR-18)·타임아웃(RES-9)·SSRF 방어 상속.
- **대안**: LLM 추출(거부 — 표 숫자 환각 D1); headless 브라우저 렌더(과중·비결정성); 표=PDF 크롭(D8 기각).
- **전환 비용**: 낮~중. 신규 의존성(permissive)·신규 `DocModelParser` 컴포넌트. 파서 라이브러리 핀·MathML 변환 정확도 임계는 NFR Design.

## TD-13 — 이미지 포맷·정규화: **WebP 재인코딩 + 치수/픽셀 상한 + 메타데이터 스트립** (Q3=A)
- **근거**: 모든 자산을 안전 디코더로 **재인코딩(WebP)** — 모바일 대역폭 절감 + 원본 바이트 비서빙(보안 TD-15). 최대 치수·총 픽셀 상한(decompression-bomb 가드), EXIF/메타 스트립. 구체 수치(해상도·DPI·상한·품질)는 NFR Design.
- **대안**: 원본 포맷 보존(재인코딩 없음) — 보안·대역폭 불리.
- **전환 비용**: 낮음(인코딩 파라미터).

## TD-14 — 자산 저장: **S3 별도 prefix/버킷(private·SSE) + 매니페스트/메타 = 공유 RDS PostgreSQL** (Q5=A)
- **근거**: 바이너리는 기존 S3(TD-7) 자산 prefix(공개 차단 SEC-9·at-rest SEC-1), 매니페스트/자산 메타는 **공유 RDS PostgreSQL**(U3/U4 계정·라이브러리, U7 용어집 자산) — 읽기 측(U7)이 RDS 조회 후 서명 URL 발급(인셉션 Q3=A). **신규 스토어 0.**
- **대안**: 매니페스트도 S3(JSON) — RDS 미사용. U7 조회·갱신 일관성에 불리.
- **전환 비용**: 낮음(포트 `AssetStorePort` 뒤). RDS 스키마·마이그레이션은 Infra Design.

## TD-15 — 이미지 보안 재인코딩(외부 소스 파싱 방어): **안전 디코더 경유 강제** (Q3=A 보안 측)
- **근거**: 외부 소스(arXiv 그래픽/PDF) 이미지는 **파싱 공격 표면**. 신뢰 디코더(예: Pillow/안전 옵션)로 재디코드·재인코딩, 치수/픽셀 상한으로 decompression bomb 차단, 메타 스트립. **원본 바이트를 그대로 저장·서빙하지 않는다.** 외부 fetch는 기존 fail-closed(BR-18)·타임아웃(RES-9) 상속(SSRF/지연 방어).
- **대안**: 원본 패스스루 — 위험(거부).
- **전환 비용**: 낮음.

---

## 비용·상한 주석 (NFR-C1)
- **NFR-C1 월 상한 = $1600/월**(2026-06-16 팀 결정 — 팀 AWS 크레딧 전액). **시스템 전역 상한**: U1 임베딩+스토리지뿐 아니라 전 유닛 AWS 지출(Bedrock 임베딩·U2 Bedrock LLM 근거화·OpenSearch·RDS·컴퓨트·S3) 합계가 $1600/월 이내. U1은 그 슬라이스 하나이며 **U6.CostGuardCircuitBreaker가 시스템 상한 강제**(80% 경보/100% 전 저하). 임베딩 1회(시드) 비용은 디덥(BR-4)·본문 크기 정책(BR-21)으로 통제.
- _주의(팀 확인): $1600이 일회성 크레딧 풀이면 런웨이=풀÷월지출; 월 한도 자체는 지시대로 $1600._

## 결정 완료(팀, 2026-06-16) & 후속
- ✅ **TD-4 스토어 = OpenSearch**(대안 Aurora pgvector / S3 Vectors+동반 기각) — [전역].
- ✅ **TD-3 = cross-lingual**(cross-lingual 질의 가정 확정) — [전역].
- ✅ **BR-1 = 엄격 OA 라이선스 검증**(재배포 가능 라이선스만; 미표기/불가 NON_OA 배제).
- ✅ **NFR-C1 = $1600/월**(시스템 전역).
- ✅ **FD 문서 규약 = 완전 추상**(FD는 구체 모델/차원/스토어/큐 미기재; NFR docs가 단일 진실 원천).
- 후속(보류): 유닛별 비용 배분 · 리전/배포 타깃(Infra) · CI 스캔 파이프라인(NFR Design) · $1600 크레딧 풀 vs 월 한도 런웨이 확인.
