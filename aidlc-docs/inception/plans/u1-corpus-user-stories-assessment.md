# U1 Corpus 사용자 스토리 실행 평가

**단계**: INCEPTION -> 사용자 스토리(Part 1: 평가)
**일자**: 2026-06-26
**대상**: 재인셉션 페이즈 1 / U1 Corpus 생성 파이프라인

## 요청 분석
- **원 요청**: PR #220 머지 후 U1 Corpus 생성 파이프라인 다음 AIDLC 단계 진행.
- **요구사항 입력**: `requirements.md`의 FR-6, FR-18, NFR-C1, RES-7/8/9, QT-9, C-1, §12.
- **사용자 영향**: 간접. 검색/요약/에이전트가 쓰는 코퍼스 범위와 근거 품질이 바뀐다.
- **복잡도**: 중간 이상. 멀티소스 수집, dedup, eager DocModel, 인덱스 전환, 비용/운영 게이트가 함께 바뀐다.
- **이해관계자**: P1 연구자, OP 운영자.

## 충족된 평가 기준
- [x] **High Priority - 신규 제품 기반 역량**: 검색/요약/에이전트의 데이터 기반이 arXiv 단일에서 멀티소스 Corpus로 확장된다.
- [x] **Medium Priority - Backend user impact**: 사용자가 보는 검색 커버리지와 근거 앵커 품질에 직접 영향을 준다.
- [x] **Medium Priority - Data changes**: DocModel(Block) 기반 인덱스와 `(paperId, version)` 정합이 필요하다.
- [x] **Medium Priority - Operations/testing**: source별 watermark, retry/DLQ, eager 비용 상한, QT-9 불변식이 필요하다.

## 결정
**사용자 스토리 실행**: 예

**근거**: 기능 UI가 아니라 데이터 파이프라인 변경이지만, 검색·요약·에이전트 품질의 전제라 기존 인제스천 스토리를 갱신해야 한다. 새 에픽은 만들지 않고 기존 US-I1~I3와 OP 운영 스토리만 최소 수정한다.

## 기대 산출
- 기존 인제스천 에픽의 arXiv 단일 표현 제거.
- FR-6/FR-18/NFR-C1/RES-7/8/9/QT-9 추적성 보강.
- OP 페르소나에 Corpus 운영·비용 관측 책임 반영.
