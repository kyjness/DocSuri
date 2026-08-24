"""2층 LLM 심판(설계 v3 §6.2) — **수동**. CI가 아니다.

문항마다 실제 evidence 턴을 한 번 돌리고, 그 판단이 골든셋의 기대 방향과 같은 쪽인지를
심판 모델이 채점한다. 1층(결정론)은 `backend/tests/test_evidence_golden_set.py`가 CI에서
공짜로 돌고, 여기는 Bedrock 호출이 문항당 두 번(턴 + 심판) 들어간다.

    set -a; source .env; set +a
    uv run --project backend python tools/local/evidence_judge.py            # 라벨 문항 전부
    uv run --project backend python tools/local/evidence_judge.py --case cot_prompting_definition

**왜 CI에 안 넣나** — 설계가 2층을 "야간/수동"으로 규정한다. 심판도 모델이라 흔들리고,
그 흔들림이 매 PR CI를 빨갛게 만들면 정작 1층이 잡아낸 배선 고장이 묻힌다.

**읽는 법** — 이 스크립트는 합격/불합격을 선고하지 않는다. 설계가 요구하는 것은
"심판 자체를 사람 라벨 표본과 일치율로 검증한다"이므로, 첫 실행의 값어치는 점수가 아니라
**심판이 사람 판정과 얼마나 어긋나는지를 보는 것**이다. 어긋난 문항은 손으로 확인하고,
심판이 틀렸으면 채점 기준을 고치고, 에이전트가 틀렸으면 그 문항을 회귀로 남긴다.

**주의**: 코퍼스와 자격증명이 실제여야 한다([[evidence-local-smoke-runbook]]). Bedrock
rerank 스로틀이 잦아 검색이 baseline RRF로 저하될 수 있고, 그러면 이 실행이 재는 것은
"리랭크가 붙은 탐색"이 아니다 — 문항마다 경고 로그를 모아 `contaminated`로 함께 보고한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.modules.evidence.adapters.llm_bedrock import parse_json_object  # noqa: E402
from backend.modules.evidence.domain.models import AgentRunContext  # noqa: E402
from backend.modules.evidence.eval.golden_set import GoldenCase, labelled_cases  # noqa: E402
from backend.modules.evidence.eval.layer1 import score_turn, summarise  # noqa: E402
from backend.modules.evidence.real_wiring import build_evidence_runner  # noqa: E402
from backend.modules.evidence.settings import EvidenceSettings  # noqa: E402
from docsuri_shared.bedrock import ANTHROPIC_VERSION, invoke_model, text_blocks  # noqa: E402

log = logging.getLogger("evidence.judge")

# 한 문항을 도는 동안 경고를 낸 로거들. 리랭크·임베딩 스로틀은 **soft fail**이라 검색이
# baseline RRF로 조용히 내려앉고 턴은 `state: "ok"`로 끝난다 — 그 실행이 잰 것은
# "리랭크가 붙은 탐색"이 아닌데 결과만 봐서는 구분되지 않는다.
_WATCHED = (
    "docsuri.evidence.loop",
    "docsuri.evidence.tools",
    "docsuri.evidence.sources",
    "docsuri.evidence.llm",
    "docsuri.evidence.runner",
    "discovery.service.orchestrator",
    "discovery.adapters.space_guard",
    "docsuri.discovery.api",
)


class _Contamination(logging.Handler):
    """문항 하나를 도는 동안 나온 경고를 모은다. 비어 있지 않으면 그 행은 비교 불가다.

    discovery의 `live_recall_eval`이 같은 이유로 같은 것을 센다 — 거기서 가져온 모양이다.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.msgs: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.msgs.append(record.getMessage())

