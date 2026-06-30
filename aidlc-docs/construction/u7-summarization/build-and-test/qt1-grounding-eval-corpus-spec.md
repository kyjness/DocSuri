# U7 — QT-1 Grounding 충실도 평가 코퍼스 스펙 (held-out, OP/팀 인계)

**단계**: CONSTRUCTION → Build & Test (QT-1) · **유닛**: U7 Summarization · **일자**: 2026-06-29
**상태**: 🟡 인계 스펙 — **코퍼스 데이터는 OP/팀 소유**(미구축). 하니스·시드 스캐폴드는 완료.
**근거**: 워크플로 플랜 §모듈 업데이트 2·4, NFR Requirements §9, `summarization/eval/`(`grounding_eval.py`·`seed_cases.py`), `domain/grounding.py`.

---

## 1. 왜 필요한가 (데이터 게이트)

수치 임계 재보정(`_NUMERIC_MISMATCH_THRESHOLD`, 현재 `0.5` 무보정 추정값)과 matcher 정밀화는
**평가 데이터 없이 조정하면 회귀**한다 — 너무 조이면 과민 기권(grounded 요약을 버림), 너무 풀면
날조 통과. 이 둘은 본 코퍼스가 생기기 전까지 **착수 금지**(플랜 데이터 게이트). 하니스(`run_grounding_eval`)는
이미 준비됐으므로, 본 스펙대로 라벨 코퍼스만 채우면 재보정이 잠금 해제된다.

## 2. 소유·경계

- **소유 = OP/팀**(시드 `eval/seed_cases.py`는 하니스 구동용 스캐폴드일 뿐, 코퍼스 아님).
- **held-out·동결**: 재보정에 쓰는 셋은 동결(임계를 데이터에 과적합하지 않도록). 시드와 분리 보관.
- U7(개발)은 **출력 표면**(하니스·`GroundingValidator`·앵커/기권 결정)만 제공, **평가 실행·라벨 권위는 OP/팀**.

## 3. 케이스 형식 (하니스 계약)

각 케이스 = `GroundingEvalCase`(`eval/grounding_eval.py`):

| 필드 | 형식 | 의미 |
|---|---|---|
| `name` | str | 고유 식별 |
| `gi` | `GroundingInput(draft: SummaryDraft, refined: RefinedSource)` | 검증 입력(요약 초안 + 정제 원문) |
| `expected` | `"faithful" \| "fabricated"` | 리뷰어 라벨 — faithful=통과 기대, fabricated=기권 기대 |
| `rationale` | str | 라벨 근거(감사 앵커) |
| `confident` | bool | 라벨 안정성(임계 probe는 `False`) |

- `SummaryDraft`/`RefinedSource` 실제 형태는 `domain/models.py` 참조(앵커=`{field_name,target∈{section\|table\|figure},span,label}`).
- 실 논문에서 추출하되 **PII/저작권 본문 무분별 저장 금지**(SEC-3) — 필요한 span만.

## 4. 하니스 소비 · 산출 지표

```python
from summarization.eval.grounding_eval import run_grounding_eval
report = run_grounding_eval(HELD_OUT_CASES)   # validator 미지정 시 실 GroundingValidator
report.false_pass      # fabricated인데 통과 = 날조 누출 (최악, 목표 0)
report.false_abstain   # faithful인데 기권 = 과민 기권 (UX 손상, 목표 0)
```
순수·결정적(LLM 0콜) — CI 회귀로 안전.

## 5. 커버리지 목표 (재보정·matcher 정밀화를 가르려면 필수)

- **수치 임계 스윕**: ungrounded 비율을 `0.0 … 1.0`로 분포(특히 **0.3–0.7 경계 밀집**) — false_pass↔false_abstain 곡선을 그려 strict 값 선택. 현 probe(`probe_half_ungrounded`, 0.5)는 시작점.
- **반올림/단위 변형**(matcher 정밀화 대상): `95.3%↔0.953`, `1.2e3↔1200`, 반올림 오차(`95.34↔95.3`), 천단위 구분(`1,200`), 유효숫자 — 현 `_normalize_number`가 못 잡는 케이스를 라벨해 정밀화 근거 확보.
- **앵커 SOFT 드롭 엣지**: 표 재구성·패러프레이즈·수식 span(LaTeX↔유니코드) — 드롭은 되되 기권은 안 돼야(faithful 유지).
- **HARD 기권 경로**: 빈/잘림·스키마 미완 — 기권 확정(fabricated).
- **헤드라인 vs 부수 수치**(선택): 핵심 결과 수치 날조 가중 여부 판단용.

