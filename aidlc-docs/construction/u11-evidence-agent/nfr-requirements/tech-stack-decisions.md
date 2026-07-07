# U11 Evidence Formation Agent — Tech Stack Decisions (ADR)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U11 Evidence Formation Agent · **일자**: 2026-06-30
**형식**: ADR(결정·근거·대안·전환 비용). `[전역 계승]` = 시스템 전역 PIN(재결정 아님). 근거: FD 산출물 · nfr-requirements.md.

---

## TD-E1 [전역 계승] — 런타임 · 웹 프레임워크
- **결정**: Python · **FastAPI**(backend 모듈형 모놀리스 app-shell 기존 자산).
- **근거**: 시스템 전역 결정 계승(U2/U3/U7 사용 중). async I/O(Bedrock·OpenSearch·S3·RDS·SQS 외부 대기)·pydantic v2(shared/python) 정합·SSE 스트리밍 지원.
- **대안/전환**: 신규 프레임워크 = app-shell 재작성 비용. 채택 안 함.

## TD-E2 [전역 계승] — LLM 게이트웨이
- **결정**: **AWS Bedrock**(IAM·관측·비용 일원화). U6 게이트웨이 경유(SEC-11 레이트리밋·비용).
- **근거**: 전역 계승. 모델 호스팅·과금 단일화.

## TD-E3 — 모델 바인딩 (Agent 추론·추출)
- **결정**: **Claude Sonnet 4.6(`claude-sonnet-4-6`)** — Agent 추론(자율 Tool 호출) + DocModel 블록 근거 추출.
- **근거**: 다논문 교차확인·비교표 조립·멀티턴 맥락 유지 = 복잡 추론 필수 → Sonnet 선택. Haiku는 Agent 루프 자율성 부족(Tool 호출 품질 저하). 비용(§6)은 CostGuard 게이트로 관리.
- **대안**: Haiku(비용↓ but Agent 품질↓·날조 위험↑) · 사용자 선택기(세션 일관성·비용 예측 불가). 채택 안 함.
- **전환 비용**: 모델 ID 단일 상수 교체 → 낮음.

## TD-E4 — Bedrock 스트리밍 호출
- **결정**: **Converse API 스트리밍**(`boto3 bedrock-runtime` async 래핑) → **SSE 점진 전송**(BR-EV-6).
- **근거**: NFR-P6(Agent 실행 수십 초 → 스트리밍 TTFB 필수). 결과 확정 전까지 최종 claims 보류(INV-EV-3).
- **대안**: 비스트리밍(TTFB 악화). 채택 안 함.

## TD-E5 — 세션 · 턴 영속화
- **결정**: **RDS PostgreSQL**(기존 U3/U4/U7 자산). `evidence_sessions`·`evidence_turns` 테이블. (ownerId, sessionId) 인덱스로 소유자 격리(INV-EV-1).
- **근거**: 멀티턴 맥락(FR-36) + 소유권 격리 + 트랜잭션 필요. Redis(영속/백업 약함)·S3(쿼리/갱신 불리). RDS = 기존 자산 재사용(신규 인프라 0).
- **대안**: NoSQL(쿼리/갱신 불리·트랜잭션 약함). 채택 안 함.
- **전환 비용**: 스키마 마이그레이션 + 리포지토리 교체. 중간.

## TD-E6 — 비동기 잡 오프로드 (NFR-P6, BR-EV-6)
- **결정**: **SQS 잡 큐 + Agent 워커**(U7 TD-S9 패턴 계승). API가 복잡 요청 감지 → enqueue → `TurnPendingResult{ jobId }` 반환 → 클라이언트 폴링 `GET /api/evidence/jobs/{jobId}` → 워커 완료 후 DB write.
- **근거**: 다논문 Agent 실행(LLM 복수 호출, 60s+)은 게이트웨이 타임아웃(~29s) 하드 실패 → 비동기 필수. 단순 요청(소수 논문·첨부 없음)은 동기 SSE 유지(체감 무변경).
- **게이트**: `DOCSURI_EVIDENCE_ASYNC_ENABLED`(기본 OFF) · `DOCSURI_EVIDENCE_JOB_QUEUE_URL`. 미설정 시 async path abstain(기존 동기 경로).
- **대안**: WebSocket(연결 유지 비용·인프라 복잡도↑). 채택 안 함.
- **전환 비용**: SQS 큐 + 워커 배포 단위 추가(Infra slice — CDK). 중간.