_JUDGE_SYSTEM = """당신은 문헌 근거 에이전트의 답변을 채점한다.

기준은 셋이고, 각각 pass/fail과 한 줄 사유를 낸다:
1. direction — 판단이 기대 방향과 같은 쪽인가. 조건을 나눠야 하는 질문에 단정했으면 fail.
2. conditions — 조건 구분이 적절한가. 갈리지 않는 질문에 억지로 나눴어도 fail.
3. split_point — 갈림 지점이 맞는가. 해당 없으면 pass로 두고 사유에 '해당 없음'.

답변은 근거 번호가 붙은 문장과 종합 문장이 섞여 있다. **종합 문장에 근거가 없다는 것은
감점 사유가 아니다** — 그것은 설계가 허용한 형태이고 화면에서 이미 구분된다.

출력은 JSON 하나:
{"direction": {"verdict": "pass|fail", "why": "..."},
 "conditions": {"verdict": "pass|fail", "why": "..."},
 "split_point": {"verdict": "pass|fail", "why": "..."}}"""


def _judge_prompt(case: GoldenCase, answer) -> str:
    sentences = "\n".join(
        f"- {segment.text}" + (f" [근거 {segment.refs}]" if segment.refs else " (종합)")
        for segment in answer.segments
    )
    return (
        f"질문: {case.question}\n"
        f"질문 유형: {case.type.value}\n\n"
        f"기대 판단 방향(사람이 라벨함):\n{case.expected_direction}\n\n"
        f"에이전트의 판단:\n{sentences}"
    )


def _run_case(runner, case: GoldenCase, cap: _Contamination) -> dict:
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

    cap.msgs.clear()
    ctx = AgentRunContext(
        owner_id="judge",
        session_id=f"judge:{case.name}",
        turn_id=f"judge-{case.name}",
        prior_topics=(case.prior_topic,) if case.prior_topic else (),
    )
    trace: list = []
    result = runner.run(ctx, EvidenceRequest(topic=case.question), on_trace=trace.append)
    outcome = getattr(result, "outcome", None)
    if outcome is None or getattr(outcome, "state", "") != "ok":
        # **기권에도 트레이스를 싣는다.** 사유 코드만으로는 "근거가 없다"와 "내가 못 찾았다"가
        # 구분되지 않는다 — 이 저장소가 반복해서 당한 모양이라, 실패에서 볼 것을 더 남긴다.
        return {
            "case": case.name,
            "state": getattr(outcome, "state", "error"),
            "reason": getattr(outcome, "abstainReason", None),
            "trace": _trace_rows(trace),
            "contamination": list(cap.msgs),
            "judge": None,
        }
    report = score_turn(case, outcome, trace=trace)
    return {
        "case": case.name,
        "state": "ok",
        "layer1": asdict(report),
        "trace": _trace_rows(trace),
        "contamination": list(cap.msgs),
        "answer": [s.text for s in (outcome.answer.segments if outcome.answer else [])],
        "outcome": outcome,
        "report": report,
    }


def _trace_rows(trace: list) -> list[str]:
    return [
        f"{r.seq} {r.tool} {r.outcome.value} {r.args_summary[:60]} -> {r.result_summary[:80]}"
        for r in trace
    ]


def _judge(client, model: str, case: GoldenCase, answer) -> dict:
    body = {
        "anthropic_version": ANTHROPIC_VERSION,
        "max_tokens": 1024,
        "system": _JUDGE_SYSTEM,
        "messages": [{"role": "user", "content": _judge_prompt(case, answer)}],
    }
    return parse_json_object("\n".join(text_blocks(invoke_model(client, model, body))))


