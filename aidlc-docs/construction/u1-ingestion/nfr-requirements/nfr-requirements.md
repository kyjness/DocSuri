# nfr-requirements.md — U1 Ingestion 비기능 요구사항 (프로덕션)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U1 Ingestion · **일자**: 2026-06-16
**근거**: FD 산출물(프로덕션) · 계획서 프로덕션 답변 배너 · `requirements.md`
**고도**: NFR 목표 + 스택 종류. 리전/IaC/CI-CD/배포/복원력 테스트는 Infra/NFR Design 보류(NS-1).
**스코프**: 단일 프로덕션 트랙(데모 트랙 폐기).

---

## 0. U1 Corpus NFR 우선 적용 개정 (2026-06-26)

> **우선순위**: 본 섹션은 2026-06-26 U1 Corpus 재인셉션(FR-6, FR-18, NFR-C1, QT-9)을 반영한 최신 NFR Requirements다. 아래 §1~§11의 5년 arXiv-only, Cohere v3, section/full-text chunking, lazy DocModel 설명과 충돌하면 **본 섹션을 우선한다**.

### 0.1 확장성·처리량

- **phase-1 범위**: 최근 AI/ML 1년, OA/인덱싱 허용 라이선스, 명시적 build budget 안에서만 eager Corpus를 구축한다. 5년/전체 AI/ML 확장은 별도 backfill phase다.
- **source fan-out**: arXiv, Semantic Scholar, OpenAlex를 source별 job과 watermark로 분리한다. 한 source의 장애·쿼터가 다른 source의 watermark를 전진/정체시키면 안 된다.
- **GROBID 처리량**: Semantic Scholar/OpenAlex PDF는 containerized internal GROBID 처리량을 별도 병목으로 본다. source fetch 동시성, GROBID 동시성, embedding batch 동시성은 각각 독립 quota를 갖는다.
- **index generation**: DocModel 기반 index generation은 active alias 밖에서 bulk write하고, QT-9와 smoke check 통과 후 alias cutover한다. 기존 active index는 rollback window 동안 유지한다.
- **DocModel 완성형**: phase-1 DocModel은 `fullText` 전문 텍스트 투영본과 `sections[].blocks[]` 멀티모달 구조를 함께 가져야 한다. 구조 블록은 paragraph/table/formula/figure/list/code를 보존하고, 이미지는 JSON에 base64/URL로 넣지 않고 `AssetRef`로 `assets/` 객체를 참조한다.

### 0.2 성능·최신성

- U1은 비동기 워커이므로 사용자 API P50/P95 SLA는 N/A다. NFR 목표는 **backfill 수렴, incremental freshness, active index 무손상**이다.
- source별 incremental target은 "마지막 성공 watermark 이후만 처리"다. 전량 재스캔 + dedup 의존은 비용 상한 위반 위험 때문에 기본 경로가 아니다.
- DocModel 생성은 phase-1에서 eager지만, 비용 게이트가 OPEN이면 새 item은 보류/backfill queue로 넘어가고 기존 검색/열람은 active generation을 계속 사용한다.

### 0.3 신뢰성·복원력

- retry/DLQ stage는 `source_fetch`, `license_validate`, `grobid_extract`, `docmodel_validate`, `chunk`, `embed`, `index_write`, `artifact_store`를 구분한다.
- DLQ reprocess는 원래 canonical pipeline으로 재진입한다. 별도 보정 경로를 만들지 않는다.
- partial index generation은 alias 전환 금지다. `(paperId, version)` 불일치, 누락 DocModel block reference, DocModel schema validation 실패는 cutover blocker다.
- source별 watermark는 해당 page/item이 committed, retry scheduled, 또는 DLQ routed 된 뒤에만 전진한다.

### 0.4 비용

