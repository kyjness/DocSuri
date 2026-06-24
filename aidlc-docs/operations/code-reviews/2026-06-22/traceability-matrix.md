# Traceability Matrix

Generated: 2026-06-22 06:49:34 UTC
Project: Unknown Project

## Summary

- Total Requirements: 62
- Total Stories: 33
- Total Units: 8
- Total Code Files: 318
- Total Tests: 0

## AIDLC Traceability Coverage

Complete traceability across all AI-DLC development layers:

**⚠ Layer 1: Requirements → Stories**
- 50/62 requirements traced to user stories (81%)

**✓ Layer 2: Stories → Units**
- 33/33 stories traced to units of work (100%)

**⚠ Layer 3: Units → Components**
- 6/8 units traced to logical components (75%)

**⚠ Layer 4: Components → Code**
- 43/73 implementation components traced to source code (59%)
  - 195 implementation files, 123 boilerplate files

**⚠ Layer 5: Code → Components**
- 38/195 implementation files traced back to components (19%)
  - 157 orphaned implementation files

## Coverage Gaps

- **SEC-10** (no_stories): Requirement '(공급망)' has no linked user stories
- **SEC-13** (no_stories): Requirement '감사(`AuditSink` 변경 연산 발행, 민감/내부 비노출) | D12/BR-L10 | (U6/ops 결선 예정)' has no linked user stories
- **NFR-X1** (no_stories): Requirement '핵심 흐름에 대해 가능 범위에서 WCAG 2.1 AA 지향; v1 차단 게이트는 아님(NFR-R* 우선으로 후순위).' has no linked user stories
- **NFR-M1** (no_stories): Requirement '모듈형 아키텍처, 문서화된 컴포넌트; 기술 스택은 Construction에서 선정.' has no linked user stories
- **SEC-2** (no_stories): Requirement '모든 네트워크 중간자(LB/API 게이트웨이/CDN)에 액세스 로깅. (SECURITY-02)' has no linked user stories
- **SEC-6** (no_stories): Requirement '최소 권한 IAM(문서화된 예외 없이는 와일드카드 액션/리소스 금지). (SECURITY-06)' has no linked user stories
- **SEC-7** (no_stories): Requirement '기본 거부(deny-by-default) 네트워크 구성; 공개 인그레스는 80/443만. (SECURITY-07)' has no linked user stories
- **SEC-14** (no_stories): Requirement '경보 + 모니터링; **추가 전용(append-only) 감사 로그**, 90일+ 보존. (SECURITY-14)' has no linked user stories
- **RES-2** (no_stories): Requirement '**RTO/RPO + DR (CQ4=E)**: 단일 리전, 멀티 AZ; **교차 리전 DR 없음**. 자동 암호화 DB 백업; **계정/검색 저장 메타데이터**에 대해 RPO ~24h 이내 허용, RTO는 IaC 재배포 + 복원으로 수 시간. **공유 arXiv 벡터 인덱스는 FR-6 인제스천 파이프라인에서 재생성 가능(rebuildable) 자산으로 취급' has no linked user stories
- **RES-3** (no_stories): Requirement '**변경 관리(CQ5=A)**: 기존 프로세스 준수 — **GitHub PR 리뷰 + git-flow(feature → develop → main) + GitHub Projects**. 새로 만들지 않음. (RESILIENCY-03)' has no linked user stories
- **RES-10** (no_stories): Requirement 'DR 전략 문서화(Backup & Restore, RES-2 기준): **교차 리전 페일오버 없음** — AZ 수준 복원 + 백업/인덱스 재구축 복구 절차(복원·재구축 런북). (RESILIENCY-11/13)' has no linked user stories
- **RES-12** (no_stories): Requirement '복원력 테스트 방식 — **NFR Design으로 보류**(RESILIENCY-14).' has no linked user stories

## Forward Traceability Matrix

