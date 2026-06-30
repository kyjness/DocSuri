# U7 Summarization — Unit Test Execution

**단계**: CONSTRUCTION → Build & Test · **유닛**: U7 Summarization · **일자**: 2026-06-19

## Run Unit Tests
```bash
cd backend/modules/summarization
PYTHONPATH="src:../../../shared/python/src" python -m pytest -q
```
(또는 `uv run pytest`.) real-first: 단위 테스트는 **테스트 전용 Fixture/Stub**(`tests/stubs.py`)만 사용 — Bedrock/S3/Redis/RDS 불필요.

## 결과 (2026-06-29 실측)
- **127 passed · 3 skipped**(통합 self-skip) — 2026-06-19 이후 멀티모달·구조화 번역·페이즈 3 추가분 포함. 아래 표는 대표 파일(전수 아님).

| 파일 | 테스트 | 커버 |
|---|---|---|
| `test_domain_refiner.py` | 3 | BR-S3/Q2/Q6 — 노이즈 제거·캡션/Appendix/수치 보존·섹션 도출 |
| `test_domain_glossary.py` | 4 | BR-S4/Q8 — 후치환(한국어 조사 안전)·멱등·keep-as-is·prompt-enforced 미치환 |
| `test_domain_grounding.py` | 4 | BR-S7/Q4/Q15 — 통과·가짜 앵커·수치 불일치·스키마 미완 |
| `test_domain_source_cache_length.py` | 6 | Q1 소스 폴백·BR-S1 immutable 키·Q3 길이 분기 |
| `test_orchestrator.py` | 7 | 캐시 HIT·비용 저하·소스부재·요약 OK·근거화 실패→1회 재시도→기권·LLM 장애→복구·번역 |
| `test_pbt.py` | 5 | PBT-S1 키 결정성·S2 정제 멱등·S3 후치환 멱등·keep-as-is 불변·S4 SEC-9 라운드트립 |
| `test_grounding_registry.py` | 2 | D3 — U7 validator를 `summary`/`advisory`로 등재·`summary`의 enforcement 주장 거부(단일권위=검색) |
| `test_grounding_eval.py` | 5 | QT-1 — 하니스 집계 math(false_pass/false_abstain)·confident 시드 누출/과민기권 0·임계 probe 현 동작 |
| `test_integration_real.py` | (1 skip) | 자격증명 부재 시 self-skip(아래 통합 문서) |

## 린트
```bash
ruff check src tests        # All checks passed
```

## Fix Failing Tests
실패 시: 출력 확인 → 해당 컴포넌트(`src/summarization/...`) 수정 → 재실행. **앱 코드는 워크스페이스 루트, 문서는 aidlc-docs만.**
