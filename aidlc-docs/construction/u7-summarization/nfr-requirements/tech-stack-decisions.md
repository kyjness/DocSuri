# U7 Summarization — Tech Stack Decisions (ADR)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U7 Summarization · **일자**: 2026-06-19
**형식**: ADR(결정·근거·대안·전환 비용). `[전역 계승]` = 시스템 전역 PIN(재결정 아님). 근거: 계획서 15문 A.

---

## TD-S1 [전역 계승] — 런타임 · 웹 프레임워크
- **결정**: Python · **FastAPI**(backend 모듈형 모놀리스 app-shell 기존 자산).
- **근거**: 시스템 전역 결정 계승(U2/U3 사용 중). async I/O(Bedrock/S3/Redis 외부 대기)·pydantic v2(shared/python) 정합·자동 OpenAPI.
- **대안/전환**: 신규 프레임워크 = app-shell 재작성 비용. 채택 안 함.

## TD-S2 [전역 계승] — LLM 게이트웨이
- **결정**: **AWS Bedrock**(IAM·관측·비용 일원화). U6 게이트웨이 경유(SEC-11 레이트리밋·비용).
- **근거**: 전역 계승. 모델 호스팅·과금 단일화.

## TD-S3 — 모델 바인딩 (FD BR-S5 → 구체) — Q1
- **결정**: **요약 = Claude Sonnet 4.6(`claude-sonnet-4-6`)** · **번역 = Claude Haiku 4.5(`claude-haiku-4-5`)**. task가 자동 결정, 사용자 선택기 비노출.
- **근거**: 난해 AI/ML 코퍼스 요약 = 정밀 모델(Sonnet); 번역 품질은 모델보다 용어집(BR-S4)이 좌우 → 경량(Haiku). 설계 입력 §2.
- **대안**: 단일 모델(요약 품질↓) · 사용자 선택기(캐시 분할·혼란). 채택 안 함.
- **전환 비용**: `modelVer` 캐시 키 일부 → 모델 변경 = 키 변경(자동 재생성). 낮음.

## TD-S4 — Bedrock 스트리밍 호출 — Q2
- **결정**: **스트리밍 API**(`InvokeModelWithResponseStream` / Converse stream), boto3(bedrock-runtime) async 래핑 → **버퍼-검증-스트리밍**(BR-S8).
- **근거**: NFR-P2(첫 생성 수십 초 → 스트리밍 TTFB 필수). 근거화 통과분부터 노출.
- **대안**: 비스트리밍(TTFB 악화). 채택 안 함.

## TD-S5 — 요약 스토어(영구+핫) — Q3
- **결정**: **S3(영구 진실원본) + ElastiCache Redis(핫, 짧은 TTL)**. 키 = immutable `SummaryCacheKey`. 경로 예 `summaries/{paperId}/v{version}/{task}_{lang}_{persona}_{modelVer}_{promptVer}.json`. read-through(Redis→S3)·write-through.
- **근거**: 설계 입력 §11·기존 프로덕션 자산(신규 인프라 0). 부담 무시 수준(~2KB×30만≈600MB).
- **세부 이연**: Redis TTL·S3 라이프사이클 수치 = Infra.

## TD-S6 — 개인 용어집(P2) 영속화 — Q4
- **결정**: **RDS PostgreSQL**(기존 U3/U4 자산). per-user 구조화 소량·트랜잭션·owner 격리(SEC-8). `glossaryVer` 증가 트랜잭션 관리.
- **근거**: 사용자 데이터(관계형·owner 스코프·백업). accounts/library와 동형.
- **대안**: Redis(영속/백업 약함) · S3(쿼리/갱신 불리). 채택 안 함.
- **주**: 시드 도메인 용어집(P1 공유·고정)은 코드/구성 자산(스토어 아님).

## TD-S7 — 섹션/앵커 도출 — Q5 (FD Q6 바인딩)
- **결정**: **정규식·휴리스틱(헤딩 패턴) 코드 구현** — 헤딩/번호/Table·Figure 라벨 인식 → label + char span, 실패 시 span-only.
- **근거**: AI/ML arXiv 헤딩 규칙적·전문이 이미 정제 텍스트(재파싱 불필요)·신규 인프라 0·결정성(PBT-S5).
- **대안**: 외부 과학문서 파서(GROBID 등) = 무겁고 신규 인프라. 채택 안 함.

