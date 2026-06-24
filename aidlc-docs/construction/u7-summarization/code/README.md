# U7 Summarization — Code Summary

**단계**: CONSTRUCTION → Code Generation (Part 2) · **일자**: 2026-06-19 · **위치**: `backend/modules/summarization/`
**검증**: `pytest` **29 passed, 1 skipped**(통합 self-skip) · `ruff check` **clean**.

## 구조 (real-first, src-layout)
```
backend/modules/summarization/
├── pyproject.toml · ruff.toml
├── src/summarization/
│   ├── domain/   models · refiner · source_selector · cache_key · length_router ·
│   │             glossary · grounding · assembler
│   ├── service/  orchestrator
│   ├── ports/    ports (Llm/Store/FullText/GlossaryRepo)
│   ├── adapters/ settings · bedrock_llm · s3_redis_store · s3_full_text · rds_glossary  ← 실 단일본
│   ├── api/      router(/api/summarize) · gateway_seam
│   ├── prompts/  templates (본문 격리 · persona · 용어집 · grounding)
│   └── real_wiring.py
├── migrations/   001_create_user_glossary.sql
└── tests/        stubs · conftest · test_domain_* · test_orchestrator · test_pbt · test_integration_real
```

## 설계 반영 (FD/NFR/Infra 답변 → 코드)
- **Q4 근거화**: `domain/grounding.py` = U7 고유 **결정적** 게이트(앵커 실재·수치 정규화·스키마·잘림). U6 검색용 `enforce` 미사용. LLM-judge 없음(Q15).
- **Q2 정제 / Q6 섹션**: `domain/refiner.py` = 참고문헌·Header/Footer·페이지번호·저작권·저자정보 제거; **캡션·Appendix·Supplementary·수식 보존**; 정규식 섹션 도출(실패 시 span-only).
- **Q5 스트리밍**: `service/orchestrator.py` = 생성-버퍼-검증-점진렌더(완성 draft를 근거화 통과 후 노출, FR-5 날조 0).
- **저하 3계층**: 비용(`CostDegradedDTO`, U6 `get_budget_state`) ≠ 장애(`LlmUnavailable`→1회 재시도→`AbstainDTO`) ≠ 소스부재(초록 폴백/`SourceUnavailableDTO`).
- **Q8 용어집**: `domain/glossary.py` = keep-as-is·핵심 매핑은 프롬프트 강제; 사용자 선호 단순 명사는 **결정적 후치환**(한국어 조사 안전 = 좌측 경계만 매칭).
- **Q7 캐시 키**: `domain/cache_key.py` = immutable `(paper,version,task,lang,persona,glossaryVer,modelVer,promptVer)`; S3 경로·Redis `sum:` 키.
- **real-first(Q10/Q11/TD-S12)**: 어댑터는 실 구현 단일본(Bedrock/S3/Redis/RDS); **Production Mock Adapter 없음**. 단위 테스트는 `tests/stubs.py` 테스트 전용 Fixture/Stub. 통합 테스트는 자격증명 부재 시 self-skip.
- **TD-S3/S4 모델**: 요약=`claude-sonnet-4-6` / 번역=`claude-haiku-4-5`, Bedrock `invoke_model_with_response_stream`.

## 스토리 커버 (US-S1~S6)
US-S1 요약 · US-S2 번역 · US-S3 출처보기/기권 · US-S4 개인화(persona·용어집) · US-S5 캐시/온디맨드 · US-S6 기여(비용 게이트·근거화 텔레메트리).

## 로컬 검증
```bash
cd backend/modules/summarization
PYTHONPATH="src:../../../shared/python/src" python -m pytest   # 29 passed, 1 skipped
ruff check src tests                                           # clean
```

## ⚠️ 의존성·조율 플래그 (배포 last-mile)
- **app-shell 마운트 = 조율 존(@ELSAPHABA 사인오프 필요)**: `backend/wiring.py`는 **변경하지 않았다**(쉘 소유·기존 테스트 단언 보호). 사인오프 후 아래 mounter를 `_INTEGRATIONS`에 추가하면 라이브 연결된다 — 미구성(`DOCSURI_SUMMARY_BUCKET` 미설정) 시 graceful-skip(mock 폴백 없음, real-first):
  ```python
  def _mount_summarization(app, settings, result):
      from docsuri_ops.cost_guard import CostGuardCircuitBreaker
      from summarization.adapters.settings import SummarizationSettings
      from summarization.api.router import build_router
      s = SummarizationSettings.from_env()
      if not s.summarization_enabled:
          result.skipped.append(("summarization", "not configured (DOCSURI_SUMMARY_BUCKET unset)"))
          return
      from summarization.real_wiring import build_real_orchestrator
      bundle = build_real_orchestrator(
          s, cost_guard=CostGuardCircuitBreaker(),
          observability=getattr(app.state, "observability", None),
      )
      app.state.summarization_bundle = bundle
      app.include_router(build_router(bundle.orchestrator))
      result.mounted.append("summarization")
  ```
  (마운트 시 `test_app_shell.py`의 모듈 집합 단언에 `"summarization"` 추가 필요 = 쉘 소유 변경.)
- **인프라 증분(@Infra 사인오프, infrastructure-design 연계)**: ECS task role Bedrock/S3 IAM · `user_glossary` 마이그레이션 적용 · Redis `sum:` TTL 구성 · CloudWatch/Budget U7 라인 · CI 통합 게이트 레인(스코프 CI 역할).
- **신규 DTO 계약** `shared/dtos/summarization`(PROVISIONAL): 현재 모듈 로컬 응답 DTO로 대체; 별도 shared PR로 승격(U4 library 선례).
- **비동기 잡(초장문 map-reduce)**: v1 미프로비저닝(TD-S9 fast-follow, #135) — `LengthRouter`가 OVER_CAP·MAP_REDUCE 밴드를 모두 기권으로 처리.