| Requirement | Stories | Units |
|-------------|---------|-------|
| NFR-P1: (P50<3s) — **U2/U6 API 대상, U1 N/A**. | US-CG6, US-H1, US-S5 | U1, U2, U3, U5, U6, U7, U8 |
| NFR-A1: (99.5% 가용성) — API 대상; U1은 "복구·재시도·정체 없음"(NFR-R1, RES-7/9)으로 표현(SLA 아님). | US-A1, US-A2 | U3, U5, U6 |
| NFR-C1: (시스템 전역 $1600/월) | US-CG5, US-CG6, US-R3, US-S6 | U6, U7, U8 |
| NFR-S1: (~3,000 사용자·동시 ~50) | US-S1, US-S2, US-S3, US-S4, US-S5, US-S6 | U1, U2, U5, U6, U7 |
| NFR-P2: (체감 성능) | US-CG6, US-S5 | U5, U6, U7, U8 |
| RES-9: / NFR-R2 | US-CG5, US-CG6, US-I3, US-R2 | U1, U2, U6, U8 |
| QT-5: 요약/번역 근거화(날조 0·기권·앵커). U7 `GroundingValidator` 결정적 게이트 출력 표면 제공(평가 실행=U6/OP). | US-CG6, US-S1, US-S3, US-S6 | U1, U2, U5, U6, U7, U8 |
| SEC-1: at-rest 암호화 + TLS — RDS/OpenSearch/S3 관리형 암호화·전송 TLS(NFR Q17=A). | US-CG6 | U6, U8 |
| SEC-5: 인제스천 데이터 입력 검증·새니타이즈(BR-19). | US-D1 | U2, U5 |
| SEC-9: OA 전문 오브젝트 스토리지 **공개 차단**(BR-20) + 일반화 에러. | US-CG6, US-D7 | U2, U5, U6, U8 |
| SEC-10: (공급망) | _none_ | _none_ |
| SEC-15: 모든 외부 호출 fail-closed(BR-18). | US-D7 | U2, U5 |
| SEC-3: 구조화 로깅(requestId 상관)·**질의 원문/PII 로깅 정책 준수**. | US-A1 | U3, U5, U6 |
| NFR-U1: /U2(폰 우선·폰 목업) | US-CG6, US-D1, US-D4, US-H1 | U1, U2, U3, U5, U6, U8 |
| QT-2: (관련도) | US-CG6, US-D3 | U2, U6, U8 |
| QT-3: (신뢰성/저하) | US-CG6, US-D7, US-R2 | U2, U5, U6, U8 |
| QT-4: (PBT) | US-CG6 | U6, U8 |
| NFR-R2: 메타 스냅샷 가용성 격리(U2/인덱스 독립); rerun만 degrade | D5/BR-L5, D9/INV-L2 | `LibraryItemDTO.meta`, `SearchResultSetDTO` | US-CG5, US-D7, US-R2 | U2, U5, U6, U8 |
| SEC-8: 인가 위임(U3 `AuthorizationGuard` 단일 권위) + owner-scoping 백스톱 | D11, INV-L1 | `Principal`/`Action`/`AccountId`(U3 재사용) | US-A2, US-CG1, US-CG4, US-CG6, US-L1, US-L2, US-L3, US-S4 | U2, U3, U4, U5, U6, U7, U8 |
| SEC-13: 감사(`AuditSink` 변경 연산 발행, 민감/내부 비노출) | D12/BR-L10 | (U6/ops 결선 예정) | _none_ | _none_ |
| FR-1: 자유 텍스트 자연어 연구 의도를 주 입력으로 받는다. | 단일 질의 입력란; 최대 길이(제안: 500자)까지 허용·검증. | US-CG6, US-D1, US-H1 | U1, U2, U3, U5, U6, U8 |
| FR-2: 의도를 해석/확장하여 공유 AI/ML arXiv 벡터 인덱스에 대해 **시맨틱 검색**을 수행한다(하이브리드 lexical+vector 허용). | 대표 질의 세트에서 관련 논문이 상위 결과에 등장(평가셋으로 검증 — QT-2). | US-CG6, US-D2, US-H1 | U1, U2, U3, U5, U6, U8 |
| FR-3: 관련도순으로 정렬해 상위 N건을 빠르게 반환한다. | 상위 N건(제안: 20) 반환, 문서화된 관련도 점수순 정렬. | US-CG6, US-D3, US-H1 | U1, U2, U3, U5, U6, U8 |
| FR-4: 각 결과를 **폰 화면**에 최적화해 제시: 제목, 저자, 연도, arXiv ID, 초록 스니펫, 관련도 신호, arXiv 링크. | 360–430px 너비에서 가로 스크롤 없이 완전히 가독·조작 가능. | US-CG6, US-D4, US-H1 | U1, U2, U3, U5, U6, U8 |
| FR-5: **엄격한 근거화(strict grounding)**: 노출되는 모든 논문은 인덱스의 실재 레코드; AI 생성 텍스트(관련도 설명/요약)는 검색된 논문에서만 도출; 근거가 없으면 날조 대신 **기권(abstain)**("관련 논문 없음"). | 평가셋 전반에서 날조 논문/인용 0건; 코퍼스 밖 질의에 기권 경로 동작. (QT-1) | US-CG3, US-CG6, US-D5, US-D6, US-H1, US-R1, US-S1, US-S3 | U1, U2, U3, U5, U6, U7, U8 |
| FR-6: **인제스천 & 인덱싱 파이프라인**: arXiv API(오픈액세스 메타데이터+전문)에서 AI/ML 논문을 수집→청크→임베딩→벡터 인덱스 저장; 최신성 위해 스케줄 갱신. | **arXiv 슬라이스(제안: 카테고리 cs.LG·cs.AI·cs.CL·cs.CV·stat.ML; 기간 최근 5년; 규모 수십만 건)** 수집; **갱신 주기(제안: 일 1회)** 로 | US-CG6, US-I1, US-I2 | U1, U6, U8 |
| FR-7: **사용자 계정**: 공개 셀프 가입, 로그인, 로그아웃, 인증 세션. | 신규 사용자가 셀프 가입·로그인·세션 유지 가능; 자격증명은 SEC-12 준수. | US-A1, US-A2, US-CG6, US-H1 | U1, U2, U3, U5, U6, U8 |
| FR-8: **검색 저장**: 질의 저장, 목록, 재실행, 삭제(사용자별 비공개). | 저장 검색이 세션 간 지속, 소유자에게만 노출(SEC-8). | US-CG6, US-L1 | U4, U5, U6, U8 |
| FR-9: **라이브러리 저장**: 논문을 개인 라이브러리에 추가/삭제·목록. | 라이브러리가 사용자별 지속·비공개(SEC-8). | US-CG4, US-CG6, US-L2 | U3, U4, U5, U6, U8 |
| FR-10: 사용자별 **검색 이력**. | 최근 질의가 목록·재실행 가능, 사용자에게 비공개. | US-CG6, US-L3 | U2, U4, U6, U8 |
| FR-11: **빈 결과 & 실패 UX**: 빈 검색, 업스트림(arXiv/LLM/인덱스) 장애, 저하(degraded) 모드에 대한 명확한 구분 상태. | 각 상태가 구체적·비기술적 메시지 표시; 빈 화면·스택 트레이스 없음; 오류 시 fail closed·일반화된 프로덕션 에러(SEC-9, SEC-15, NFR-R1). | US-CG5, US-CG6, US-D6, US-D7, US-R2, US-S3, US-S6 | U2, U5, U6, U7, U8 |
| FR-12: **AI 요약(요약 액션) [U7]**: 검색 결과 카드에서 선택한 **단일 논문의 전문**을 페르소나 질문 기반 **구조화 요약**(핵심주장·기여·방법·결과·한계·재현성)으로 생성. 요약 *수준* 선택(전문가용/입문자용). 각 항목에 원문 근거 앵커(섹션·표·그림) 부기. | 선택 논문 1편에 구조화 요약 반환; 각 주장에 검증 가능한 원문 앵커("출처  | US-CG6, US-S1, US-S3, US-S5 | U1, U2, U5, U6, U7, U8 |
| FR-13: **한국어 번역(번역 액션) [U7]**: 선택한 논문의 **초록**을 한국어로 번역. 도메인 용어집(미번역 리스트 포함) 적용으로 전문용어 일관. | 초록 한국어 번역 반환; 용어집의 미번역 용어(모델명·약어)는 영어 유지; 사용자 용어 선호 저장 시 이후 일관 적용(SEC-8). 온디맨드(NFR-P2). | US-CG6, US-S2, US-S5 | U1, U5, U6, U7, U8 |
| FR-14: **요약/번역 개인화 [U7]**: persona 생성 변형(전문가용/입문자용)·표시 뷰 프리셋(전체/3줄/관점별)·용어집(P1 도메인 시드 + P2 개인 오버라이드). | persona는 논문당 최대 2벌 생성; 뷰 프리셋은 동일 출력의 **재생성 없는** 표시 변형; 개인 용어 선호가 사용자별 지속(SEC-8). 커뮤니티 공유 용어집(P3)·자유입력 p | US-CG6, US-S4 | U5, U6, U7, U8 |
| FR-15: **각주 트리 / 인용 그래프 [U8]**: 논문 상세보기 페이지에서 선택 논문의 backward references(이 논문이 인용한 논문)를 트리로 표시한다. 기본 1-hop, 사용자 펼침 시 최대 2-hop, 화면당 최대 50노드. | 논문 상세보기 페이지에 요약·초록 번역·전문 번역·각주 트리 4개 액션 중 각주 트리 진입점이 존재한다(상세보기 FE | US-CG1, US-CG2, US-CG3, US-CG6 | U5, U6, U8 |
| FR-16: **인용 노드 저장/연동 [U8]**: 각주 트리 노드는 라이브러리 저장 액션과 연결된다. 전체 인용 그래프 기능은 로그인 필수이며 U3/U6 인증·인가 경로를 통과한다. | 모든 표시 노드에서 "라이브러리에 저장" 가능; 저장 시 U4 `LibraryItemMeta` 스냅샷을 재사용한다. 외부 인용 API 장애 시 캐시된 snapshot을 우선 표시하고, | US-CG4, US-CG5, US-CG6 | U3, U4, U6, U8 |
| NFR-P3: 각주 트리(FR-15/16)는 **온디맨드 액션**으로 검색 SLA(NFR-P1) 대상이 아니다. 캐시 히트는 P50<500ms(제안), 첫 외부 조회는 명시적 로딩/부분 결과를 허용한다. | US-CG1, US-CG6 | U5, U6, U8 |
| NFR-R1: **조용한 오답 금지(no silent wrong answers)**: 모든 실패는 명시적 상태로 표면화; 시스템은 fail closed(SEC-15). | US-CG6, US-D7, US-R1, US-R2, US-R3, US-R4, US-R5 | U2, U5, U6, U8 |
| NFR-U2: 데스크톱/태블릿에서는 앱을 **폰 목업 프레임 안에 중앙 배치**해 렌더링(데스크톱 리플로우 레이아웃 아님). *(SEC-4 자기-프레이밍 유의사항 참조.)* | US-CG6, US-D4 | U2, U5, U6, U8 |
| NFR-X1: 핵심 흐름에 대해 가능 범위에서 WCAG 2.1 AA 지향; v1 차단 게이트는 아님(NFR-R* 우선으로 후순위). | _none_ | _none_ |
| NFR-O1: 메트릭·구조화 로그·트레이스 + 운영 대시보드(RES-5). | US-CG6, US-R4 | U6, U8 |
| NFR-M1: 모듈형 아키텍처, 문서화된 컴포넌트; 기술 스택은 Construction에서 선정. | _none_ | _none_ |
| SEC-2: 모든 네트워크 중간자(LB/API 게이트웨이/CDN)에 액세스 로깅. (SECURITY-02) | _none_ | _none_ |
| SEC-4: HTTP 보안 헤더 + 제한적 CSP. **자기-프레이밍 예외**: 데스크톱에서 앱이 폰 목업 안에 스스로를 프레이밍하므로 `X-Frame-Options`/`frame-ancestors`는 동일 출처 자기-프레이밍을 허용해야 함(전면 `DENY` 아님). 단, 이 카브아웃은 `frame-ancestors`/`X-Frame-Options`에만 적용되며 `sc | US-CG6, US-D4 | U2, U5, U6, U8 |
| SEC-6: 최소 권한 IAM(문서화된 예외 없이는 와일드카드 액션/리소스 금지). (SECURITY-06) | _none_ | _none_ |
| SEC-7: 기본 거부(deny-by-default) 네트워크 구성; 공개 인그레스는 80/443만. (SECURITY-07) | _none_ | _none_ |
| SEC-11: 시큐어 디자인: 인증 로직 격리; **공개 가입 + 검색 엔드포인트에 레이트 리미팅**, **계정 생성 남용 방어(봇/대량 가입 스로틀링·봇 완화)** 포함(공개 서비스의 남용 + 비용 통제; SEC-12 로그인 무차별 대입 방어와 별개). (SECURITY-11) | US-A1, US-CG6, US-R3, US-S6 | U3, U5, U6, U7, U8 |
| SEC-12: 인증: 비밀번호 정책 + 유출 검사, 적응형 해싱, secure/httpOnly/sameSite 세션, 무차별 대입 방어, 관리자 MFA. (SECURITY-12) | US-A1, US-A2, US-CG6 | U3, U5, U6, U8 |
| SEC-14: 경보 + 모니터링; **추가 전용(append-only) 감사 로그**, 90일+ 보존. (SECURITY-14) | _none_ | _none_ |
| RES-1: 워크로드 중요도 분류 및 비즈니스 영향 + 의존성 맵 문서화(arXiv API, LLM/임베딩, 벡터 스토어). (RESILIENCY-01) | US-CG6 | U6, U8 |
| RES-2: **RTO/RPO + DR (CQ4=E)**: 단일 리전, 멀티 AZ; **교차 리전 DR 없음**. 자동 암호화 DB 백업; **계정/검색 저장 메타데이터**에 대해 RPO ~24h 이내 허용, RTO는 IaC 재배포 + 복원으로 수 시간. **공유 arXiv 벡터 인덱스는 FR-6 인제스천 파이프라인에서 재생성 가능(rebuildable) 자산으로 취급 | _none_ | _none_ |
| RES-3: **변경 관리(CQ5=A)**: 기존 프로세스 준수 — **GitHub PR 리뷰 + git-flow(feature → develop → main) + GitHub Projects**. 새로 만들지 않음. (RESILIENCY-03) | _none_ | _none_ |
| RES-4: CI/CD, 롤백 메커니즘, 배포 방식 — **NFR Design으로 보류**(RESILIENCY-04). | US-CG6 | U6, U8 |
| RES-5: 메트릭/로그/트레이스 모니터링 + 운영 대시보드. (RESILIENCY-05) | US-R4 | U6 |
| RES-6: 얕은(shallow) + 깊은(deep) 헬스 체크와 라우팅 연동; 공개 엔드포인트 합성 모니터링. (RESILIENCY-06) | US-CG6, US-R5 | U6, U8 |
| RES-7: 복원력 모니터링 + 경보(예: 인제스천 갱신 실패, 단일 AZ 운영, 용량). (RESILIENCY-07) | US-CG6, US-I2 | U1, U6, U8 |
| RES-8: 오토스케일링 / 서버리스 동시성 한도 + 클라우드 서비스 쿼터 인지(arXiv 레이트 한도, LLM 처리량). (RESILIENCY-09) | US-CG6, US-I3 | U1, U6, U8 |
| RES-10: DR 전략 문서화(Backup & Restore, RES-2 기준): **교차 리전 페일오버 없음** — AZ 수준 복원 + 백업/인덱스 재구축 복구 절차(복원·재구축 런북). (RESILIENCY-11/13) | _none_ | _none_ |
| RES-11: **장애 대응(CQ6=B+)**: **경량 장애 대응 + 오류 교정(COE)** 프로세스 제안; RES-5 경보를 연동. 장애 분류 체계는 **AI/에이전트 특화 클래스**를 명시적으로 포함하며 각각 탐지 신호·경보·COE 후속을 가져야 함: **(a) 비용 폭발** — 폭주하는 LLM/API 비용(→ NFR-C1 비용 상한 서킷 브레이커, SEC-11 레 | US-CG6, US-R1, US-R2, US-R3, US-R4, US-S6 | U2, U6, U7, U8 |
| RES-12: 복원력 테스트 방식 — **NFR Design으로 보류**(RESILIENCY-14). | _none_ | _none_ |
| QT-1: 엄격 근거화 인수 | US-CG6, US-D5, US-D6, US-H1, US-R1, US-S6 | U1, U2, U3, U5, U6, U7, U8 |
| QT-6: 인용 엣지 정확도 + 그래프 불변식 [U8] | US-CG2, US-CG3, US-CG6 | U6, U8 |

## Reverse Traceability Matrix

| Unit | Stories | Requirements |
|------|---------|--------------|
| U1: U1 Ingestion | US-D2, US-D5, US-H1, US-I1, US-I2, US-I3, US-S1, US-S2 | FR-1, FR-12, FR-13, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, NFR-P1, NFR-S1, NFR-U1, QT-1, QT-5, RES-7, RES-8, RES-9 |
| U2: U2 Discovery | US-D1, US-D2, US-D3, US-D4, US-D5, US-D6, US-D7, US-H1, US-L3, US-R1, US-R2, US-S1 | FR-1, FR-10, FR-11, FR-12, FR-2, FR-3, FR-4, FR-5, FR-7, NFR-P1, NFR-R1, NFR-R2, NFR-S1, NFR-U1, NFR-U2, QT-1, QT-2, QT-3, QT-5, RES-11, RES-9, SEC-15, SEC-4, SEC-5, SEC-8, SEC-9 |
| U3: U3 Accounts | US-A1, US-A2, US-CG4, US-H1 | FR-1, FR-16, FR-2, FR-3, FR-4, FR-5, FR-7, FR-9, NFR-A1, NFR-P1, NFR-U1, QT-1, SEC-11, SEC-12, SEC-3, SEC-8 |
| U4: U4 Library | US-CG4, US-L1, US-L2, US-L3 | FR-10, FR-16, FR-8, FR-9, SEC-8 |
| U5: U5 Frontend | US-A1, US-A2, US-CG1, US-D1, US-D4, US-D7, US-H1, US-L1, US-L2, US-S1, US-S2, US-S3, US-S4, US-S5 | FR-1, FR-11, FR-12, FR-13, FR-14, FR-15, FR-2, FR-3, FR-4, FR-5, FR-7, FR-8, FR-9, NFR-A1, NFR-P1, NFR-P2, NFR-P3, NFR-R1, NFR-R2, NFR-S1, NFR-U1, NFR-U2, QT-1, QT-3, QT-5, SEC-11, SEC-12, SEC-15, SEC-3, SEC-4, SEC-5, SEC-8, SEC-9 |
| U6: U6 Reliability/Ops | US-A1, US-A2, US-CG1, US-CG3, US-CG5, US-CG6, US-D5, US-D6, US-I2, US-I3, US-R1, US-R2, US-R3, US-R4, US-R5, US-S3, US-S6 | FR-1, FR-10, FR-11, FR-12, FR-13, FR-14, FR-15, FR-16, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-8, FR-9, NFR-A1, NFR-C1, NFR-O1, NFR-P1, NFR-P2, NFR-P3, NFR-R1, NFR-R2, NFR-S1, NFR-U1, NFR-U2, QT-1, QT-2, QT-3, QT-4, QT-5, QT-6, RES-1, RES-11, RES-4, RES-5, RES-6, RES-7, RES-8, RES-9, SEC-1, SEC-11, SEC-12, SEC-3, SEC-4, SEC-8, SEC-9 |
| U7: U7 Summarization | US-S1, US-S2, US-S3, US-S4, US-S5, US-S6 | FR-11, FR-12, FR-13, FR-14, FR-5, NFR-C1, NFR-P1, NFR-P2, NFR-S1, QT-1, QT-5, RES-11, SEC-11, SEC-8 |
| U8: U8 Citation Graph | US-CG1, US-CG2, US-CG3, US-CG4, US-CG5, US-CG6 | FR-1, FR-10, FR-11, FR-12, FR-13, FR-14, FR-15, FR-16, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-8, FR-9, NFR-C1, NFR-O1, NFR-P1, NFR-P2, NFR-P3, NFR-R1, NFR-R2, NFR-U1, NFR-U2, QT-1, QT-2, QT-3, QT-4, QT-5, QT-6, RES-1, RES-11, RES-4, RES-6, RES-7, RES-8, RES-9, SEC-1, SEC-11, SEC-12, SEC-4, SEC-8, SEC-9 |

## Component → Code Traceability

| Component | Code Files |
|-----------|------------|
| COMP-IngestionPipelineService: IngestionPipelineService | CODE:ingestion/src/docsuri_ingestion/application.py |
| COMP-RefreshOrchestrationService: RefreshOrchestrationService | CODE:ingestion/src/docsuri_ingestion/application.py |
| COMP-IngestionResilienceService: IngestionResilienceService | CODE:ingestion/src/docsuri_ingestion/resilience.py |
| COMP-ArxivSourceClient: ArxivSourceClient | _none_ |
| COMP-FetchParseProcessor: FetchParseProcessor | CODE:ingestion/src/docsuri_ingestion/processors.py |
| COMP-Chunker: Chunker | CODE:ingestion/src/docsuri_ingestion/processors.py |
| COMP-EmbeddingGatewayAdapter: EmbeddingGatewayAdapter | _none_ |
| COMP-VectorIndexWriter: VectorIndexWriter | _none_ |
| COMP-DeduplicationGuard: DeduplicationGuard | CODE:ingestion/src/docsuri_ingestion/processors.py |
| COMP-RefreshScheduler: RefreshScheduler | _none_ |
| COMP-NewArxivEventHandler: NewArxivEventHandler | _none_ |
| COMP-IngestFailureHandler: IngestFailureHandler | CODE:ingestion/src/docsuri_ingestion/resilience.py |
| COMP-EmbeddingCache: EmbeddingCache | CODE:backend/modules/discovery/src/discovery/cache/embedding_cache.py |
| COMP-degradeMode: degradeMode | _none_ |
| COMP-SearchGatewayPort: SearchGatewayPort | CODE:backend/modules/library/ports.py |
| COMP-history_consumer: history_consumer | _none_ |
| COMP-AuditSink: AuditSink | CODE:backend/modules/library/ports.py |
| COMP-OrchestrationService: OrchestrationService | _none_ |
| COMP-SummaryStoreAdapter: SummaryStoreAdapter | _none_ |
| COMP-FullTextSourceAdapter: FullTextSourceAdapter | _none_ |
| COMP-GlossaryRepository: GlossaryRepository | _none_ |
| COMP-BedrockLlmGatewayAdapter: BedrockLlmGatewayAdapter | _none_ |
| COMP-InputRefiner: InputRefiner | CODE:backend/modules/summarization/src/summarization/domain/refiner.py |
| COMP-LengthRouter: LengthRouter | CODE:backend/modules/summarization/src/summarization/domain/length_router.py |
| COMP-GroundingValidator: GroundingValidator | CODE:backend/modules/summarization/src/summarization/domain/grounding.py |
| COMP-ResultAssembler: ResultAssembler | CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py |
| COMP-QueryUnderstandingExpander: QueryUnderstandingExpander | CODE:backend/modules/discovery/src/discovery/domain/expander.py |
| COMP-SearchOrchestrationService: SearchOrchestrationService | CODE:backend/modules/discovery/src/discovery/service/orchestrator.py |
| COMP-U2.SearchOrchestrationService: U2.SearchOrchestrationService | _none_ |
| COMP-GroundingAdapter: GroundingAdapter | CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py |
| COMP-AuthorizationGuard: AuthorizationGuard | CODE:backend/modules/accounts/guard.py |
| COMP-GroundingEnforcementHook: GroundingEnforcementHook | CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py |
| COMP-ReliabilityEvalProbe: ReliabilityEvalProbe | CODE:ops/src/docsuri_ops/reliability_eval.py |
| COMP-QueryIntakeController: QueryIntakeController | _none_ |
| COMP-QueryValidator: QueryValidator | CODE:backend/modules/discovery/src/discovery/domain/validator.py |
| COMP-HybridRetriever: HybridRetriever | CODE:backend/modules/discovery/src/discovery/domain/retriever.py |
| COMP-RelevanceRanker: RelevanceRanker | CODE:backend/modules/discovery/src/discovery/domain/ranker.py |
| COMP-AccountController: AccountController | _none_ |
| COMP-SignupService: SignupService | CODE:backend/modules/accounts/services/signup.py |
| COMP-AuthenticationService: AuthenticationService | CODE:backend/modules/accounts/services/auth.py |
| COMP-SessionManager: SessionManager | CODE:backend/modules/accounts/services/session_manager.py |
| COMP-SessionVerifier: SessionVerifier | _none_ |
| COMP-CredentialStore: CredentialStore | _none_ |
| COMP-PasswordPolicy: PasswordPolicy | CODE:backend/modules/accounts/password.py |
| COMP-SessionStore: SessionStore | _none_ |
| COMP-SavedSearchController: SavedSearchController | _none_ |
| COMP-LibraryController: LibraryController | _none_ |
| COMP-SearchHistoryController: SearchHistoryController | _none_ |
| COMP-SavedSearchService: SavedSearchService | CODE:backend/modules/library/services/saved_search.py |
| COMP-LibraryService: LibraryService | CODE:backend/modules/library/services/library.py |
| COMP-SearchHistoryService: SearchHistoryService | CODE:backend/modules/library/services/history.py |
| COMP-UserDataRepository: UserDataRepository | CODE:backend/modules/library/ports.py |
| COMP-UserDataDTOAndValidation: UserDataDTOAndValidation | _none_ |
| COMP-AppShell: AppShell | _none_ |
| COMP-PhoneMockupFrame: PhoneMockupFrame | CODE:frontend/components/PhoneMockupFrame.tsx |
| COMP-SecurityHeaderPolicy: SecurityHeaderPolicy | _none_ |
| COMP-SearchScreen: SearchScreen | CODE:frontend/components/SearchScreen.tsx |
| COMP-ResultList: ResultList | CODE:frontend/components/ResultList.tsx |
| COMP-ResultCard: ResultCard | CODE:frontend/components/ResultCard.tsx |
| COMP-AccountScreens: AccountScreens | _none_ |
| COMP-LibraryHistoryScreens: LibraryHistoryScreens | _none_ |
| COMP-StateView: StateView | CODE:frontend/components/StateView.tsx |
| COMP-ApiClient: ApiClient | CODE:frontend/lib/api/apiClient.ts |
| COMP-ApiGatewayMiddleware: ApiGatewayMiddleware | _none_ |
| COMP-AuthnAuthzGuard: AuthnAuthzGuard | _none_ |
| COMP-InputValidationGuard: InputValidationGuard | _none_ |
| COMP-RateLimiter: RateLimiter | _none_ |
| COMP-CostGuardCircuitBreaker: CostGuardCircuitBreaker | CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py |
| COMP-ObservabilityHub: ObservabilityHub | CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py |
| COMP-HealthCheckService: HealthCheckService | CODE:ops/src/docsuri_ops/health.py |
| COMP-AiIncidentDetectorSuite: AiIncidentDetectorSuite | CODE:ops/src/docsuri_ops/incidents.py |
| COMP-IncidentEventPublisher: IncidentEventPublisher | CODE:ops/src/docsuri_ops/incidents.py |
| COMP-OpsDashboardService: OpsDashboardService | CODE:ops/src/docsuri_ops/dashboard.py |


## Detailed Traceability

### NFR-P1: (P50<3s) — **U2/U6 API 대상, U1 N/A**.
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/plans/u1-ingestion-nfr-requirements-plan.md (line 20)
**Type**: non-functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-H1**: — 첫 검색 매직 모먼트 *(HERO)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 13)
  - Units: U1, U2, U3, U5
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-S5**: — 온디맨드 즉시/스트리밍 응답
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 190)
  - Units: U5, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### NFR-A1: (99.5% 가용성) — API 대상; U1은 "복구·재시도·정체 없음"(NFR-R1, RES-7/9)으로 표현(SLA 아님).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/plans/u1-ingestion-nfr-requirements-plan.md (line 21)
**Type**: non-functional

**Stories**:
- **US-A1**: — 공개 셀프 가입
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 72)
  - Units: U3, U5, U6
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-A2**: — 로그인, 로그아웃, 세션
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 78)
  - Units: U3, U5, U6
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### NFR-C1: (시스템 전역 $1600/월)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/plans/u2-discovery-nfr-requirements-plan.md (line 18)
**Type**: non-functional

**Stories**:
- **US-CG5**: — 인용 API 실패/쿼터 저하
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 234)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R3**: — 비용 상한 서킷 브레이커 + 비용 폭발 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 142)
  - Units: U6
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S6**: — 요약 비용 게이트 + 근거화 운영 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 196)
  - Units: U6, U7
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### NFR-S1: (~3,000 사용자·동시 ~50)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/plans/u2-discovery-nfr-requirements-plan.md (line 19)
**Type**: non-functional

**Stories**:
- **US-S1**: — AI 구조화 요약
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 165)
  - Units: U1, U2, U5, U7
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-S2**: — 한국어 번역
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 171)
  - Units: U1, U5, U7
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-S3**: — 출처 보기 & 근거 부족 시 기권
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 177)
  - Units: U5, U6, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S4**: — 요약/번역 개인화 (수준·뷰·용어 선호)
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 183)
  - Units: U5, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-S5**: — 온디맨드 즉시/스트리밍 응답
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 190)
  - Units: U5, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-S6**: — 요약 비용 게이트 + 근거화 운영 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 196)
  - Units: U6, U7
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### NFR-P2: (체감 성능)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/plans/u7-summarization-frontend-nfr-requirements-plan.md (line 19)
**Type**: non-functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S5**: — 온디맨드 즉시/스트리밍 응답
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 190)
  - Units: U5, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### RES-9: / NFR-R2
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/plans/u7-summarization-nfr-requirements-plan.md (line 20)
**Type**: resiliency

**Stories**:
- **US-CG5**: — 인용 API 실패/쿼터 저하
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 234)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-I3**: — 복원력 있는 인제스천
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 121)
  - Units: U1, U6
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R2**: — 우아한 저하 + 반쪽짜리 결과 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 136)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### QT-5: 요약/번역 근거화(날조 0·기권·앵커). U7 `GroundingValidator` 결정적 게이트 출력 표면 제공(평가 실행=U6/OP).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/plans/u7-summarization-nfr-requirements-plan.md (line 21)
**Type**: quality

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S1**: — AI 구조화 요약
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 165)
  - Units: U1, U2, U5, U7
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-S3**: — 출처 보기 & 근거 부족 시 기권
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 177)
  - Units: U5, U6, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S6**: — 요약 비용 게이트 + 근거화 운영 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 196)
  - Units: U6, U7
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### SEC-1: at-rest 암호화 + TLS — RDS/OpenSearch/S3 관리형 암호화·전송 TLS(NFR Q17=A).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u1-ingestion/nfr-requirements/nfr-requirements.md (line 31)
**Type**: security

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### SEC-5: 인제스천 데이터 입력 검증·새니타이즈(BR-19).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u1-ingestion/nfr-requirements/nfr-requirements.md (line 32)
**Type**: security

**Stories**:
- **US-D1**: — 자연어 질의 입력
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 25)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### SEC-9: OA 전문 오브젝트 스토리지 **공개 차단**(BR-20) + 일반화 에러.
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u1-ingestion/nfr-requirements/nfr-requirements.md (line 33)
**Type**: security

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D7**: — 빈/실패/저하 UX
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 61)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### SEC-10: (공급망)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u1-ingestion/nfr-requirements/nfr-requirements.md (line 34)
**Type**: security

**Stories**: _none linked_

### SEC-15: 모든 외부 호출 fail-closed(BR-18).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u1-ingestion/nfr-requirements/nfr-requirements.md (line 35)
**Type**: security

**Stories**:
- **US-D7**: — 빈/실패/저하 UX
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 61)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### SEC-3: 구조화 로깅(requestId 상관)·**질의 원문/PII 로깅 정책 준수**.
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u2-discovery/nfr-requirements/nfr-requirements.md (line 48)
**Type**: security

**Stories**:
- **US-A1**: — 공개 셀프 가입
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 72)
  - Units: U3, U5, U6
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### NFR-U1: /U2(폰 우선·폰 목업)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u2-discovery/nfr-requirements/nfr-requirements.md (line 64)
**Type**: non-functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D1**: — 자연어 질의 입력
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 25)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-D4**: — 폰 최적화 결과 카드
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 44)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-H1**: — 첫 검색 매직 모먼트 *(HERO)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 13)
  - Units: U1, U2, U3, U5
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### QT-2: (관련도)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u2-discovery/nfr-requirements/nfr-requirements.md (line 68)
**Type**: quality

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D3**: — 관련도순 상위 N건
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 37)
  - Units: U2
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py

### QT-3: (신뢰성/저하)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u2-discovery/nfr-requirements/nfr-requirements.md (line 69)
**Type**: quality

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D7**: — 빈/실패/저하 UX
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 61)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-R2**: — 우아한 저하 + 반쪽짜리 결과 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 136)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### QT-4: (PBT)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u2-discovery/nfr-requirements/nfr-requirements.md (line 70)
**Type**: quality

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### NFR-R2: 메타 스냅샷 가용성 격리(U2/인덱스 독립); rerun만 degrade | D5/BR-L5, D9/INV-L2 | `LibraryItemDTO.meta`, `SearchResultSetDTO`
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u4-library/nfr-requirements/nfr-requirements.md (line 128)
**Type**: non-functional

**Stories**:
- **US-CG5**: — 인용 API 실패/쿼터 저하
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 234)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D7**: — 빈/실패/저하 UX
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 61)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-R2**: — 우아한 저하 + 반쪽짜리 결과 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 136)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### SEC-8: 인가 위임(U3 `AuthorizationGuard` 단일 권위) + owner-scoping 백스톱 | D11, INV-L1 | `Principal`/`Action`/`AccountId`(U3 재사용)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u4-library/nfr-requirements/nfr-requirements.md (line 130)
**Type**: security

**Stories**:
- **US-A2**: — 로그인, 로그아웃, 세션
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 78)
  - Units: U3, U5, U6
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG1**: — 논문 상세보기에서 각주 트리 열기
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 208)
  - Units: U5, U6, U8
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG4**: — 인용 노드 라이브러리 저장
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 228)
  - Units: U3, U4, U8
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-LibraryController, COMP-LibraryService, COMP-SavedSearchController, COMP-SavedSearchService, COMP-SearchHistoryController, COMP-SearchHistoryService, COMP-UserDataDTOAndValidation, COMP-UserDataRepository
  - Code: CODE:backend/modules/library/services/library.py
  - Code: CODE:backend/modules/library/services/saved_search.py
  - Code: CODE:backend/modules/library/services/history.py
  - Code: CODE:backend/modules/library/ports.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-L1**: — 검색 저장 & 재실행
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 89)
  - Units: U4, U5
  - Components: COMP-LibraryController, COMP-LibraryService, COMP-SavedSearchController, COMP-SavedSearchService, COMP-SearchHistoryController, COMP-SearchHistoryService, COMP-UserDataDTOAndValidation, COMP-UserDataRepository
  - Code: CODE:backend/modules/library/services/library.py
  - Code: CODE:backend/modules/library/services/saved_search.py
  - Code: CODE:backend/modules/library/services/history.py
  - Code: CODE:backend/modules/library/ports.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-L2**: — 라이브러리 저장
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 95)
  - Units: U4, U5
  - Components: COMP-LibraryController, COMP-LibraryService, COMP-SavedSearchController, COMP-SavedSearchService, COMP-SearchHistoryController, COMP-SearchHistoryService, COMP-UserDataDTOAndValidation, COMP-UserDataRepository
  - Code: CODE:backend/modules/library/services/library.py
  - Code: CODE:backend/modules/library/services/saved_search.py
  - Code: CODE:backend/modules/library/services/history.py
  - Code: CODE:backend/modules/library/ports.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-L3**: — 검색 이력
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 100)
  - Units: U2, U4
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-LibraryController, COMP-LibraryService, COMP-SavedSearchController, COMP-SavedSearchService, COMP-SearchHistoryController, COMP-SearchHistoryService, COMP-UserDataDTOAndValidation, COMP-UserDataRepository
  - Code: CODE:backend/modules/library/services/library.py
  - Code: CODE:backend/modules/library/services/saved_search.py
  - Code: CODE:backend/modules/library/services/history.py
  - Code: CODE:backend/modules/library/ports.py
- **US-S4**: — 요약/번역 개인화 (수준·뷰·용어 선호)
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 183)
  - Units: U5, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### SEC-13: 감사(`AuditSink` 변경 연산 발행, 민감/내부 비노출) | D12/BR-L10 | (U6/ops 결선 예정)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/construction/u4-library/nfr-requirements/nfr-requirements.md (line 133)
**Type**: security

**Stories**: _none linked_

### FR-1: 자유 텍스트 자연어 연구 의도를 주 입력으로 받는다. | 단일 질의 입력란; 최대 길이(제안: 500자)까지 허용·검증.
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 37)
**Type**: functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D1**: — 자연어 질의 입력
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 25)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-H1**: — 첫 검색 매직 모먼트 *(HERO)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 13)
  - Units: U1, U2, U3, U5
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### FR-2: 의도를 해석/확장하여 공유 AI/ML arXiv 벡터 인덱스에 대해 **시맨틱 검색**을 수행한다(하이브리드 lexical+vector 허용). | 대표 질의 세트에서 관련 논문이 상위 결과에 등장(평가셋으로 검증 — QT-2).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 38)
**Type**: functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D2**: — 공유 arXiv 인덱스에 대한 시맨틱 검색
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 31)
  - Units: U1, U2
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
- **US-H1**: — 첫 검색 매직 모먼트 *(HERO)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 13)
  - Units: U1, U2, U3, U5
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### FR-3: 관련도순으로 정렬해 상위 N건을 빠르게 반환한다. | 상위 N건(제안: 20) 반환, 문서화된 관련도 점수순 정렬.
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 39)
**Type**: functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D3**: — 관련도순 상위 N건
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 37)
  - Units: U2
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
- **US-H1**: — 첫 검색 매직 모먼트 *(HERO)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 13)
  - Units: U1, U2, U3, U5
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### FR-4: 각 결과를 **폰 화면**에 최적화해 제시: 제목, 저자, 연도, arXiv ID, 초록 스니펫, 관련도 신호, arXiv 링크. | 360–430px 너비에서 가로 스크롤 없이 완전히 가독·조작 가능.
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 40)
**Type**: functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D4**: — 폰 최적화 결과 카드
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 44)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-H1**: — 첫 검색 매직 모먼트 *(HERO)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 13)
  - Units: U1, U2, U3, U5
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### FR-5: **엄격한 근거화(strict grounding)**: 노출되는 모든 논문은 인덱스의 실재 레코드; AI 생성 텍스트(관련도 설명/요약)는 검색된 논문에서만 도출; 근거가 없으면 날조 대신 **기권(abstain)**("관련 논문 없음"). | 평가셋 전반에서 날조 논문/인용 0건; 코퍼스 밖 질의에 기권 경로 동작. (QT-1)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 41)
**Type**: functional

**Stories**:
- **US-CG3**: — 인용 근거화와 unresolved 분리
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 221)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D5**: — 엄격히 근거화된 결과
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 50)
  - Units: U1, U2, U6
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D6**: — 날조 대신 기권
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 56)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-H1**: — 첫 검색 매직 모먼트 *(HERO)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 13)
  - Units: U1, U2, U3, U5
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-R1**: — 근거화 보장 + 할루시네이션 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 130)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S1**: — AI 구조화 요약
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 165)
  - Units: U1, U2, U5, U7
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-S3**: — 출처 보기 & 근거 부족 시 기권
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 177)
  - Units: U5, U6, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### FR-6: **인제스천 & 인덱싱 파이프라인**: arXiv API(오픈액세스 메타데이터+전문)에서 AI/ML 논문을 수집→청크→임베딩→벡터 인덱스 저장; 최신성 위해 스케줄 갱신. | **arXiv 슬라이스(제안: 카테고리 cs.LG·cs.AI·cs.CL·cs.CV·stat.ML; 기간 최근 5년; 규모 수십만 건)** 수집; **갱신 주기(제안: 일 1회)** 로
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 42)
**Type**: functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-I1**: — arXiv 인제스천 & 인덱싱 파이프라인
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 109)
  - Units: U1
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
- **US-I2**: — 최신성 스케줄 갱신
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 115)
  - Units: U1, U6
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### FR-7: **사용자 계정**: 공개 셀프 가입, 로그인, 로그아웃, 인증 세션. | 신규 사용자가 셀프 가입·로그인·세션 유지 가능; 자격증명은 SEC-12 준수.
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 43)
**Type**: functional

**Stories**:
- **US-A1**: — 공개 셀프 가입
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 72)
  - Units: U3, U5, U6
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-A2**: — 로그인, 로그아웃, 세션
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 78)
  - Units: U3, U5, U6
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-H1**: — 첫 검색 매직 모먼트 *(HERO)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 13)
  - Units: U1, U2, U3, U5
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### FR-8: **검색 저장**: 질의 저장, 목록, 재실행, 삭제(사용자별 비공개). | 저장 검색이 세션 간 지속, 소유자에게만 노출(SEC-8).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 44)
**Type**: functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-L1**: — 검색 저장 & 재실행
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 89)
  - Units: U4, U5
  - Components: COMP-LibraryController, COMP-LibraryService, COMP-SavedSearchController, COMP-SavedSearchService, COMP-SearchHistoryController, COMP-SearchHistoryService, COMP-UserDataDTOAndValidation, COMP-UserDataRepository
  - Code: CODE:backend/modules/library/services/library.py
  - Code: CODE:backend/modules/library/services/saved_search.py
  - Code: CODE:backend/modules/library/services/history.py
  - Code: CODE:backend/modules/library/ports.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### FR-9: **라이브러리 저장**: 논문을 개인 라이브러리에 추가/삭제·목록. | 라이브러리가 사용자별 지속·비공개(SEC-8).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 45)
**Type**: functional

**Stories**:
- **US-CG4**: — 인용 노드 라이브러리 저장
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 228)
  - Units: U3, U4, U8
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-LibraryController, COMP-LibraryService, COMP-SavedSearchController, COMP-SavedSearchService, COMP-SearchHistoryController, COMP-SearchHistoryService, COMP-UserDataDTOAndValidation, COMP-UserDataRepository
  - Code: CODE:backend/modules/library/services/library.py
  - Code: CODE:backend/modules/library/services/saved_search.py
  - Code: CODE:backend/modules/library/services/history.py
  - Code: CODE:backend/modules/library/ports.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-L2**: — 라이브러리 저장
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 95)
  - Units: U4, U5
  - Components: COMP-LibraryController, COMP-LibraryService, COMP-SavedSearchController, COMP-SavedSearchService, COMP-SearchHistoryController, COMP-SearchHistoryService, COMP-UserDataDTOAndValidation, COMP-UserDataRepository
  - Code: CODE:backend/modules/library/services/library.py
  - Code: CODE:backend/modules/library/services/saved_search.py
  - Code: CODE:backend/modules/library/services/history.py
  - Code: CODE:backend/modules/library/ports.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### FR-10: 사용자별 **검색 이력**. | 최근 질의가 목록·재실행 가능, 사용자에게 비공개.
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 46)
**Type**: functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-L3**: — 검색 이력
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 100)
  - Units: U2, U4
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-LibraryController, COMP-LibraryService, COMP-SavedSearchController, COMP-SavedSearchService, COMP-SearchHistoryController, COMP-SearchHistoryService, COMP-UserDataDTOAndValidation, COMP-UserDataRepository
  - Code: CODE:backend/modules/library/services/library.py
  - Code: CODE:backend/modules/library/services/saved_search.py
  - Code: CODE:backend/modules/library/services/history.py
  - Code: CODE:backend/modules/library/ports.py

### FR-11: **빈 결과 & 실패 UX**: 빈 검색, 업스트림(arXiv/LLM/인덱스) 장애, 저하(degraded) 모드에 대한 명확한 구분 상태. | 각 상태가 구체적·비기술적 메시지 표시; 빈 화면·스택 트레이스 없음; 오류 시 fail closed·일반화된 프로덕션 에러(SEC-9, SEC-15, NFR-R1).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 47)
**Type**: functional

**Stories**:
- **US-CG5**: — 인용 API 실패/쿼터 저하
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 234)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D6**: — 날조 대신 기권
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 56)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D7**: — 빈/실패/저하 UX
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 61)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-R2**: — 우아한 저하 + 반쪽짜리 결과 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 136)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S3**: — 출처 보기 & 근거 부족 시 기권
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 177)
  - Units: U5, U6, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S6**: — 요약 비용 게이트 + 근거화 운영 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 196)
  - Units: U6, U7
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### FR-12: **AI 요약(요약 액션) [U7]**: 검색 결과 카드에서 선택한 **단일 논문의 전문**을 페르소나 질문 기반 **구조화 요약**(핵심주장·기여·방법·결과·한계·재현성)으로 생성. 요약 *수준* 선택(전문가용/입문자용). 각 항목에 원문 근거 앵커(섹션·표·그림) 부기. | 선택 논문 1편에 구조화 요약 반환; 각 주장에 검증 가능한 원문 앵커("출처 
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 48)
**Type**: functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S1**: — AI 구조화 요약
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 165)
  - Units: U1, U2, U5, U7
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-S3**: — 출처 보기 & 근거 부족 시 기권
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 177)
  - Units: U5, U6, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S5**: — 온디맨드 즉시/스트리밍 응답
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 190)
  - Units: U5, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### FR-13: **한국어 번역(번역 액션) [U7]**: 선택한 논문의 **초록**을 한국어로 번역. 도메인 용어집(미번역 리스트 포함) 적용으로 전문용어 일관. | 초록 한국어 번역 반환; 용어집의 미번역 용어(모델명·약어)는 영어 유지; 사용자 용어 선호 저장 시 이후 일관 적용(SEC-8). 온디맨드(NFR-P2).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 49)
**Type**: functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S2**: — 한국어 번역
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 171)
  - Units: U1, U5, U7
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-S5**: — 온디맨드 즉시/스트리밍 응답
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 190)
  - Units: U5, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### FR-14: **요약/번역 개인화 [U7]**: persona 생성 변형(전문가용/입문자용)·표시 뷰 프리셋(전체/3줄/관점별)·용어집(P1 도메인 시드 + P2 개인 오버라이드). | persona는 논문당 최대 2벌 생성; 뷰 프리셋은 동일 출력의 **재생성 없는** 표시 변형; 개인 용어 선호가 사용자별 지속(SEC-8). 커뮤니티 공유 용어집(P3)·자유입력 p
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 50)
**Type**: functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S4**: — 요약/번역 개인화 (수준·뷰·용어 선호)
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 183)
  - Units: U5, U7
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### FR-15: **각주 트리 / 인용 그래프 [U8]**: 논문 상세보기 페이지에서 선택 논문의 backward references(이 논문이 인용한 논문)를 트리로 표시한다. 기본 1-hop, 사용자 펼침 시 최대 2-hop, 화면당 최대 50노드. | 논문 상세보기 페이지에 요약·초록 번역·전문 번역·각주 트리 4개 액션 중 각주 트리 진입점이 존재한다(상세보기 FE
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 51)
**Type**: functional

**Stories**:
- **US-CG1**: — 논문 상세보기에서 각주 트리 열기
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 208)
  - Units: U5, U6, U8
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG2**: — 제한된 깊이와 노드 메타데이터
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 214)
  - Units: U8
- **US-CG3**: — 인용 근거화와 unresolved 분리
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 221)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### FR-16: **인용 노드 저장/연동 [U8]**: 각주 트리 노드는 라이브러리 저장 액션과 연결된다. 전체 인용 그래프 기능은 로그인 필수이며 U3/U6 인증·인가 경로를 통과한다. | 모든 표시 노드에서 "라이브러리에 저장" 가능; 저장 시 U4 `LibraryItemMeta` 스냅샷을 재사용한다. 외부 인용 API 장애 시 캐시된 snapshot을 우선 표시하고,
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 52)
**Type**: functional

**Stories**:
- **US-CG4**: — 인용 노드 라이브러리 저장
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 228)
  - Units: U3, U4, U8
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-LibraryController, COMP-LibraryService, COMP-SavedSearchController, COMP-SavedSearchService, COMP-SearchHistoryController, COMP-SearchHistoryService, COMP-UserDataDTOAndValidation, COMP-UserDataRepository
  - Code: CODE:backend/modules/library/services/library.py
  - Code: CODE:backend/modules/library/services/saved_search.py
  - Code: CODE:backend/modules/library/services/history.py
  - Code: CODE:backend/modules/library/ports.py
- **US-CG5**: — 인용 API 실패/쿼터 저하
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 234)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### NFR-P3: 각주 트리(FR-15/16)는 **온디맨드 액션**으로 검색 SLA(NFR-P1) 대상이 아니다. 캐시 히트는 P50<500ms(제안), 첫 외부 조회는 명시적 로딩/부분 결과를 허용한다.
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 59)
**Type**: non-functional

**Stories**:
- **US-CG1**: — 논문 상세보기에서 각주 트리 열기
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 208)
  - Units: U5, U6, U8
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### NFR-R1: **조용한 오답 금지(no silent wrong answers)**: 모든 실패는 명시적 상태로 표면화; 시스템은 fail closed(SEC-15).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 67)
**Type**: non-functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D7**: — 빈/실패/저하 UX
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 61)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-R1**: — 근거화 보장 + 할루시네이션 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 130)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R2**: — 우아한 저하 + 반쪽짜리 결과 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 136)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R3**: — 비용 상한 서킷 브레이커 + 비용 폭발 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 142)
  - Units: U6
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R4**: — 관측성 & AI 인시던트 경보
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 148)
  - Units: U6
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R5**: — 헬스 체크
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 154)
  - Units: U6
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### NFR-U2: 데스크톱/태블릿에서는 앱을 **폰 목업 프레임 안에 중앙 배치**해 렌더링(데스크톱 리플로우 레이아웃 아님). *(SEC-4 자기-프레이밍 유의사항 참조.)*
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 72)
**Type**: non-functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D4**: — 폰 최적화 결과 카드
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 44)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### NFR-X1: 핵심 흐름에 대해 가능 범위에서 WCAG 2.1 AA 지향; v1 차단 게이트는 아님(NFR-R* 우선으로 후순위).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 75)
**Type**: non-functional

**Stories**: _none linked_

### NFR-O1: 메트릭·구조화 로그·트레이스 + 운영 대시보드(RES-5).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 78)
**Type**: non-functional

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R4**: — 관측성 & AI 인시던트 경보
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 148)
  - Units: U6
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### NFR-M1: 모듈형 아키텍처, 문서화된 컴포넌트; 기술 스택은 Construction에서 선정.
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 79)
**Type**: non-functional

**Stories**: _none linked_

### SEC-2: 모든 네트워크 중간자(LB/API 게이트웨이/CDN)에 액세스 로깅. (SECURITY-02)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 86)
**Type**: security

**Stories**: _none linked_

### SEC-4: HTTP 보안 헤더 + 제한적 CSP. **자기-프레이밍 예외**: 데스크톱에서 앱이 폰 목업 안에 스스로를 프레이밍하므로 `X-Frame-Options`/`frame-ancestors`는 동일 출처 자기-프레이밍을 허용해야 함(전면 `DENY` 아님). 단, 이 카브아웃은 `frame-ancestors`/`X-Frame-Options`에만 적용되며 `sc
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 88)
**Type**: security

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D4**: — 폰 최적화 결과 카드
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 44)
  - Units: U2, U5
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx

### SEC-6: 최소 권한 IAM(문서화된 예외 없이는 와일드카드 액션/리소스 금지). (SECURITY-06)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 90)
**Type**: security

**Stories**: _none linked_

### SEC-7: 기본 거부(deny-by-default) 네트워크 구성; 공개 인그레스는 80/443만. (SECURITY-07)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 91)
**Type**: security

**Stories**: _none linked_

### SEC-11: 시큐어 디자인: 인증 로직 격리; **공개 가입 + 검색 엔드포인트에 레이트 리미팅**, **계정 생성 남용 방어(봇/대량 가입 스로틀링·봇 완화)** 포함(공개 서비스의 남용 + 비용 통제; SEC-12 로그인 무차별 대입 방어와 별개). (SECURITY-11)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 95)
**Type**: security

**Stories**:
- **US-A1**: — 공개 셀프 가입
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 72)
  - Units: U3, U5, U6
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R3**: — 비용 상한 서킷 브레이커 + 비용 폭발 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 142)
  - Units: U6
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S6**: — 요약 비용 게이트 + 근거화 운영 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 196)
  - Units: U6, U7
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### SEC-12: 인증: 비밀번호 정책 + 유출 검사, 적응형 해싱, secure/httpOnly/sameSite 세션, 무차별 대입 방어, 관리자 MFA. (SECURITY-12)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 96)
**Type**: security