## 6. 재보정 절차 (코퍼스 확보 후, 데이터 게이트 해제 시)

1. held-out 셋으로 `run_grounding_eval` → false_pass/false_abstain 측정(현 `0.5` 기준선).
2. `sweep_numeric_threshold(cases, thresholds)`로 곡선 작성 → **날조 0 우선, 과민 기권 최소** strict 값 선택.
3. matcher 정밀화(반올림 톨러런스·단위 정규화)는 **완료**(`_number_grounded`/`_source_values`) — 적용 후 false_abstain 재측정.
4. 변경은 `domain/grounding.py`(`GroundingValidator(numeric_mismatch_threshold=...)` 기본값)만 — FROZEN 계약 무변경. 회귀=`test_grounding_eval` 확장.
5. 결과를 NFR Requirements §9·본 스펙에 back-sync.

> **2026-06-29 현황(합성 분석)**: `eval/numeric_corpus.py`(프랙션 스펙트럼·합성)로 스윕한 결과 — 안정 라벨 기준 0.5는 [0.25, 0.66] 구간 안전, 정책 민감 경계("정확히 절반 미검증=날조?")만 0.4~0.49에서 잡힘. **결정: 0.5 유지·실 held-out 논문 코퍼스 확보까지 변경 보류**(합성 데이터로 운영 튜닝값 변경 안 함). 분석 인프라(스윕·임계 주입·단조성 회귀 테스트)는 완비 — 실 코퍼스만 채우면 재보정은 기본값 한 줄 변경.

> **2026-06-29 갱신(실 수치 코퍼스 재보정)**: `eval/real_corpus.py` 신설 — **실제 arXiv 논문 8건**(BERT·ResNet·ViT·RoBERTa·EfficientNet·CLIP·GPT-3·T5)의 Results/Table **수치 span을 verbatim 발췌**해 ground-truth로 삼고, faithful=실수치 인용/fabricated=통제된 비율 치환으로 18케이스(confident 14 + 정책 probe 4) 구성(SEC-3: 본문 통째 저장 안 함, 필요한 수치 span만). 스윕: **confident 안전 평지=[0.25, 0.51]** — 합성(0.66)보다 **상단이 0.51로 좁혀짐**(실제 0.60 프랙션 날조 케이스 ViT 3/5 존재 → 0.5 위로 못 올림). 0.5는 안전 평지 **상단 끝**, confident 14/14 무누출·무과민기권(`false_pass=false_abstain=0`). 0.45가 정책 probe 포함 18/18을 완벽 분류하나 이는 "**정확히 절반 미검증=날조**" 정책 채택 시에만 유효 — **결정(리뷰어/정책): 0.5 유지**. ⚠️ 한계: 원문 수치는 실데이터지만 faithful draft는 구성된 것이라 운영 draft의 자연 matcher-miss율을 과소평가 → 0.45 조임은 corpus에 안 보이는 과민기권 위험. 회귀=`tests/test_real_corpus.py`(안전 평지·절반-미검증 probe·단조성 잠금).

## 7. 포인터

- 하니스·스윕: `backend/modules/summarization/src/summarization/eval/grounding_eval.py`(`run_grounding_eval`·`sweep_numeric_threshold`)
- 시드(스캐폴드): `…/eval/seed_cases.py` · 수치 프랙션 코퍼스(합성): `…/eval/numeric_corpus.py` · 실 수치 코퍼스(arXiv 발췌): `…/eval/real_corpus.py` · 회귀: `tests/test_grounding_eval.py`·`tests/test_real_corpus.py`
- 검증기·임계: `…/domain/grounding.py`(`_NUMERIC_MISMATCH_THRESHOLD=0.5`·`_normalize_number`)
- 관련: NFR Requirements §9 · 워크플로 플랜 QT-1 항목