- **hard cap**: 계정/app 월 budget은 현재 CDK의 AWS Budget과 동일하게 **$1600/month**를 상한으로 둔다. U1 Corpus는 이 안의 별도 cost line이다.
- **phase-1 build budget**: U1 job은 per-run budget guard를 가져야 하며, 초과 시 후순위 item을 보류/backfill로 이월한다. 무제한 eager build는 금지한다.
- **계측 단위**: source fetch count, GROBID page/document count, DocModel count, chunk count, embedding token/vector count, OpenSearch bulk write count, S3 stored bytes, DLQ count를 별도 metric으로 낸다.
- **비용 저하**: 비용 circuit OPEN 시 신규 Corpus 확장/backfill만 멈춘다. active search index와 이미 저장된 DocModel read path는 제거하지 않는다.

### 0.5 보안·데이터 보호

- raw PDF는 transient input이다. Semantic Scholar/OpenAlex PDF와 arXiv PDF fallback은 GROBID/추출 처리 후 저장하지 않는다.
- GROBID는 internal-only로 둔다. 외부 공개 엔드포인트, 사용자 업로드 PDF 처리, raw PDF 다운로드는 범위 밖이다.
- S3 artifact는 private + SSE + TLS를 유지한다. 저장 허용 대상은 normalized FullText, DocModel JSON, assets, generation manifest, source provenance다. DocModel JSON에는 이미지 바이트, presigned URL, raw PDF object reference를 넣지 않는다.
- 외부 HTML/XML/TEI는 size limit, entity expansion/DTD 차단, schema validation, sanitize를 거친다.

### 0.6 관측성

- U1 실패 신호는 `ObservabilityHub.emitMetric`/`emitLog`로 라우팅한다. `emitFailureSignal`은 U1 내부 명칭일 뿐 포트 계약이 아니다.
- 필수 metric: source별 watermark lag, source fetch error rate, GROBID failure rate, DocModel validation failure, embedding spend, generation cutover status, DLQ backlog, reprocess success/failure.

### 0.7 PBT/QT-9

- Hypothesis 기반 generator는 source record 중복/순서 섞기, DOI/arXiv/title-key 결측, version 변경, block id 누락, malformed DocModel, retry/DLQ replay를 포함해야 한다.
- blocking invariant: multisource dedup idempotency, source watermark monotonicity, `(paperId, version)` consistency, DocModel `fullText` + multimodal block schema roundtrip/negative validation, index record blockRef existence, AssetRef object existence, retry/DLQ idempotency, raw PDF non-storage.

---

## 1. 확장성 (Scalability)
- **코퍼스 규모**: phase-1 슬라이스 — cs.LG·cs.AI·cs.CL·cs.CV·stat.ML × 최근 1년. 최근 5년은 Phase 7 backfill 확장 범위다. 아키텍처는 NFR-S1 저(低)천명대 사용자까지 무재설계 확장.
- **시드 빌드(US-I1)**: OAI-PMH 하베스트(`set=cs`, resumptionToken)로 대량 수집(NFR Q2=B). **시간 단위 소요 허용**(준비 작업, 실시간 아님; Q10).
- **워커 확장(Q11=B)**: fetch/parse/embed **병렬**, **인덱스 쓰기는 직렬화**(단일 writer 계약·FD BR-13 REBUILD_LOCK 유지). 동시성은 arXiv 쿼터(RES-8) 내 보수적.

## 2. 성능 · 최신성 (Performance / Freshness)
- **U1은 비동기 워커 — NFR-P1(P50<3s) N/A**(API 대상).
- **최신성/RPO(RES-2)**: 일 1회 증분(Atom API), RPO=마지막 인제스천 시점, 재구축 가능 자산(별도 백업 없음)(Q13).
- **배치(Q12)**: 임베딩 배치=embed 호출 처리량 최적화일 뿐 **커밋은 논문 단위 유지**(FD Q8/BR-7). 배치/페이지 크기 보수적(쿼터/타임아웃 내).

