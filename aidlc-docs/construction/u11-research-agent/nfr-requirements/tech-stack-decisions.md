# U11 Research Agent — Tech Stack Decisions (ADR)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**형식**: ADR(결정·근거·대안·전환 비용). `[전역 계승]`=시스템 전역 PIN(재결정 아님). `[게이트]`=아키텍처 게이트(`docmodel-fulltext-index-pivot`) 의존(U1/U2/infra 조율). `[열림]`=실험/평가 이연(미확정).
**근거**: 계획서 **Q1~Q16 전부 A** + U7·U2·U3 tech-stack 선례.

---

## TD-RA-1 [전역 계승] — 런타임 · 웹 프레임워크
- **결정**: Python · **FastAPI**(backend 모듈형 모놀리스 app-shell). async I/O·pydantic v2(shared/python)·자동 OpenAPI.
- **근거**: 전역 계승(U2/U3/U7). 다논문 fan-out·외부 대기 중첩에 async 적합.

## TD-RA-2 [전역 계승] — LLM 게이트웨이
- **결정**: **AWS Bedrock**, **U6 게이트웨이 경유**(SEC-11·비용·관측 일원화).
- **근거**: 전역 계승. 모델 호스팅·과금·레이트리밋 단일화.

## TD-RA-3 — 모델 바인딩 (Q1=A)
- **결정**: **논문별 근거 추출 = Claude Sonnet 4.6**(`claude-sonnet-4-6`) — AI/ML 전문에서 주장·방법·결과수치·한계 충실 추출. **교차확인 정렬·포맷 = Sonnet 기본**, 단순 포맷 단계는 Haiku 4.5(`claude-haiku-4-5`) 강등 가능(튜닝). 사용자 모델 선택기 비노출.
- **근거**: U7 선례(요약=Sonnet) 정합 — 추출 충실도가 근거화 통과율·신뢰를 좌우. 비용은 캐시·K 상한으로 bound.
- **전환 비용**: `model/promptVersion`이 캐시 키 일부 → 모델 변경=키 변경(자동 재생성). 낮음.

## TD-RA-4 — Bedrock 스트리밍 호출 (Q2/Q3=A)
- **결정**: **스트리밍 API**(Converse stream / `InvokeModelWithResponseStream`), boto3 async 래핑 → **버퍼-검증-스트리밍**(U6 근거화 통과분부터 노출). 진행상태 전송 = **SSE 우선 + 폴백 폴링**.
- **근거**: NFR-P5(다논문 수 초~분 → TTFB·진행상태). U7 BR-S8 계승.
- **대안**: 비스트리밍(TTFB 악화). 채택 안 함.

## TD-RA-5 — 세션·결과 스토어 (Q4=A)
- **결정**: **RDS PostgreSQL** — `ResearchSession`·`ConversationTurn`·`ResearchResult`(owner-scoped 관계·트랜잭션·백업). 큰 근거표 본문은 **RDS JSONB 또는 S3 참조**(크기 임계 — NFR Design).
- **근거**: U7 용어집·U3/U4 자산과 동형. 신규 인프라 0.
- **대안**: S3만(목록/쿼리 불리)·Redis(영속/백업 약). 채택 안 함.

## TD-RA-6 — 첨부 원본 스토어 (Q5=A)
- **결정**: **S3(owner-scoped, SSE-KMS)** + 형식/크기 한도. 무해화 후 doc-model 파이프라인 재사용 파싱(role=`query_context`). 무기한 보관 + 삭제 제어(`deleteAttachment`).
- **근거**: 대용량·재취득 불가 사용자 자료. doc-model 자산 저장 패턴 동형. 한도 수치=NFR Design.

## TD-RA-7 — 분석 결과 캐시(영구+핫) (Q6=A)
- **결정**: **S3/RDS(영구) + ElastiCache Redis(핫, 짧은 TTL) 2단**. 키 = immutable `AgentCacheKey`(정규화 질의·모드·첨부 해시·코퍼스 스냅샷·model/promptVer·persona?). read-through·write-through. **단일-턴 다논문 분석만 캐시**(멀티턴 대화는 세션 영속으로 별도).
- **근거**: U7 TD-S5 계승. 중복 호출 0콜 → 비용·지연 방어. 버전 변경 무효화.
- **세부 이연**: TTL·라이프사이클=Infra.

