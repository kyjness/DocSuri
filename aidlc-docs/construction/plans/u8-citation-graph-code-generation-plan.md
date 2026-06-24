# u8-citation-graph-code-generation-plan.md — Code Generation 계획 + 승인 게이트

**단계**: CONSTRUCTION -> Code Generation (유닛별 루프)  
**유닛**: U8 Citation Graph  
**일자**: 2026-06-21  
**근거**: `construction/u8-citation-graph/functional-design/`, `nfr-requirements/`, `nfr-design/`, `infrastructure-design/`

> 본 계획서는 승인 게이트다. 승인 전에는 앱 코드를 생성하지 않는다.

## 1. 구현 범위

- Backend only.
- FE paper-detail 버튼/화면은 제외.
- Provider는 Semantic Scholar 단일.
- Redis snapshot은 기존 cache 경로가 있으면 재사용하고, 없으면 최소 adapter를 둔다.
- 기본 테스트는 fixture provider만 사용한다.

## 2. 생성 계획

- [x] backend U8 module skeleton
- [x] request/response DTOs
- [x] Semantic Scholar fixture/provider boundary
- [x] Redis snapshot store
- [x] bounded tree builder
- [x] FastAPI routes behind feature flag/auth guard
- [x] U4 save gateway adapter
- [x] U6 telemetry emission
- [x] unit/property/API tests with fixture provider
- [x] opt-in contract test stub

## 3. 승인 질문

Code Generation을 시작할까요?

A) **계획대로 backend-only U8 코드를 생성한다.** (권장)

B) 코드 생성 전에 계획을 수정한다.

X) 기타.

[Answer]: A