def _write(path: Path, output: dict) -> None:
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="이 이름의 문항 하나만 돌린다")
    parser.add_argument("--out", type=Path, help="결과 JSON을 여기에 쓴다")
    parser.add_argument(
        "--spacing",
        type=float,
        default=20.0,
        help="문항 사이 대기(초). Bedrock 쿼터가 빡빡해 붙여 돌리면 스로틀이 결과를 오염시킨다.",
    )
    args = parser.parse_args()

    settings = EvidenceSettings.from_env()
    if not settings.evidence_enabled:
        log.error("evidence가 구성되지 않았다 — .env를 source했는지 확인한다")
        return 2

    runner = build_evidence_runner(settings)
    cases = [c for c in labelled_cases() if not args.case or c.name == args.case]
    if not cases:
        log.error("문항을 찾지 못했다: %s", args.case)
        return 2

    import boto3

    client = boto3.client("bedrock-runtime", region_name=settings.region_name)

    cap = _Contamination()
    for name in _WATCHED:
        logging.getLogger(name).addHandler(cap)

    rows, reports = [], []
    for index, case in enumerate(cases):
        if index and args.spacing:
            time.sleep(args.spacing)
        log.info("돌리는 중: %s (%d/%d)", case.name, index + 1, len(cases))
        row = _run_case(runner, case, cap)
        if row["state"] == "ok":
            reports.append(row.pop("report"))
            outcome = row.pop("outcome")
            if outcome.answer and not outcome.answer.checks.fallback:
                try:
                    row["judge"] = _judge(client, settings.model_id, case, outcome.answer)
                except Exception as exc:  # noqa: BLE001 — 심판 하나가 죽어도 실행은 이어간다
                    # 심판도 같은 모델·같은 쿼터를 친다. 여기서 던지면 앞서 돈 문항들(문항당
                    # Bedrock 호출 여러 번)이 디스크에 닿기 전에 사라진다.
                    log.warning("심판 실패: %s — %s", case.name, exc)
                    row["judge"] = {"error": str(exc)[:200]}
            else:
                # 폴백은 판단이 아니다 — 심판에 넣으면 "판단이 틀렸다"로 잘못 읽힌다.
                row["judge"] = {"skipped": "fallback — 판단 층이 검사를 통과하지 못했다"}
        rows.append(row)
        if args.out:
            # 문항마다 바로 쓴다 — 마지막에 한 번 쓰면 도중에 죽은 실행은 아무 것도 안 남긴다.
            _write(args.out, {"summary": None, "cases": rows})

    summary = summarise(reports)
    # **스로틀은 측정을 조용히 오염시킨다.** 던져진 턴은 근거가 아니라 쿼터 때문에 기권한
    # 것이라 "에이전트가 못 찾았다"로 읽으면 안 된다 — 따로 세어 보고한다
    # (discovery의 live_recall_eval이 같은 이유로 같은 것을 센다).
    throttled = [r["case"] for r in rows if r.get("reason") == "llm_unavailable"]
    summary["throttled_or_llm_down"] = throttled
    if throttled:
        log.warning(
            "%d건이 llm_unavailable로 끝났다 — 이 실행의 수치는 그만큼 신뢰할 수 없다: %s",
            len(throttled),
            ", ".join(throttled),
        )
    # 던져지지 **않고** 끝난 행도 오염될 수 있다. 리랭크가 죽으면 검색이 baseline으로
    # 내려앉은 채 ok로 끝나므로, 위 목록만 보면 깨끗해 보인다 — 세는 것이 요점이다.
    contaminated = {r["case"]: r["contamination"] for r in rows if r.get("contamination")}
    summary["contaminated"] = contaminated
    if contaminated:
        log.warning(
            "%d건이 경고를 내며 돌았다 — 그 행의 recall은 리랭크가 붙은 탐색의 값이 아닐 수 "
            "있다: %s",
            len(contaminated),
            ", ".join(contaminated),
        )
    output = {"summary": summary, "cases": rows}
    if args.out:
        _write(args.out, output)
        log.info("결과를 %s에 썼다", args.out)
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))

    # 판정하지 않는다 — 첫 실행의 값어치는 점수가 아니라 심판과 사람 판정의 어긋남이다.
    log.info("문항 %d건 · 1층 위반 %d건", len(rows), len(summary["violations"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
