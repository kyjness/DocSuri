# nfr-requirements.md — U1 Ingestion 비기능 요구사항 (프로덕션)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U1 Ingestion · **일자**: 2026-06-16
**근거**: FD 산출물(프로덕션) · 계획서 프로덕션 답변 배너 · `requirements.md`
**고도**: NFR 목표 + 스택 종류. 리전/IaC/CI-CD/배포/복원력 테스트는 Infra/NFR Design 보류(NS-1).
**스코프**: 단일 프로덕션 트랙(데모 트랙 폐기).

---

## 1. 확장성 (Scalability)
- **코퍼스 규모**: FR-6 풀 슬라이스 — cs.LG·cs.AI·cs.CL·cs.CV·stat.ML × 최근 5년 = **수십만 건**(Q1=D). 아키텍처는 NFR-S1 저(低)천명대 사용자까지 무재설계 확장.
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