**Stories**:
- **US-A1**: — 공개 셀프 가입
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 72)
  - Units: U3, U5, U6
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-A2**: — 로그인, 로그아웃, 세션
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 78)
  - Units: U3, U5, U6
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### SEC-14: 경보 + 모니터링; **추가 전용(append-only) 감사 로그**, 90일+ 보존. (SECURITY-14)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 98)
**Type**: security

**Stories**: _none linked_

### RES-1: 워크로드 중요도 분류 및 비즈니스 영향 + 의존성 맵 문서화(arXiv API, LLM/임베딩, 벡터 스토어). (RESILIENCY-01)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 105)
**Type**: resiliency

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### RES-2: **RTO/RPO + DR (CQ4=E)**: 단일 리전, 멀티 AZ; **교차 리전 DR 없음**. 자동 암호화 DB 백업; **계정/검색 저장 메타데이터**에 대해 RPO ~24h 이내 허용, RTO는 IaC 재배포 + 복원으로 수 시간. **공유 arXiv 벡터 인덱스는 FR-6 인제스천 파이프라인에서 재생성 가능(rebuildable) 자산으로 취급
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 106)
**Type**: resiliency

**Stories**: _none linked_

### RES-3: **변경 관리(CQ5=A)**: 기존 프로세스 준수 — **GitHub PR 리뷰 + git-flow(feature → develop → main) + GitHub Projects**. 새로 만들지 않음. (RESILIENCY-03)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 107)
**Type**: resiliency