## TD-E7 — 논문 검색 (PaperSearchTool)
- **결정**: **U2 OpenSearch 클라이언트 재사용**(U2 소유 vector store·U11은 dependency). 직접 OpenSearch client 호출(U2 HTTP API 경유 아님 — 동일 백엔드 내).
- **근거**: U2가 인덱싱·쿼리 소유 → U11은 소비자. 동일 모노레포 내 직접 클라이언트 호출이 레이턴시 최소(HTTP hop 제거). scope 분기(auto/explicit/mixed)는 U11 로직(BR-EV-2).
- **의존 계약**: `shared/vector-spec`의 `IndexRecord`. U11 재정의 금지.

## TD-E8 — DocModel 블록 읽기 (EvidenceDocModelTool)
- **결정**: **S3 read-only**(U1 단일 writer, U11 소비자). `paperId + recordRef` → S3 키 매핑 → `DocModelBlock[]` 읽기. 실패 → 해당 논문 건너뜀.
- **근거**: DocModel SSOT = U1. U11은 read-only 소비자(쓰기 금지). 실패 시 부분 허용(BR-EV-4 패턴).

## TD-E9 — 첨부 임시 처리 (AttachmentDocModelAdapter)
- **결정**: **임시 S3 업로드 → U1 DocModel 파이프라인 재사용 → 추출 후 즉시 원시 파일 삭제**. 추출 완료 DocModelBlock은 Agent 컨텍스트 내 메모리에만 유지.
- **근거**: C-1/INV-EV-4(첨부 영구 저장 금지). U1 파이프라인 재사용으로 구현 부담 최소화.
- **대안**: 별도 파싱 라이브러리(구현 비용↑·U1 파이프라인 중복). 채택 안 함.

## TD-E10 [전역 계승] — 속성 기반 테스트
- **결정**: **Hypothesis**(Python). PBT-EV-1~5(기권 안전성·소유권 격리·비노출·scope 격리·D5 라운드트립).
- **근거**: 전역 PBT 정책 계승.

## TD-E11 — real-first 테스트 전략
- **결정**: **Production Mock Adapter는 구현하지 않는다.** 출하 코드 = 포트 + 실 어댑터 단일본(Bedrock·OpenSearch·S3·RDS·SQS).
  - **단위 테스트**: **테스트 전용 Fixture/Stub 허용**(출하 어댑터 아님 — 테스트 코드) + Hypothesis PBT.
  - **통합 테스트**: 실 의존성 대상(자격증명/엔드포인트 = CI/Infra).
- **근거**: real-first(전역 정책). 단위 테스트 결정성·속도를 위해 픽스처 허용하되, mock을 출하 어댑터로 패키징 금지.
- **전환 비용**: 포트(EvidenceFormationPort·의존성 역전) 유지 → 어댑터 교체 용이. 낮음.

---

## 정합 확인 (전역/위임)

- **[전역 계승]** Python·FastAPI·Bedrock·RDS·S3·SQS·NFR-C1·Hypothesis — U11 재결정 아님.
- **[U6 위임]** 비용 게이트·관측·레이트리밋·인증/인가 — 포트 소비만(재구현 없음).
- **[U2 위임]** OpenSearch 인덱싱·벡터 검색 — U11은 소비자. 쿼리 형태만 결정.
- **[U1 위임]** DocModel S3 write·첨부 파이프라인 — U11은 read-only 소비자 + 파이프라인 재사용.
- **D5 FROZEN 계약** `shared/dtos/evidence.schema.json` + `shared/ports/EvidenceFormationPort` — U11 재정의 금지.