## TD-RA-8 — 긴 다논문 분석 비동기 잡 (Q2=A)
- **결정(형태)**: **3밴드** — 소규모(동기 스트리밍) / **대규모(비동기 잡: SQS 큐 + Agent 워커, 폴링→캐시 히트)** / OVER_CAP(거절·안내). U7 잡 패턴(TD-S9) 재사용.
- **근거**: 다논문 fan-out LLM 다중 호출(수십 초~분) → 동기 시 게이트웨이 타임아웃(~29s) 하드 실패. 대다수 질의는 동기 유지.
- **배포·게이트**: Agent 워커 = 별도 배포(Infra). 잡도 동일 근거화/기권·멱등(캐시 히트). **임계 수치(K·토큰)=NFR Design/튜닝.**

## TD-RA-9 — 후보 검색 (FD Q2 / NFR 정합)
- **결정**: **U2 검색 재사용** + **bounded 다중쿼리(A+)**(질의·첨부 분해→여러 번→합집합·PaperId 디덥). 출력 최소 `paper_id`(+score); **block_id locator는 권장 옵션**(granularity 종속).
- **근거**: 검색 단일 권위(U2) 유지·다양성·별도 검색 엔진 신설 회피. U2 다중쿼리 진입 vs U11 반복 호출=NFR/Code.

## TD-RA-10 — 근거화 (FD Q7)
- **결정**: **U6 단일 근거화 공유 계약 소비**(검색 enforce + 문서충실도 통일). U11은 정형화·verdict 매핑만(재구현 금지)·항목별 기권. **U7 `AnchorVerdict`도 동일 계약 이관**(확정·blast-radius=배포 U7).
- **근거**: 단일 권위(INV-U11-2)·날조 0(QT-8). 형상=`shared/ports.md` 확정 시 동기화.

## TD-RA-11 [게이트][열림] — 색인 granularity + locator (Q8=A 열어둠)
- **결정**: **미확정** — document/section/block dense(+lexical BM25) 후보, **recall·비용 평가(GQ1)로 결정**. block_id locator는 종속. 비용 방향: block dense=k-NN RAM 최다(#120), block BM25=싸게 locator.
- **근거**: 실험 전 확정 시 선택지 축소. 전문 통합 인덱스·eager doc-model=아키텍처 게이트(U1/U2/infra 조율).

## TD-RA-12 [전역 계승] — 속성 기반 테스트 (Q13=A)
- **결정**: **Hypothesis**(Python). PBT-RA1~6(union 라운드트립·기권 안정성·owner isolation·캐시 키·부분결과·출처 실재).
- **근거**: 전역 PBT 정책 계승.

## TD-RA-13 — real-first 테스트 전략 (Q15=A, U7 TD-S12 계승)
- **결정**: **Production Mock Adapter 미구현.** 출하 = 포트 + 실 어댑터 단일본. 단위=테스트 픽스처/Stub(허용·테스트 코드)+PBT; 통합=실 의존성(CI/Infra). **프런트만 계약(shared DTO) mock 픽스처로 병렬**.
- **전환 비용**: 포트(의존성 역전) 유지 → 어댑터 교체 용이. 낮음.

## TD-RA-14 — shared DTO 계약 승격 (Q16=A, U7/U8 선례)
- **결정**: **`shared/dtos/research_agent`(PROVISIONAL) 승격 + 별도 shared PR**. `AgentResponse` 5종 union·`EvidenceTable`/`CrossCheckTag`·세션/턴·`AgentCacheKey`·`StructuredLocator`. 드리프트 가드·U6 근거화 계약 정합 대상.
- **근거**: 프런트·U6·U2 정합. U4/U7 승격 선례.

## TD-RA-15 [열림] — 모드 B 외부 학술 API (Q14=A 차기)
- **결정**: **차기 사이클(미빌드)** — novelty(FR-23·Q4=A) 구현 시 외부 학술 메타데이터 API·쿼터·캐시(U8 패턴) 선정. 본 사이클 seam만.

---

## 정합 확인 (전역/위임/게이트)
- **[전역 계승]** Python·FastAPI·Bedrock·RDS·Redis·S3·SQS·Hypothesis·NFR-C1 — U11 재결정 아님.
- **[U6 위임]** 인증/인가·레이트리밋·근거화(통일 계약)·비용 게이트·관측 — 포트 소비(재구현 없음).
- **[게이트]** 전문 통합 인덱스·eager doc-model·근거화 U6 통일·DF-6(각주/메타) — `docmodel-fulltext-index-pivot` 승인 + U1/U2/U7/infra 조율.
- **[열림]** granularity(GQ1)·랭킹(GQ2)·K/임계·모드 B API — 실험/NFR Design/차기.
- **신규 DTO 계약** `shared/dtos/research_agent`(PROVISIONAL) — 별도 shared PR 승격(TD-RA-14).