**Stories**: _none linked_

### RES-4: CI/CD, 롤백 메커니즘, 배포 방식 — **NFR Design으로 보류**(RESILIENCY-04).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 108)
**Type**: resiliency

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### RES-5: 메트릭/로그/트레이스 모니터링 + 운영 대시보드. (RESILIENCY-05)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 109)
**Type**: resiliency

**Stories**:
- **US-R4**: — 관측성 & AI 인시던트 경보
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 148)
  - Units: U6
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### RES-6: 얕은(shallow) + 깊은(deep) 헬스 체크와 라우팅 연동; 공개 엔드포인트 합성 모니터링. (RESILIENCY-06)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 110)
**Type**: resiliency

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R5**: — 헬스 체크
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 154)
  - Units: U6
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### RES-7: 복원력 모니터링 + 경보(예: 인제스천 갱신 실패, 단일 AZ 운영, 용량). (RESILIENCY-07)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 111)
**Type**: resiliency

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-I2**: — 최신성 스케줄 갱신
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 115)
  - Units: U1, U6
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### RES-8: 오토스케일링 / 서버리스 동시성 한도 + 클라우드 서비스 쿼터 인지(arXiv 레이트 한도, LLM 처리량). (RESILIENCY-09)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 112)
**Type**: resiliency

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-I3**: — 복원력 있는 인제스천
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 121)
  - Units: U1, U6
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### RES-10: DR 전략 문서화(Backup & Restore, RES-2 기준): **교차 리전 페일오버 없음** — AZ 수준 복원 + 백업/인덱스 재구축 복구 절차(복원·재구축 런북). (RESILIENCY-11/13)
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 114)
**Type**: resiliency

