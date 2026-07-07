# DocSuri Production Roadmap — 2026-07

> **Date**: 2026-07-03 · **Baseline**: develop (2026-07-07) · **main at v1.12.0** (`e7390b44`; v1.9.0→v1.12.0 promotions #405 reembed fast-rebuild+bulk-PDF re-parse, #415 novelty-agent). develop 21 commits ahead.
> **Updated**: 2026-07-07 (session sweep) — **reconcile vs live `origin/main`**:
> - **main advanced to v1.12.0** since the notes below were written. Already ON main (not "promotion pending"): **#346 KPI funnel** (PR #403), **#347 U10 real-data** (PR #407 최근 본 논문 + PR #414 ORCID 버튼), plus #405/#415.
> - **#422 authz merged** to develop (`15fc49fa`) — supersedes "PR #422 open" below. **env-seam test fix landed** on develop (`6207455c`, via #417 bundle) — no longer a dangling branch.
> - **Real develop→main gap = 6 items** awaiting one v1.13 promotion+deploy: **#416** reranker, **#418** SSR-500 root-cause, **#420** docmodel throttle, **#422** authz, env-seam test, **#427** email→SES.
> - **4 open PRs in flight** (not yet reflected below): **#419** reembed Cohere-v3, **#423** U8 citation-graph timeout+design, **#424** U5 math render KaTeX→MathJax, **#425** doc-model read-at-arXiv-version (뷰어/citation-tree 잔여).
> - **#348 email — ✅ 결정+머지: SES 프로덕션 프라이머리** (2026-07-07, SES 프로덕션 액세스 승인). `compute_stack` `EMAIL_PROVIDER` `resend`→`ses` — **PR #427 merged to develop** (`d849c7c7`, admin-merge). SES는 태스크 IAM 역할 인증 → API 키 만료/로테이션 리스크 제거(2026-06-25 인시던트 클래스 소멸). Resend는 휴면 폴백(env 되돌리면 무배포 페일오버). 프로덕션 반영=다음 `cdk deploy Docsuri-Compute`.
> - **남은 결정/운영**: #345 perso shadow→real (v1 의도적 유예), #344 doc-model 큐 분리(결정), #347 잔여 ORCID/profile(결정), #343 DLQ drain 24건+native_html 10,660/21,252 (throttle 라이브=`cdk deploy` 후에만 안전), node24 upstream(차단).
> **Updated**: 2026-07-07 — **Phase 2 board reconcile** (post-refresh GitHub sweep):
> - ✅ **#341 SSR 500** — **closed** by PR #418 (SSR keep-alive를 ALB idle timeout에 맞춤 — 간헐 500의 근인). #353(logs)/#355(edge error page) 위에 근인 수정 랜딩. develop merged, main 승격 전.
> - ✅ **env-dependent `test_api_create_status_and_cancel`** — fake/live seam 고정(`branch fix/novelty-test-env-seam`): 앱쉘이 라이브 Bedrock/HTTP 어댑터를 `app.state.novelty_adapters`에 배선하고 무큐 디스패치가 워커를 인라인 실행 → ambient AWS creds가 종료 상태를 좌우하던 문제. Noop 어댑터로 오버라이드해 환경 무관 결정적 degrade. (51 novelty tests green)
> - ✅ **검색 품질 개선(charter phase 7)** — **PR #416 merged**(Cross-Encoder Reranker; 배포 차단 2건 크로스리전 배선+`bedrock:Rerank` IAM 해소, fail-soft RRF baseline 유지). 후속 **PR #419 open**(Cohere Embed Multilingual v3 재임베드 + region-decouple).
> - 🟡 **#343/#344 docmodel/backfill** — **PR #420 merged to develop** (admin-merge, `685ee2a`): arXiv 콜러 단일화(`docsuri-docmodel-builder` max_capacity=1, `lower=10` 버스트 스텝 제거) + CDK 계약 테스트. 드레인 시 DLQ 유입 억제. **남은 작업은 별도 프로덕션 뮤테이션**(라이브 `docsuri-docmodel-dlq` 24건 re-enqueue/드레인 · S3 native_html 10,660/21,252) — throttle이 라이브(다음 `cdk deploy`)여야 안전하게 실행. 큐 분리(#344)는 여전히 결정 대기.
> - 🟡 **#167 authz shared 계약** — **PR #422 open**: 인가 계약(`Principal`·`Action`·`Decision`·`AccountId`·`UserRole` + stateless `AuthorizationGuard`)을 accounts(U3) 내부→`docsuri_shared.authz`로 이전. 프로덕션 17곳+테스트 8곳 import rewire, accounts는 re-export(클래스 동일성 보존 → `except DomainException` 무회귀), moved-name leak=0. backend 236 tests green·ruff clean. SSOT 2건 back-sync(unit-of-work-dependency·shared-contracts-overview). 가드 stateless라 단일 권위 U3 의미 유지.
> - 🔴 **여전히 결정/운영 대기**: #345 personalization shadow→real(지표 판정), #348 email SES vs Resend(결정), #344 doc-model 큐 분리(결정), #347 잔여 ORCID/profile(결정).
> **Updated**: 2026-07-06 — **Phase 2 board refresh** (GitHub live sweep):
> - **main은 여전히 v1.9.0**. 이후 Phase 2 변경은 develop 머지/오픈 PR 상태이며 다음 main 승격 전까지 프로덕션 반영으로 간주하지 않음.
> - ✅ **#346 KPI funnel** — PR #403 merged to develop, issue closed.
> - 🟡 **#347 U10 mock 해소** — PR #407(최근 본 논문 실데이터) + PR #414(ORCID 로그인 버튼 기본 활성화) merged to develop, issue still open for residual ORCID/profile decision.
> - 🟡 **검색 품질 개선(charter phase 7)** — PR #416 open(Cross-Encoder Reranker). 배포 활성화는 rerank region/model ARN/IAM/model access 선결, fail-soft baseline 유지.
> - 🟡 **#341 SSR 500** — PR #353(logs) + PR #355(edge error page) done; root-cause fix PR still missing.
> - ✅ **Issue hygiene** — #187–#191 closed as shipped US-A3~A7 stories with evidence comments.
> - 🔴 **No dedicated PR yet**: #343 docmodel backlog self-heal, #344 pre-2026 backfill/autoscale/doc-model queue decision, #345 personalization shadow→real, #348 email strategy, #167 authz shared contract, `github-tag-action` node24 upstream bump, env-dependent `test_api_create_status_and_cancel`.
> **Updated**: 2026-07-06 — **Phase 1 COMPLETE** — 마지막 잔여 항목(PDF 첨부·원고, doc-model 경유) 프로덕션 반영:
> - ✅ **v1.8.0 — 사용자 PDF → doc-model MVP** (PR #390/#391/#392/#393 = PR0–3 + #394; main 승격 #395). 공유계약 동결(`userdoc:{uuid}` paperId · `upload:{ownerId}:{jobId}:{attachmentId}` recordRef · arXiv URL 무날조) → ingestion 신규 `BUILD_USER_DOC_MODEL` JobKind(S3-소스, arxivRef 없음) → backend 코디네이터(업로드·enqueue·폴링, best-effort 저하) → FE 소비. **#14 consume-on-retry**(PR #394): 원고 doc-model이 폴백 타임아웃보다 늦게 완성돼도 novelty 워커가 서버측 retry-until-ready(재큐 + DelaySeconds, 최대 8회)로 소비. pdfplumber 평문 doc-model(GROBID 미배선).
> - ✅ **v1.9.0 — GROBID 구조 추출** (#13 = PR #396 앱코드 + PR #397 인프라; main 승격 #398, **full deploy 완료 2026-07-06**). `build_user_doc_model`이 GROBID `extract_tei→build_from_tei`로 구조화 TEI(섹션/표/그림) 생성, 빈/오류 TEI는 pdfplumber 폴백(무회귀). **Option B 인프라**: 전용 `docsuri-userdoc-queue` + `docsuri-userdoc-builder` Fargate(자체 `grobid/grobid:0.8.0` 사이드카 + `/api/isalive` HEALTHY 게이트, cpu2048/mem8192/80GB) — lean `docsuri-docmodel-builder`(arXiv 뷰어 빌드)가 ~20GB GROBID 콜드풀을 떠안지 않게 분리. 생산자(API·novelty) 라우팅 `DOCSURI_USERDOC_BUILD_QUEUE_URL` + 코디네이터 팩토리 우선순위. **배포**: develop→main 릴리스(docsuri-ingestion·docsuri-api 이미지 재빌드 + ECS 롤) → `cdk deploy` Ingestion/Novelty/Compute → 라이브 검증(API rev27 라우팅 env ✅ · userdoc 워커 GROBID 배선 ✅ · CloudFront 200 · X-Origin-Verify 403 없음 · ECS 2/2). userdoc 워커 desired 0 → 첫 업로드가 실런타임 스모크(grobid 콜드풀 ~수 분).
> **Updated**: 2026-07-05 — Phase 1 execution, day 2:
> - ✅ **v1.7.0 promote & deploy** (PR #385, main `7b36d52`) — v1.6.0 이후 6개 PR(#379–#384) 승격: form_evidence 선행(#380)·Notion export(#382)·QT-8/QT-10 상시 게이트+저하 지표(#383)·physics 수식 매크로 렌더(#381, 유진)·로드맵 ×2. release.yml 자동 태깅 → GitHub Release → ECS 롤링 배포 전 잡 green. **Phase 1은 PDF(doc-model 경유)만 남기고 프로덕션 완료.** 마이그레이션 003(notion connections)은 API 기동 시 자동 적용; env `DOCSURI_NOTION_TOKEN_KEY` 설정 전까지 Notion export 휴면(연결 등록만 422 안전 저하). novelty DLQ 1건 purge 완료(0건 확인).
> - ✅ **P4 잔여 완주** (PR #380·#382·#383, develop `2d42f3f`) — **#251 form_evidence 선행**(자연어 잡이 D5 포트로 근거 묶음을 먼저 만들고 U2가 보강; abstain은 무날조 저하 소비), **#258 Notion export E2E**(토큰 Fernet 암호화 저장·미리보기→명시 승인→페이지 생성·실패는 FAILED 안전 수렴; env `DOCSURI_NOTION_TOKEN_KEY` 필요), **#273/#259 QT-8·QT-10 상시화**(날조 0건 평가셋·DTO 라운드트립·상태전이/실험계획/export 게이트) + `novelty.step_degraded{source}` 지표. 4개 스토리 auto-close. old-queue 확인: 구 큐는 이미 retired, DLQ 1건(pre-GA)만 purge 대기. `s3:PutObject`·bucket env는 live 검증 완료(allowed — #252 코멘트). **남은 Phase 1 항목은 PDF(doc-model 경유) 하나** — ingestion 신규 JobKind 설계 인계(#268/#252).
> - ✅ **v1.6.0 promote & deploy** (PR #378, main `a656d8a`) — v1.5.0 이후 10개 PR(#368–#377) 승격. release.yml 자동 태깅 → GitHub Release → ECS 롤링 배포 전 잡 green(API·Ingestion·FE 이미지 + 전 서비스). **Phase 1 P0–P3 프로덕션 반영.** 비차단 후속 1건: API 태스크 롤 `s3:PutObject` 확인 전까지 원고 업로드는 422 안전 저하(#252, 유진).
> - ✅ **P2-b merged** (PR #370): **#257 단계 상세 이벤트** — worker가 FE `timelineDetail` 계약 키(source/query/count/outputSummary/reason)로 도구·쿼리·발견 출처 수·저하 사유를 emit(검색 단계는 시작+완료 이벤트, LLM 단계는 draft 선완료라 시작 이벤트가 결과 수 동봉) + **#253 유사 연구 표 상세 칼럼**(문제정의·방법·데이터셋·결과·한계·겹치는 점). 리뷰 2라운드 반영: 상세 칸은 **필드별 근거**(`{value, sourceRefIndexes}`)가 유효할 때만 값 보존 — row 출처는 포괄 근거가 아니며 검증 불가 형상은 기권 null(B-001); SSE 경로도 REST와 동일한 payload→detail 매핑(N-001).
> - ✅ **P3 1차 슬라이스 merged** (PR #373): 에이전트 첨부 **처리 전 검증**(pdf/markdown/text 허용목록 · 10MB · 최대 8개 → 422 즉시 거부, #268/#297 AC) + **실배포 첨부 500 결함** 수정(FE 객체 vs 공유계약 `list[str]` 핸들 → 파싱단계 검증 + id 핸들 변환); 후속 커밋이 evidence async 경로의 핸들 보존까지 마감. 2차(presigned upload + doc-model ingestion + #252 E2E, CDK/IAM 동반)는 **#268 설계 코멘트로 유진 검토 대기**.
> - ✅ **#371 merged** (팀): summary worker crash 수정 + 수식/MathML sanitize + glossary 편집 UI 분리(CollapsibleTerms/GlossaryTermEditor) + renderMath 보강.
> - ✅ **#372 merged** (팀 ELSAPHABA): novelty Bedrock을 `invoke_model_with_response_stream`으로 전환 + read_timeout 45s→300s — 장시간 draft 타임아웃 완화. #370과의 충돌(test_novelty·audit) 해소 및 칼럼 테스트 fake의 스트리밍 계약 이식 후 머지.
> - ✅ **세션 재열람·초기화 마감** (PR #375): 코드 검증 결과 #271(재열람·Postgres 영속·owner 격리)은 **이미 완성** — 증빙 코멘트 후 close 판단은 리드에. 남은 공백 **전체 초기화**(US-EV8 AC2: 소유자 벌크 `DELETE /jobs` 양 모듈 + 드로어 2단계 확인) 구현 + 조사 중 발견한 **novelty SQL 삭제 고아 행 결함**(FK cascade 부재로 이벤트·메시지·아티팩트·export 잔존, SEC-14) 수정. #272 closed.
> - ✅ **P3 2차 merged** (PR #376): 첨부·원고 **본문 E2E** — evidence md/txt 첨부가 근거 **추출 대상 문서**로 포함(corpus 비어도 진행, INV-EV-3 유지; 본문 없는 첨부는 '[첨부 안내]' 별도 메시지), novelty 원고 잡 **디스패치 보류 → `POST /jobs/{id}/manuscript`(S3 적재·objectKey 바인딩) → 분석 시작**(US-NV2 md/txt 관통, FE 실배포 게이트 제거). presigned-PUT 설계안 대신 본문 동봉(≤256KiB)+서버 적재로 인프라 협의 없이 레포 내 완결.
> - ⏭️ Remaining Phase 1 — see §3: **PDF 첨부·원고**(doc-model 파이프라인 경유, Q6=A)만 남음 — 빌드 계약이 arXiv 전용이라 ingestion에 S3-소스 JobKind 신설 필요(3-서비스, GROBID env 게이트), #268/#252에 설계 인계.
> _Prev 2026-07-04 pm — NFR-C1 비용 거버넌스 v1.5.0 (PR #364, 유진 `40d545d`); #339 close (PR #365); #293/#295/#296/#298 close; summary worker 5th ECS unit + **v1.5.0 승격** (PR #366/#367, 5유닛 안정); novelty FE 렌더러 (PR #368). am — v1.4.0 승격 (PR #360); CI node24 (PR #361); #338/#349 에이전트 merge; #353/#355/#357 오픈; #351 merge. 07-03 — #337 merge; #349 오픈._
> Snapshot of where the product stands against the team's initial plan, and the path to
> production-level completion of our goals. Tracking references: #251–#416 where cited below.

## 1. Status vs. the initial plan

| Plan item | Status | Notes |
|---|---|---|
| 논문 검색 | ✅ Live | Hybrid search over ~1.5M-chunk corpus; daily auto-harvest (EventBridge 15:00 KST); pre-2026 historical drain in progress |
| 논문 요약/번역 | ✅ Live | Grounded summaries/translation; glossary redesign (PR #334); source-anchor structural resolution + stale-docmodel self-heal (PR #351); tool-use structured output (PR #356, shipped v1.4.0); summary worker now its own ECS unit (PR #366, **v1.5.0**) — 무한 pending 사고 클래스 prod 종결; worker crash + 수식/MathML sanitize + glossary 편집 UI (PR #371, **v1.6.0**); physics 패키지 수식 매크로 렌더 — **PR #381, v1.7.0**(유진, #371 후속) |
| 프로필 페이지 | 🟡 Live w/ residual | U10 merged; 최근 본 논문 실데이터 PR #407 + ORCID 로그인 버튼 기본 활성화 PR #414는 develop merged, main 승격 전. #347 still open for residual ORCID/profile decision |
| 인용 그래프 → 각주 트리 | ✅ Live | DOI node expansion 500 fixed — **PR #357** (provider fail-closed) shipped **v1.5.0**, #342 closed |
| 트렌드/알림 | ❌ Not started | Never entered requirements — needs inception re-entry |
| 구독제 | ❌ Not started | Never entered requirements — needs inception re-entry |
| 로그 수집 | ✅ Live | U9 collection healthy (944 events/7d, 0 failures); KPI funnel dashboard + read-complete instrumentation PR #403 merged to develop, #346 closed (main promotion pending) |
| 개인화 추천 | 🟡 Shadow | Search boost applied in shadow mode (PR #300); go-live judgment pending (#345); US-P5 deferred |
| 에이전트: 문헌탐색/근거형성 | ✅ Live (v1.4.0) | PR #338 shipped v1.4.0; **cost-governed since v1.5.0** (PR #364); 근거 카드 + `§` 인용 앵커 (#339, PR #365); 첨부 검증 422 + 500 수정 (PR #373); **첨부 본문 근거 추출 포함** (PR #376) + **세션 재열람·삭제·전체 초기화** (PR #375) — **모두 v1.6.0 배포**; **QT-8 근거화 평가셋 상시화** (#273, PR #383, **v1.7.0**). **PDF 첨부(doc-model 경유) ✅ v1.8.0 MVP + v1.9.0 GROBID(#13)** — Phase 1 완료 |
| (charter add) 연구아이디어 novelty 에이전트 | ✅ Live (v1.4.0) | PR #349 shipped v1.4.0; cost-governed since v1.5.0 (PR #364: draft-gate + 5/day quota). FE 아티팩트 렌더러 (PR #368) + **P2-b merged** (PR #370) + **Bedrock streaming·timeout 300s** (PR #372) + **원고 업로드 E2E** (PR #376: 디스패치 보류→본문 적재→분석) — **모두 v1.6.0 배포**; **form_evidence 선행**(#251, PR #380) + **Notion export**(#258, PR #382) + **QT-10·소스별 저하 지표**(#259, PR #383) — **모두 v1.7.0 배포**. **PDF 원고(doc-model 경유) ✅ v1.8.0 + v1.9.0 GROBID(#13)** — Phase 1 완료 |
| 웹검색 레퍼런스 (고려) | ❌ Not started | Novelty agent has GitHub+datasets search; web/news deferred to next cycle |
| 온보딩 (고려) | ❌ Not started | Candidate fix for personalization cold-start |

Infra baseline: CI/CD hardening merged (#304/#305), main promotion + v* tag CD path live.
Production deploys now go through CI on main push — the manual-buildx era is over.

## 2. Phase 0 — This week: protect prod, land the agent

| # | Action | Tracking |
|---|---|---|
| 1 | ✅ **PR #337 merged** (2026-07-03 13:00 UTC) — revert-on-promote trap closed | PR #337 |
| 2 | ✅ **PR #338 merged** (`f12990d`, 2026-07-04) — #359 landed all 4 blockers + whitespace + multi-turn context; independently re-reviewed → APPROVED. Attachments → tracked follow-up | PR #338, #359 |
| 3 | ✅ **Promoted develop→main → `v1.4.0`** (2026-07-04) — PR #360 merged (`45651d0`); `release.yml` auto-tagged `v1.4.0` (ships #351 anchor, #356 tool-use, #338 evidence agent, #349 novelty agent), `cd.yml` ECS rolling deploy | #340 · `v1.4.0` |
| 4 | ✅ **#339 closed** (PR #365, 2026-07-04) — 근거 카드 + `§` 인용 앵커 렌더링 + screen-level evidence-card test; shipped in v1.5.0 | #339 · PR #365 |

## 3. Phase 1 — Weeks 1–2: agent GA (the 차별화)

The differentiator is **built and shipped — Phase 1 complete (v1.9.0, 2026-07-06)**. Focus now shifts to Phase 2 (production hardening, §4).

**Execution board (2026-07-05)** — verified against code+tests, not docs (board sweep: 4 stories DONE→closed, rest partial):

| Step | Status | Notes |
|---|---|---|
| P0 · Cost gates (NFR-C1) | ✅ **v1.5.0** | PR #364 — CostGuard on both agent Bedrock paths, real spend recorded from invocation metrics, critical-tier `[abstain] cost_degraded`, per-user daily quotas (evidence 30 · novelty 5; Redis-shared, fail-open) |
| P1 · #339 + story hygiene | ✅ **v1.5.0** | PR #365 (근거 카드 + `§` 앵커 + screen test); #293/#295/#296/#298 closed with evidence comments |
| P2-a · Novelty FE renderers | ✅ **v1.6.0** | PR #368 (`233aac1`) — #253–#256 FE half |
| P2-b · Novelty backend | ✅ **v1.6.0** | PR #370 — #257 단계 상세 이벤트(timelineDetail 계약) + #253 표 상세 칼럼; 리뷰 2라운드로 **필드별 근거 강제**(B-001) + SSE detail 매핑(N-001). 같은 날 PR #372(Bedrock streaming + timeout 300s)와 통합 |
| P3 · Attachments E2E | ✅ **v1.6.0** | 1차 (PR #373): 처리 전 검증(422) + 첨부 500 결함 + async 핸들 보존. 2차 (PR #376): **본문 E2E** — evidence 첨부(md/txt) 추출 대상 포함 · novelty 원고 업로드 관통(#252 md/txt). `s3:PutObject`+bucket env ✅ live 검증(allowed). 후속 ✅ **PDF 본문**(doc-model 경유): v1.8.0 MVP(#390–#394, pdfplumber) + v1.9.0 GROBID 구조(#13: #396/#397, Option B 전용 워커+사이드카) — **Phase 1 완료** |
| P4 · Residue | ✅ **v1.7.0** | 세션(#271/#272) ✅ PR #375·v1.6.0 (둘 다 closed). #251 form_evidence 선행 ✅ PR #380 · #258 Notion export ✅ PR #382 · #273/#259 QT-8/QT-10+지표 ✅ PR #383 (4개 스토리 auto-close, **v1.7.0 배포**). old-queue ✅ 확인 — 구 큐 retired·현행 큐 0건·DLQ purge ✅ 완료(0건 확인) |

## 4. Phase 2 — Weeks 2–4 (parallel): production hardening

Ordered by user impact:

| Status | Item | Tracking |
|---|---|---|
| ✅ Develop merged | Intermittent SSR 500 on paper pages — **PR #353** enables ALB/CloudFront access logs (step ①); raw-500 exposure handled at the edge by **PR #355** branded CloudFront error page (step ②); root-cause fix **PR #418** aligns SSR keep-alive with the ALB idle timeout (step ③, #341 closed). develop merged, main promotion pending. | #341 · #353 · #355 · #418 |
| ✅ Done | 각주 트리 DOI node expansion 500 — **PR #357**: S2 200-with-bad-body was fail-open (parse escaped the `httpx`-only guard → app 500); now fail-closed to Unavailable at both the provider parse and tree assembly (BR-CG12). Regression tests exercise the real provider path the old suite bypassed via FixtureProvider. | #342 · #357 |
| 🟡 Develop merged | Docmodel backlog self-heal — **PR #420 merged** throttles the arXiv caller to one task (`max_capacity=1`, `lower=10` burst step removed) so drains stop feeding the DLQ. Remaining: the re-enqueue/DLQ drain itself is a separate prod mutation (live: DLQ 24 msgs · S3 native_html 10,660/21,252), safe only once the throttle is live via `cdk deploy`. | #343 · #420 |
| 🟡 Develop merged | Finish pre-2026 backfill drain → restore ingestion autoscale — **PR #420** landed the prerequisite throttle; queue-separation decision (#344) still open. | #344 · #420 |
| 🔴 No PR | Personalization shadow→real flip after metric review; then US-P5 + keywordWeights. | #345 |
| ✅ On main (v1.10+) | KPI funnel dashboard (AI 호출 > 검색 > 완독률) from existing U9 events — **PR #403** merged; #346 closed; **promoted to main**. | #346 · #403 |
| 🟡 On main, residual decision | U10 mypage mocks: 최근 본 논문 실데이터 **PR #407** + ORCID 로그인 버튼 기본 활성화 **PR #414** **on main (v1.10+)**; #347 remains open only for residual ORCID/profile decision. | #347 · #407 · #414 |
| ✅ Merged to develop (PR #427) | Email → **SES production-primary** (AWS prod access granted 2026-07-07). `EMAIL_PROVIDER=ses`; SES auth via task IAM role (no API key to expire → retires 2026-06-25 incident class); Resend kept as dormant deploy-free fallback. **PR #427 merged** (`d849c7c7`); live on next `cdk deploy Docsuri-Compute`. | #348 · #427 |
| 🟡 PR open | Authz contract → `docsuri_shared.authz` refactor — **PR #422**: Principal/Action/Decision/AccountId/UserRole + stateless guard 이전, accounts re-export(클래스 동일성 보존), 소비자 17 + 테스트 8 rewire, leak=0, backend 236 tests green. | #167 · #422 |
| ✅ Develop merged | 검색 품질 개선 (charter phase 7) — **PR #416 merged** (Cross-Encoder Reranker; cross-region wiring + `bedrock:Rerank` IAM blockers cleared, fail-soft keeps RRF baseline). Follow-on **PR #419 open** (Cohere Embed Multilingual v3 re-embed + region-decouple). | #416 · #419 · charter |
| ✅ Closed | Issue hygiene: shipped US-A3~A7 stories closed with evidence comments (#187–191). | #187 · #188 · #189 · #190 · #191 |
| ⏸️ Blocked | `mathieudutour/github-tag-action` node24 bump — blocked on upstream release (rest of CI on node24 since PR #361). | — |
| ✅ Done | Env-dependent `test_api_create_status_and_cancel` — fake/live seam pinned: the app-shell wired live Bedrock/HTTP adapters into `app.state` and the no-queue dispatch ran the worker inline, so ambient AWS creds decided the terminal state. Overridden with Noop adapters for a deterministic degrade (51 novelty tests green). | `fix/novelty-test-env-seam` |

## 5. Phase 3 — Month 2: growth scope (requires inception re-entry)

Recommended order; none of these have requirements coverage today:

1. **온보딩** — smallest scope; seeds U9 keyword signals at signup, solving
   personalization cold-start.
2. **트렌드/알림** — email digest of new papers in followed topics. Cheapest version
   reuses the daily harvest + existing email path. Builds the retention loop 구독제
   needs.
3. **웹검색 레퍼런스** — implement as an evidence-agent *tool* (web/news search was
   already deferred to next cycle in the novelty charter), not a standalone feature.
4. **구독제** — deliberately last: agent LLM cost per user is the natural paid
   boundary, but pricing needs Phase 1 live + Phase 2's KPI funnel for real per-user
   Bedrock spend. Payment-provider decision via requirements re-entry.

## 6. Sequencing rationale

Ship the differentiator first (it's nearly done) → harden what users already touch →
build the retention loop → monetize with real cost data. Trends/subscription before the
agent would monetize an undifferentiated product; the KPI funnel (#346) is the cheap
instrument that keeps Phase 3 decisions honest.
