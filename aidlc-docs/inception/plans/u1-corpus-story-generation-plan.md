# U1 Corpus 스토리 개정 계획

**단계**: INCEPTION -> 사용자 스토리(Part 1/2)
**일자**: 2026-06-26
**입력**: `requirements.md` U1 Corpus 개정, 기존 `stories.md`, `personas.md`

본 계획은 기존 인제스천 스토리를 U1 Corpus 요구사항에 맞게 갱신하는 최소 계획이다. 신규 에픽/신규 페르소나는 만들지 않는다.

## 계획 결정

## PQ1 - 스토리 배치
A) **기존 에픽 4 인제스천을 갱신(권장)** - 기존 US-I1~I3가 같은 책임을 이미 담고 있다.

[Answer]: A

## PQ2 - 스토리 입도
A) **기존 3개 스토리 유지(권장)** - Corpus 구축, 증분 최신성, 복원력으로 충분하다.

[Answer]: A

## PQ3 - 페르소나
A) **기존 P1/OP 유지(권장)** - 사용자는 검색 커버리지, OP는 운영/비용을 본다.

[Answer]: A

## Part 2 실행 체크리스트
- [x] `stories.md`의 US-I1을 멀티소스 Corpus + eager DocModel + DocModel(Block) 인덱싱으로 갱신.
- [x] `stories.md`의 US-I2를 source별 watermark incremental update로 갱신.
- [x] `stories.md`의 US-I3/US-R3/US-R4 추적성을 retry/DLQ/비용/관측 기준으로 보강.
- [x] `personas.md`의 OP 책임에 Corpus 운영·eager 비용·DLQ 관측을 반영.
- [x] FR/품질 추적성 표에 FR-18, QT-9, U1 NFR-C1 보강을 반영.

## 확장 규칙 준수 요약
- **Security Baseline**: 적용. PDF 원문 미저장·라이선스 미허용 배제를 스토리 기준에 유지한다.
- **Resiliency Baseline**: 적용. source별 watermark, retry/DLQ, stage failure signal을 스토리에 포함한다.
- **Property-Based Testing Partial**: 적용. QT-9 불변식을 추적성에 연결한다.