## TD-S8 — 토큰 예산 / map-reduce 임계 — Q8
- **결정**: **형태만** — 모델 컨텍스트 윈도우 기반 입력 토큰 예산 + 단일/맵-리듀스 분기 임계 + 입력 토큰 캡(아웃라이어 상한). **구체 수치 = Code-gen/튜닝**.
- **근거**: 기술/수치 이연 원칙. 분기 규칙·결과 동등성(통합 출력도 §3 스키마)만 확정.

## TD-S9 — 초장문 비동기 잡 — Q6 — **구현됨(#135, slice 5b)**
- **결정(개정)**: 3단계(BR-S6) — 단일 콜(동기) / **map-reduce(비동기 잡)** / OVER_CAP(거절). 비동기 잡 인프라(**SQS 요약 큐 + 요약 워커**)를 구현: API가 MAP_REDUCE 밴드에서 잡 enqueue→`PendingDTO` 반환→클라이언트 폴링, 워커가 map-reduce를 inline 실행(게이트웨이 타임아웃 회피)→STORE write-through→폴링 캐시 히트.
- **근거**: 긴 요약(LLM 3~5콜, 15~75s)은 동기 시 게이트웨이 타임아웃(~29s) 하드 실패 → 비동기 필수. 대다수 논문(~13K)은 단일/동기 유지(체감 무변경). **OVER_CAP은 부분요약 없이 거절**(모바일 결정).
- **배포·게이트**: 요약 워커 = **별도 배포 단위**(Infra — slice 6 CDK). 게이트 `DOCSURI_MAP_REDUCE_ENABLED`(맵리듀스)·`DOCSURI_SUMMARY_JOB_QUEUE_URL`(비동기) 기본 OFF → 미설정 시 MAP_REDUCE abstain(기존). 잡도 동일 근거화/기권(BR-S12). dedup·best-effort enqueue·멱등(캐시 히트).

## TD-S10 — 재현성 추출 — Q16(FD)
- **결정**: **정규식 힌트 + LLM 추출 병행** → `reproducibility{code, data}`. 정규식(github.com·"code available"·"dataset" 등) + LLM 문맥. 날조 링크는 근거화(BR-S7) 차단.
- **근거**: 정규식=high-precision 링크, LLM=문맥. 페르소나 최우선 신호.

## TD-S11 [전역 계승] — 속성 기반 테스트
- **결정**: **Hypothesis**(Python). PBT-S1~S5(캐시 키·정제·후치환·DTO 라운드트립·앵커 건전성).
- **근거**: 전역 PBT 정책 계승.

## TD-S12 — real-first 테스트 전략 — Q14
- **결정**: **Production Mock Adapter는 구현하지 않는다.** 출하 코드 = 포트 + 실 어댑터 단일본(Bedrock·S3·Redis·RDS).
  - **단위 테스트**: **테스트 전용 Fixture/Stub 사용 허용**(출하 어댑터 아님 — 테스트 코드) + Hypothesis PBT.
  - **통합 테스트**: 실 의존성 대상(자격증명/엔드포인트 = CI/Infra).
- **근거**: real-first(Q10/Q11). 단위 테스트의 결정성·속도를 위해 테스트 픽스처는 허용하되, 출하 어댑터로 mock을 패키징하지 않음.
- **전환 비용**: 포트(의존성 역전·MR-4 계약 스왑) 유지 → 추후 어댑터 교체 용이. 낮음.

---

## 정합 확인 (전역/위임)
- **[전역 계승]** Python·FastAPI·Bedrock·RDS·Redis·S3·NFR-C1·Hypothesis — U7 재결정 아님.
- **[U6 위임]** 비용 게이트·관측·레이트리밋·인증/인가 — 포트 소비만(재구현 없음).
- **신규 DTO 계약** `shared/dtos/summarization`(PROVISIONAL) — 별도 shared PR 승격(U4 선례).