## 3. 가용성 · 신뢰성 (Availability / Reliability)
- **U1 가용성**: NFR-A1(99.5%)는 API 대상; 워커는 "복구·재시도·정체 없음"(NFR-R1, RES-7/9)으로 표현(SLA 아님).
- **의존성 격리 수치(RES-9, FD AS-4 확정, Q14=A)**: 외부 호출(arXiv/오브젝트 스토리지/임베딩 게이트웨이/벡터 스토어) **타임아웃 ~10s**, **재시도 최대 5회**, **지수 백오프(기본 1s·배수 2·지터)**, 서킷 개방 임계 정의. **수렴 검증**: 엔벨로프 × 단일 워커 쓰기 직렬화 × arXiv 최소 간격이 시드 빌드 시간 예산(시간 단위)에 수렴, 쿼터 미위반. (Infra 실측 재조정.)
- **부분 인덱싱 금지(NFR-R1)**: 논문 단위 원자성(BR-7) + INV-1 커밋 순서.

## 4. 비용 (Cost) — NFR-C1
- **임베딩 비용 동인**: cross-lingual 임베딩(Cohere Embed Multilingual v3, Bedrock) 토큰 과금(전문 청킹 = 논문당 다중 청크). 디덥(BR-4)으로 재처리 재임베딩 0; 본문 크기 정책(BR-21)으로 청크 폭주 통제.
- **텔레메트리**: 호출수/토큰/배치 카운트 계측 → U6 비용 텔레메트리(NFR-C1 RES-11(a) 신호 공급).
- **NFR-C1 월 상한 = $1600/월(확정, 2026-06-16)** — 팀 AWS 크레딧 전액, **시스템 전역**(전 유닛 합계). 기존 $300 제안값 대체(NFR-S1이 규모별 재설정 허용). U1 임베딩+스토리지는 그 슬라이스; **U6.CostGuardCircuitBreaker가 시스템 상한 강제**. 유닛별 배분/세부 산정은 Infra Design.

## 5. 보안 (Security)
- **SEC-1**: at-rest 암호화 + TLS — RDS/OpenSearch/S3 관리형 암호화·전송 TLS(NFR Q17=A).
- **SEC-5**: 인제스천 데이터 입력 검증·새니타이즈(BR-19).
- **SEC-9**: OA 전문 오브젝트 스토리지 **공개 차단**(BR-20) + 일반화 에러.
- **SEC-10(공급망)**: 락파일 + 의존성 취약점 스캔(SCA) + SBOM 생성 + 베이스 이미지 다이제스트 핀(`:latest` 금지). "무엇을 산출/핀"은 본 단계; 스캔 **CI 실행**은 NFR Design 보류.
- **SEC-15**: 모든 외부 호출 fail-closed(BR-18).

## 6. 관측성 (Observability) — NFR-O1
- 구조화 로깅(타임스탬프·요청/잡 ID·레벨, PII/시크릿 차단 SEC-3) + 메트릭 — **라이브러리는 언어(Python) 따름**.
- **워커→U6.ObservabilityHub 전송 채널**(`emitFailureSignal`, BR-17): 독립 워커(DQ1)이므로 이벤트 백본 전송. **구체 전송(이벤트 버스)은 U6 NFR Requirements[전역]/Infra로 보류** — 본 단계는 처분만 명시.

## 7. 유지보수성 (Maintainability)
- **모노레포 `ingestion/`**(UQ2=A) + Python 표준 도구(uv 또는 poetry) + 락파일(SEC-10).
- **PBT**: Hypothesis(Q8=A) — P1~P6 속성(business-rules §3) 도메인 제너레이터·shrinking·시드 재현성.

## 8. Usability — N/A
- U1은 비동기 워커, 사용자 표면 없음. OP CLI/런북 인체공학은 Operations(AS-5).

