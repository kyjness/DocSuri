# U7 Summarization Frontend — Business Rules (Functional Design)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U7 Summarization Frontend · **일자**: 2026-06-19
**근거**: 계획서 확정 8문 · 백엔드 계약 `POST /api/summarize` · SSOT 2026-06-19 개정 · `frontend/CLAUDE.md`(발명 금지·XSS·안전링크·토큰 비노출).
**원칙**: 클라이언트 측 **결정·검증·표시 규칙**만. 모델·근거화·캐시 생성은 백엔드 권위(여기선 표시·요청 구성).

---

## 요청 구성

- **BR-SF-1 (탭 트리거)**: 카드/상세의 요약·번역 호출은 **사용자 액션 탭 시에만** 발생. 카드 렌더만으로 LLM 호출 0(검색 결과 비용 폭주 방지). 근거: SSOT §5, Q1.
  - **편차(2026-06-19, components.md §0)**: 본문 중심 상세에서 **전문(`getFullText`)은 상세 진입 시 자동 로드**(탭 불필요). 전문 조회는 LLM 호출이 아니고 단일 상세 페이지 한정이라 비용 폭주 위험이 없다 — **요약/번역은 여전히 탭 시에만**.
- **BR-SF-2 (요청 매핑, Q8=A)**: `paperId = ResultCardVM.arxivId`, `version = 1`, 추가 본문 없음. 백엔드가 `paperId`로 S3 전문을 참조. 번역(scope=abstract)에서 `abstract`가 필요하면 카드 스니펫이 아니라 백엔드 보유 초록을 사용(스니펫 전송 금지).
- **BR-SF-3 (액션→파라미터, Q6)**:
  - [요약] → `{ task:"summary", persona }`(scope 무시/full 고정)
  - [초록 번역] → `{ task:"translate", scope:"abstract" }`
  - [전문 번역] → `{ task:"translate", scope:"full" }`
- **BR-SF-4 (중복요청 디듀프)**: 동일 `(paperId,version,task,scope,persona)` 진행 중 재탭은 새 요청을 만들지 않고 진행 중 상태를 표시.

## 캐시 · 비용

- **BR-SF-5 (캐시 표기)**: 응답 `cached:true`면 즉시 표시·"저장된 결과" 표기, 로딩 스피너 생략. persona 전환·재방문이 캐시 히트면 추가비용 0(SSOT §11).
- **BR-SF-6 (persona 전환, Q4=A)**: persona 토글은 **요약 표면에만** 노출. 전환 = 해당 persona로 재요청(캐시 히트 즉시). 번역에는 persona 미적용(단일). 근거: SSOT §9.2.
- **BR-SF-3b (전문 번역 비용 인지)**: 전문 번역은 시간·비용 큼 → 명시 버튼 + 로딩 인디케이터. **하드 게이트(차단 모달) 없음** — 온디맨드+영구저장으로 bounded(SSOT §8).

## 상태 · 안전

- **BR-SF-7 (상태 우선순위)**: `abstain`/`source_unavailable`/`cost_degraded`는 부분 렌더보다 **우선** — 근거 없는/불완전 출력을 사용자에게 노출하지 않는다. 각 상태는 **고유 메시지**(기권 ≠ 소스부재 ≠ 비용저하).
- **BR-SF-8 (앵커→전문뷰어, Q5=C)**: `AnchorChip` 클릭 → `FullTextViewer` 열고 `target`/`span` 위치 하이라이트·스크롤. 뷰어 텍스트는 백엔드 `getFullText` 반환분.
- **BR-SF-9 (XSS)**: 모든 외부 텍스트(요약 6필드·span·번역 koreanText·전문 텍스트·keptTerms)는 React 기본 이스케이프로 렌더. `dangerouslySetInnerHTML` 금지. 근거: `frontend/CLAUDE.md` Part 2-B.
- **BR-SF-10 (날조 0 · 표시 무가공)**: 표시 측은 백엔드 근거화(BR-S7) 통과분만 받는다 — 앵커·수치를 클라이언트가 합성/보정하지 않는다. 빠진 필드는 빈 상태로 두되 지어내지 않는다.
- **BR-SF-11 (라이선스 게이트, 전문뷰어)**: `getFullText`가 `license_unavailable`이면 뷰어를 열지 않고 "원문은 arXiv에서 보세요" 링크아웃 안내(영문 원문 재배포 금지). 근거: SSOT §1·§7(라이선스).
- **BR-SF-12 (정규화 텍스트 안내)**: 전문뷰어 텍스트는 참고문헌·헤더·저자정보가 제거된 정규화본임을 표기(원문 레이아웃과 다름).
- **BR-SF-13 (안전 링크)**: arXiv 등 외부 링크는 http/https만(`safeHref`) + `rel="noopener"`. 근거: BR-U5-7.

## 비-해피 · 복원력

- **BR-SF-14 (전수 매핑)**: 응답 union(ok-summary·ok-translation·abstain·cost_degraded·source_unavailable) + loading·invalid·error를 빠짐없이 screenState로 매핑(누락 0). 무한 로딩 금지.
- **BR-SF-15 (재시도)**: `error`/`cost_degraded`는 재시도 경로 제공(`onRetry`). `abstain`/`source_unavailable`은 정상 동작이므로 자동 재시도 안 함(안내만).
- **BR-SF-16 (토큰/내부값 비노출)**: 응답의 토큰·비용·캐시키·모델ID는 표시하지 않는다(백엔드 SEC-9 화이트리스트 준수, 클라이언트도 노출 금지).
- **BR-SF-17 (개인 용어집 편집, BR-S4)**: `TranslationView`의 `keptTerms[]` 배지에서 "내 번역어"를 저장(`POST /api/glossary`)하고 재오픈 시 저장값을 미리채운다(`GET /api/glossary`). 동시 1개 편집창·바깥 클릭/Esc 닫힘. 저장 성공은 "다시 번역하면 반영" 안내(즉시 재번역 강제 아님), 저장값 조회 실패는 미리채우기 생략으로 degrade(무한 로딩 없음). 입력은 길이 제한·trim, 외부 텍스트 이스케이프(BR-SF-9). 적용 범위: 후치환 경로라 **번역에 반영**(요약은 프롬프트 강제 용어만, BR-S4·§3.5).
