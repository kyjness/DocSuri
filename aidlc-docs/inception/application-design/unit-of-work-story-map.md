# unit-of-work-story-map.md — 스토리 → 유닛 매핑

**단계**: INCEPTION → Units Generation · **일자**: 2026-06-15
**근거**: `stories.md`(핵심 45 + US-NV1~9[U12] + US-EV1~9[U11]), `unit-of-work.md`(U1~U12). 각 스토리에 **주 소유 유닛(Owner)** + 기여 유닛. (구 통합 U11 연구 에이전트 스토리는 2유닛 분리로 제거 후 **에픽 9 US-NV(U12 novelty)·에픽 10 US-EV(U11 evidence)로 재생성 완료** — 2026-06-29; 아래 U11/U12 묶음 참조. 정정 2026-06-30, `aidlc-suite-review` PR #280.)

---

## 매핑 (45개 전수)

| 스토리 | Owner | 기여 유닛 |
|---|---|---|
| **US-H1** 히어로(가입→질의→근거화 결과) | U5 | U2(백킹 검색), U3(가입), U1(Corpus 인덱스) |
| **US-D1** 자연어 질의 입력 | U2 | U5(검색 화면) |
| **US-D2** 시맨틱 검색 | U2 | U1(공유 Corpus 인덱스) |
| **US-D3** 상위 N 랭킹 | U2 | — |
| **US-D4** 폰 결과 카드 | U2(조립) | U5(카드) |
| **US-D5** 엄격 근거화 | U6(근거화 후크) | U2(어댑터), U1(DocModel Block anchor) |
| **US-D6** 기권 | U2(어댑터) | U6(후크) |
| **US-D7** 빈/실패/저하 UX | U5(StateView) | U2 |
| **US-A1** 공개 가입 | U3 | U5(계정 화면), U6(레이트리밋) |
| **US-A2** 로그인/세션 | U3 | U5, U6(게이트웨이) |
| **US-A3** 비밀번호 재설정 | U3 | U5(재설정 화면), U6(레이트리밋), 이메일=Resend |
| **US-A4** 소셜 로그인(Google OIDC) | U3 | U5(소셜 버튼·콜백 UI), U6(게이트웨이), 외부 Google OIDC |
| **US-A5** 비번/이메일 변경 | U3 | U5/U10(설정 UI), 이메일=Resend |
| **US-A6** 계정 삭제(소프트+유예 캐스케이드) | U3 | U4·U2(owner-scoped 데이터 **이벤트 구독·파기**), U5/U10(UI) |
| **US-A7** 인증 에러 표면화·입력 견고화 | U3 | U5(에러 표면화·재발송 UX) |
| **US-L1** 검색 저장 | U4 | U5 |
| **US-L2** 라이브러리 | U4 | U5 |
| **US-L3** 검색 이력 | U4 | U2(SearchExecuted 생산) |
| **US-I1** 멀티소스 Corpus & DocModel 인덱싱 | U1 | — |
| **US-I2** source별 스케줄 갱신 | U1 | U6(갱신 실패 경보) |
| **US-I3** 복원력 인제스천 | U1 | U6(관측) |
| **US-R1** 근거화 보장+할루시네이션 탐지 | U6 | U2 |
| **US-R2** 우아한 저하+반쪽짜리 탐지 | U6 | U2(저하 폴백) |
| **US-R3** 비용 상한+비용 폭발 탐지 | U6 | — |
| **US-R4** 관측성+AI 인시던트 경보 | U6 | (전 유닛 신호원) |
| **US-R5** 헬스 체크 | U6 | — |
| **US-S1** AI 구조화 요약 | U7 | U1(전문 원본), U2/U5(결과 카드) |
| **US-S2** 한국어 번역 | U7 | U1(초록 원본), U5(표시) |
| **US-S3** 출처 보기 + 기권 | U7 | U6(근거화 후크), U5(하이라이트 UI) |
| **US-S4** 요약/번역 개인화 | U7 | U5(수준/뷰 전환 UI) |
| **US-S5** 온디맨드 즉시/스트리밍 | U7 | U5(점진 렌더) |
| **US-S6** 요약 비용 게이트 + 근거화 운영 | U6 | U7(요약 경로), (관측 신호원) |
| **US-CG1** 논문 상세보기에서 각주 트리 열기 | U8 | U5(상세보기 UI), U6(게이트웨이) |
| **US-CG2** 제한된 깊이와 노드 메타데이터 | U8 | — |
| **US-CG3** 인용 근거화와 unresolved 분리 | U8 | U6(관측/인시던트 신호) |
| **US-CG4** 인용 노드 라이브러리 저장 | U8 | U4(저장 계약), U3(인가) |
| **US-CG5** 인용 API 실패/쿼터 저하 | U8 | U6(레이트리밋/관측) |
| **US-CG6** 인용 그래프 운영 관측성 | U6 | U8(관측 신호원) |
| **US-P1** 의미 있는 행동 이벤트 기록 | U9 | U2/U4/U7/U5(성공 경로 신호원), U6(저하 관측) |
| **US-P2** 라이브러리 저장/해제와 출처 앵커 신호 | U9 | U4(저장/해제), U7/U5(출처 앵커) |
| **US-P3** 사용자 관심 프로필 집계 | U9 | — |
| **US-P4** 검색 결과 소폭 개인화 | U9 | U2(랭킹 적용), U5(표시/끄기 진입점) |
| **US-P5** 요약/번역 기본값 개인화 | U9 | U7(기본값 적용), U5(옵션 UI) |
| **US-P6** 개인화 제어권 | U9 | U5(설정 UI), U3(사용자/인가) |
| **US-P7** 개인화 운영 관측성과 저하 | U6 | U9(저하/집계 신호원) |

## 유닛별 스토리 묶음
- **U1 Ingestion** — US-I1, US-I2, US-I3 (+US-H1/US-D2 Corpus 인덱스 백킹)
- **U2 Discovery** — US-D1, US-D2, US-D3, US-D4, US-D6 (+US-D5/US-D7/US-R1/R2 기여, US-H1 백킹, US-L3 생산자)
- **U3 Accounts** — US-A1..A7 (+US-H1 가입); 프로덕션화 US-A3~A7(재설정·소셜 OIDC·비번/이메일 변경·삭제·입력 견고화) 추가. **자가관리 설정 UI = U10 마이페이지 소유, U3 = 백엔드 엔드포인트·도메인 규칙 소유**(경계 Q2=A).
- **U4 Library** — US-L1, US-L2, US-L3
- **U5 Frontend** — US-H1(주), US-D7(주) (+US-D1/D4/A1/A2/L1/L2/L3 UI 기여)
- **U6 Reliability/Ops** — US-D5(주), US-R1, US-R2, US-R3, US-R4, US-R5, US-S6 (+US-A1 레이트리밋, US-I2/I3 관측)
- **U7 Summarization** — US-S1, US-S2, US-S3, US-S4, US-S5 (+US-S6 요약 경로 기여)
- **U8 Citation Graph** — US-CG1, US-CG2, US-CG3, US-CG4, US-CG5 (+US-CG6 관측 신호원)
- **U9 Personalization** — US-P1, US-P2, US-P3, US-P4, US-P5, US-P6 (+US-P7 관측 신호원)
- **U11 Evidence Agent** — US-EV1~9 (에픽 10; 문헌탐색·근거형성. requirements 초안 `[U4]` 오기 → U11 정정 2026-06-30)
- **U12 Novelty Agent** — US-NV1~9 (에픽 9; 차별화 novelty·별도 인셉션 사이클로 빌드 `construction/novelty-agent/`. US-NV9=운영 관측성 페르소나 OP)

## 전수 할당 검증
- 스토리 **45개** = US-H1 + US-D1..D7(7) + **US-A1..A7(7)** + US-L1..L3(3) + US-I1..I3(3) + US-R1..R5(5) + **US-S1..S6(6)** + **US-CG1..CG6(6)** + **US-P1..P7(7)** → **전부 Owner 배정 완료(미할당 0)**.
- 횡단 스토리(US-D5 근거화)는 Owner=U6(단일 권위 후크), 기여=U2(어댑터) — Application Design 단일-소유자 규칙과 일치.
- US-H1(히어로)은 통합 슬라이스 — Owner=U5(프런트 표면), 다수 유닛 백킹(US-D*/US-A1으로 실현).
- **U7 추가(2026-06-18)**: US-S1..S5 Owner=U7(요약/번역 신규 책임), US-S6은 비용게이트·근거화 운영이라 Owner=U6(단일 권위) 기여=U7 — 단일-소유자 규칙 일치. U7은 U1(전문)·U6(근거화/비용)에 의존하나 코드 의존 그래프는 비순환 유지(`unit-of-work-dependency.md` §비순환 검증).
- **U8 추가(2026-06-19)**: US-CG1..CG5 Owner=U8(각주 트리 신규 책임), US-CG6은 운영 관측성이라 Owner=U6 기여=U8 — 단일-소유자 규칙 일치. U8은 U3/U6 인증 경로와 U4 저장 계약에 의존하나 역호출이 없어 코드 의존 그래프는 비순환 유지.
- **U9 추가(2026-06-23)**: US-P1..P6 Owner=U9(행동 이벤트/프로필/제어 신규 책임), US-P7은 운영 관측성이라 Owner=U6 기여=U9 — 단일-소유자 규칙 일치. U9는 U3/U6 인증·관측 경로에 의존하고 U2/U4/U7/U5는 U9를 비차단 호출하나, U9 역호출이 없어 코드 의존 그래프는 비순환 유지.
- **연구 에이전트(2026-06-28 재구성 → 2026-06-29 재생성 완료)**: 구 통합 U11(US-RA1~8)은 폐기되고 **U11(문헌탐색·근거형성)·U12(novelty/연구아이디어) 2유닛으로 분리**(차터 §4). 스토리·Owner 재생성 완료 — **에픽 10 US-EV1~9 Owner=U11**, **에픽 9 US-NV1~9 Owner=U12**(운영 관측성 US-NV9는 페르소나 OP). 의존: U11→U2/U7/U6/`shared`, U12→U11(`EvidenceFormationPort`)·U2 `full`·외부탐색 — D5 포트 역전으로 비순환 유지.
- **U3 확장 — 계정 프로덕션화(2026-06-24)**: US-A3~A7 Owner=**U3**(재설정·소셜 OIDC·비번/이메일 변경·삭제·입력 견고화 — 신규 에픽 아님, 에픽 2 확장). **경계(Q2=A)**: U10 마이페이지(타 팀원)=프로필/설정 **UI만**, U3=백엔드 `/auth/*` 엔드포인트·도메인 규칙 소유. **신규 의존**: U3→외부 Google OIDC(콜백·토큰 교환). **삭제 캐스케이드**: U4/U2는 이미 U3 인증에 의존하므로 U3가 이들을 **직접 호출하면 순환** — 따라서 캐스케이드는 **이벤트 구동**(U3가 `AccountDeleted` 발행 → U4/U2가 각자 owner-scoped 데이터 구독·파기)으로 의존성 역전(U7↔U6 `shared/ports` 패턴 동일) → **코드 의존 그래프 비순환 유지**. (분리될 연구 에이전트 유닛도 동일 이벤트 구독 패턴으로 편입 예정.) 이벤트 계약·유예 잡 메커니즘 = Construction(Functional/Infra Design).
- **U1 확장 — Corpus 완성형(2026-06-26)**: US-I1~I3 Owner=**U1** 유지. 멀티소스 수집(arXiv/Semantic Scholar/OpenAlex), GROBID, eager DocModel, DocModel Block 청킹/임베딩/index generation, source watermark, retry/DLQ는 모두 write-side Corpus 파이프라인 책임이므로 신규 유닛을 만들지 않는다. U2/U7은 Corpus/DocModel capability read 소비자이며 코드 의존 그래프 비순환 유지.