**Stories**: _none linked_

### RES-11: **장애 대응(CQ6=B+)**: **경량 장애 대응 + 오류 교정(COE)** 프로세스 제안; RES-5 경보를 연동. 장애 분류 체계는 **AI/에이전트 특화 클래스**를 명시적으로 포함하며 각각 탐지 신호·경보·COE 후속을 가져야 함: **(a) 비용 폭발** — 폭주하는 LLM/API 비용(→ NFR-C1 비용 상한 서킷 브레이커, SEC-11 레
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 115)
**Type**: resiliency

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R1**: — 근거화 보장 + 할루시네이션 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 130)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R2**: — 우아한 저하 + 반쪽짜리 결과 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 136)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R3**: — 비용 상한 서킷 브레이커 + 비용 폭발 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 142)
  - Units: U6
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-R4**: — 관측성 & AI 인시던트 경보
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 148)
  - Units: U6
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S6**: — 요약 비용 게이트 + 근거화 운영 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 196)
  - Units: U6, U7
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### RES-12: 복원력 테스트 방식 — **NFR Design으로 보류**(RESILIENCY-14).
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 116)
**Type**: resiliency

**Stories**: _none linked_

### QT-1: 엄격 근거화 인수
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 120)
**Type**: quality

**Stories**:
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D5**: — 엄격히 근거화된 결과
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 50)
  - Units: U1, U2, U6
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-D6**: — 날조 대신 기권
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 56)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-H1**: — 첫 검색 매직 모먼트 *(HERO)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 13)
  - Units: U1, U2, U3, U5
  - Components: COMP-ArxivSourceClient, COMP-Chunker, COMP-DeduplicationGuard, COMP-EmbeddingGatewayAdapter, COMP-FetchParseProcessor, COMP-IngestFailureHandler, COMP-NewArxivEventHandler, COMP-RefreshScheduler, COMP-VectorIndexWriter
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/processors.py
  - Code: CODE:ingestion/src/docsuri_ingestion/resilience.py
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AccountController, COMP-AuthenticationService, COMP-AuthorizationGuard, COMP-CredentialStore, COMP-PasswordPolicy, COMP-SessionManager, COMP-SessionStore, COMP-SessionVerifier, COMP-SignupService
  - Code: CODE:backend/modules/accounts/services/auth.py
  - Code: CODE:backend/modules/accounts/guard.py
  - Code: CODE:backend/modules/accounts/password.py
  - Code: CODE:backend/modules/accounts/services/session_manager.py
  - Code: CODE:backend/modules/accounts/services/signup.py
  - Components: COMP-AccountScreens, COMP-ApiClient, COMP-AppShell, COMP-LibraryHistoryScreens, COMP-PhoneMockupFrame, COMP-ResultCard, COMP-ResultList, COMP-SearchScreen, COMP-SecurityHeaderPolicy, COMP-StateView
  - Code: CODE:frontend/lib/api/apiClient.ts
  - Code: CODE:frontend/components/PhoneMockupFrame.tsx
  - Code: CODE:frontend/components/ResultCard.tsx
  - Code: CODE:frontend/components/ResultList.tsx
  - Code: CODE:frontend/components/SearchScreen.tsx
  - Code: CODE:frontend/components/StateView.tsx