## 9. VectorSpec 확정값 [전역]
- **Cross-lingual 임베딩(Cohere Embed Multilingual v3, Bedrock) · 1024 차원 · 코사인 거리.** 한국어·영어 질의를 영어 코퍼스와 동일 공간 매핑(TD-3). U1 writer ↔ U2 reader 동일(불변식). 소유=공유 임베딩 게이트웨이 레이어(UQ5=A); U1(빌드 #1) PIN; 후속 유닛 재결정 없음(NS-5).
- **가정(팀 확인)**: 질의 언어 한국어/혼합 → cross-lingual; 영어 전용이면 Titan V2 대안. **QT-2 평가셋에 한국어 질의 포함**해 검증.
- **ANN 호환 게이트**: 선택 스토어(OpenSearch k-NN) 인덱스가 1024차원·코사인 지원 확인(domain-entities §8 / business-rules §6 동일 공간 불변식).
- **전환 비용**: VectorSpec 변경 = 전체 코퍼스 재임베딩(수십만) → 사실상 단방향.

## 10. 추적성
- NFR-C1($1600 확정·시스템 전역; 규모 증가 시에만 NFR-S1 재검토)·NFR-S1·NFR-R1/O1 · RES-2/7/8/9 · SEC-1/5/9/10/15 · QT-4 · C-5(AWS) · UQ2/UQ5 → 위 §1~9 + tech-stack-decisions.md.
- **FR-17(멀티모달 자산)** → 아래 §11 + TD-11~15.

---

## 11. 멀티모달 자산 추출 NFR (FR-17 — 표시 전용, 2026-06-22 확장)

> 근거: U1 FD §6/§7 · NFR 계획 Q1~Q7=A. **표시 전용** — 인덱싱/임베딩 NFR(§1~4·§9 VectorSpec) **불변**. 자산은 검색 비대상.

### 11.1 성능 · 처리량
- **온라인 SLA 무관**: 추출은 인제스천 워커(오프라인 배치) — NFR-P1 N/A(§2와 동형).
- **추출 컴퓨트(Q4=A)**: 기존 워커 인라인(per-paper, NEW|CHANGED만 — BR-22). **ML/GPU 없음**(TD-11 PyMuPDF 휴리스틱) → CPU 배치. 시드 재구축(수십만)은 자산 추출이 per-paper 처리시간을 더하나 **인덱스 경로와 분리(best-effort)**라 임베딩/쓰기 직렬화 병목과 독립. 동시성·런타임 타깃 수치는 Infra.
- **결정성(P7)**: 추출 도구 **버전 핀**(TD-9/10 다이제스트·락파일)으로 동일 입력→동일 자산.

### 11.2 보안
- **SEC-9**: 자산 바이너리 오브젝트 스토리지 **공개 차단**(TD-14), 노출은 단기 만료 서명 URL(읽기 측 U7). 매니페스트/메타도 owner 아닌 내부 필드 비노출.
- **SEC-1**: 자산 S3·매니페스트 RDS at-rest 암호화.
- **이미지 파싱 방어(TD-15)**: 외부 소스 이미지를 **안전 디코더로 재인코딩(WebP)** + 치수/픽셀 상한(decompression bomb 가드) + 메타 스트립. 원본 바이트 비서빙.
- **SSRF/외부 호출(BR-18·RES-9 상속)**: e-print/PDF fetch는 fail-closed·타임아웃·서킷.

### 11.3 복원력 (Q7=A)
- **추출 best-effort 비차단(BR-27)**: 추출·저장 실패는 논문 인덱싱(INV-1)·markIngested·워터마크 전진을 **막지 않음**. 실패는 `ASSET_EXTRACT_FAILURE`/`ASSET_STORE_FAILURE`로 관측·재시도(BR-17 경로 재사용).
- **타임아웃·서킷**: 추출·소스 fetch에 RES-9 패턴 적용. 수치는 NFR Design.

### 11.4 비용 (NFR-C1, Q6=A)
- **bounded**: distinct 논문×버전 1회 추출(디덥 BR-22). ML 모델 없음(TD-11) → CPU·S3 스토리지 위주. **기존 $1600 시스템 전역 상한 내 흡수**, U6.CostGuard 강제.
- **텔레메트리**: 자산 추출/스토리지 라인을 비용 텔레메트리에 별도 계상(Infra 비용표에 자산 라인 추가).

### 11.5 유지보수성
- 추출은 포트(`AssetExtractor`/`AssetStorePort`) 뒤 추상화 → TD-11(휴리스틱)→ML 교체가 국소(차기 사이클). PBT P7/P8(business-rules §7.2)는 Hypothesis(TD-8).