- **US-R1**: — 근거화 보장 + 할루시네이션 탐지
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 130)
  - Units: U2, U6
  - Components: COMP-GroundingAdapter, COMP-HybridRetriever, COMP-QueryIntakeController, COMP-QueryUnderstandingExpander, COMP-QueryValidator, COMP-RelevanceRanker, COMP-ResultAssembler
  - Code: CODE:backend/modules/discovery/src/discovery/domain/grounding_adapter.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/retriever.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/expander.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/validator.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/ranker.py
  - Code: CODE:backend/modules/discovery/src/discovery/domain/assembler.py, CODE:backend/modules/summarization/src/summarization/domain/assembler.py
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-S6**: — 요약 비용 게이트 + 근거화 운영 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 196)
  - Units: U6, U7
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py

### QT-6: 인용 엣지 정확도 + 그래프 불변식 [U8]
**Source**: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/requirements/requirements.md (line 125)
**Type**: quality

**Stories**:
- **US-CG2**: — 제한된 깊이와 노드 메타데이터
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 214)
  - Units: U8
- **US-CG3**: — 인용 근거화와 unresolved 분리
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 221)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
- **US-CG6**: — 인용 그래프 운영 관측성 *(페르소나 OP)*
  - Source: /Users/revenantonthemission/.claude/jobs/56eec639/tmp/ds-develop/aidlc-docs/inception/user-stories/stories.md (line 240)
  - Units: U6, U8
  - Components: COMP-AiIncidentDetectorSuite, COMP-ApiGatewayMiddleware, COMP-AuthnAuthzGuard, COMP-CostGuardCircuitBreaker, COMP-GroundingEnforcementHook, COMP-HealthCheckService, COMP-IncidentEventPublisher, COMP-InputValidationGuard, COMP-ObservabilityHub, COMP-OpsDashboardService, COMP-RateLimiter, COMP-ReliabilityEvalProbe
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/cost_guard.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/grounding.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/health.py
  - Code: CODE:ops/src/docsuri_ops/incidents.py
  - Code: CODE:ops/src/docsuri_ops/observability.py, CODE:shared/python/src/docsuri_shared/ports.py
  - Code: CODE:ops/src/docsuri_ops/dashboard.py
  - Code: CODE:ops/src/docsuri_ops/reliability_eval.py
