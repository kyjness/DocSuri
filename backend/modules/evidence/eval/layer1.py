"""1층 채점 — 결정론(설계 v3 §6.2). CI에서 매 PR 돈다.

여기서 재는 것은 **답변 품질이 아니라 불변식**이다. 품질은 2층 심판과 골든셋이 본다.
그래서 이 모듈은 LLM을 타지 않고, 같은 턴 결과에는 같은 점수를 낸다.

| 지표 | 무엇을 잡나 | 정답 라벨 필요? |
|---|---|---|
| `citation_reality` | 인용한 논문이 근거에 실재하는가. **100%여야 한다** | ✗ |
| `gate_rejection` | 게이트가 떨어뜨린 비율 — 0이면 게이트가 안 도는 것일 수 있다 | ✗ |
| `synthesis_ratio` | 종합 문장 비율(§4.3 A5의 실측 근거) | ✗ |
| `demoted` / `regenerated` / `fallback` | 검사가 실제로 무는가 | ✗ |
| `searches` | 범위 밖 질문이 검색을 0회로 끊었는가(§2.4) | ✗ |
| `counter_probes` | 주장·비교형이 반대 측을 찾아봤는가(§3.3 바닥 2) | ✗ |
| `recall_at_k` | 정답 논문을 top-k에 올렸는가 | ○ |

**검색 평가와 답변 평가를 분리한다**(§6.2 각주) — 못 찾은 건지 찾고도 틀린 건지가 갈려야
고칠 곳이 보인다. 그래서 `recall_at_k`는 별도 필드이고 다른 지표와 섞어 평균 내지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docsuri_shared._generated.dtos.evidence_schema import (
    AnswerSegmentKind,
    EvidenceAbstainResult,
    EvidenceResult,
)

from ..domain.gate import id_key
from ..domain.models import iter_refs
from ..ports.llm import COUNTER_REQUIRED_KINDS
from ..ports.tools import (
    TOOL_CORPUS_SEARCH,
    TOOL_LIVE_LOOKUP,
    counter_probes,
)
from .golden_set import GoldenCase

__all__ = ["Layer1Report", "score_turn", "summarise"]

# 도구 이름은 **상수로** 받는다. 리터럴로 적어 두면 개명이 여기까지 안 와도 아무 데서도
# 안 걸리고, `searches`가 0이 되어 "범위 밖 질문은 검색 0회" 검사가 항상 통과한다.
_SEARCH_TOOLS = frozenset({TOOL_CORPUS_SEARCH, TOOL_LIVE_LOOKUP})


@dataclass(slots=True)
class Layer1Report:
    """문항 하나의 1층 점수. `None`은 "그 문항에 해당 없음"이지 0이 아니다."""

    case: str
    abstained: bool
    claims: int
    # 인용한 논문 중 근거에 실재하는 비율. 근거 0건이면 None(잴 것이 없다).
    citation_reality: float | None = None
    # 게이트가 떨어뜨린 건수 / (통과 + 탈락).
    gate_rejection: float | None = None
    synthesis_ratio: float | None = None
    demoted: int = 0
    regenerated: bool = False
    fallback: bool = False
    searches: int = 0
    # `stance="counter"`로 표시된 검색·추출 횟수(§3.3 바닥 2). 주장·비교형에서 0이면 위반이다.
    counter_probes: int = 0
    # **사람이 라벨한** 질문 유형이다 — 모델이 선언하는 `question_kind`와 다른 축이고
    # (골든셋이 그렇게 적어 뒀다), `summarise`가 분모를 고르는 데만 쓴다.
    expected_kind: str | None = None
    recall_at_k: float | None = None
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def score_turn(
    case: GoldenCase,
    result: EvidenceResult | EvidenceAbstainResult,
    *,
    trace: list,
    rejections: dict[str, int] | None = None,
    top_k: int = 10,
) -> Layer1Report:
    """턴 하나를 채점한다. `trace`는 `LoopState.trace`, `rejections`는 게이트 탈락 카운터."""
    report = Layer1Report(
        case=case.name,
        abstained=getattr(result, "state", "") == "abstain",
        claims=0,
        searches=sum(1 for record in trace if record.tool in _SEARCH_TOOLS),
        counter_probes=counter_probes(trace),
        expected_kind=case.expected_kind,
    )
    _check_scope(case, report)
    _check_counter_probe(report)

    if report.abstained:
        # 기권 자체는 위반이 아니다(§2.3). 범위 밖 검사는 위에서 이미 봤다.
        _check_gate(report, rejections or {})
        return report

    claims = list(result.claims)
    report.claims = len(claims)
    # 탈락률은 claims 수가 잡힌 **뒤에** 잰다 — 앞에서 재면 분모가 탈락분뿐이라 항상 1.0이다.
    _check_gate(report, rejections or {})
    _check_citations(report, claims)
    _check_answer(report, result.answer)
    if case.expected_papers:
        report.recall_at_k = _recall(case, claims, top_k)
    return report


def _check_scope(case: GoldenCase, report: Layer1Report) -> None:
    """§2.4 — 범위 밖 질문은 **비용을 쓰기 전에** 끊어야 한다."""
    if case.expected_kind != "out_of_scope":
        return
    if report.searches:
        report.violations.append(
            f"범위 밖 질문인데 검색을 {report.searches}회 했다(§2.4: 검색 0회일 때만 종료 인정)"
        )
    if not report.abstained:
        report.violations.append("범위 밖 질문에 근거 답변을 냈다")


def _check_counter_probe(report: Layer1Report) -> None:
    """§3.3 바닥 2 — 주장·비교형은 반대 측을 한 번은 찾아봐야 한다.

    **모델이 stance를 잘못 붙일 수 있으므로 여기서 센다**(§3.2). 루프의 바닥 검사는 정상
    종료를 막을 뿐이고, 예산 소진·취소로 끝난 턴은 그 검사를 지나지 않는다 — 그런 턴이
    반대 측을 한 번도 안 본 채 답을 내는 것이 지표에 보여야 한다.

    기권한 턴은 면제한다: 답을 안 냈으므로 한쪽으로 치우친 판단이 나갈 일이 없다.
    """
    if report.expected_kind not in COUNTER_REQUIRED_KINDS or report.abstained:
        return
    if report.counter_probes == 0:
        report.violations.append(
            f"{report.expected_kind}형 질문인데 stance=counter 탐색이 0회다"
            "(§3.3 바닥 2: 반대 측을 찾아본 뒤에 끝내야 한다)"
        )


def _check_gate(report: Layer1Report, rejections: dict[str, int]) -> None:
    rejected = sum(rejections.values())
    total = rejected + report.claims
    report.gate_rejection = rejected / total if total else None


def _check_citations(report: Layer1Report, claims: list) -> None:
    """인용 실재율 — 이 에이전트에서 가장 비싼 자산이 **코드로** 채점되는 지점이다.

    게이트가 이미 논문 실재를 확인하고 통과시켰으므로 정상 동작에서는 항상 1.0이다.
    그래서 이 값이 1.0 미만인 것은 품질 저하가 아니라 **게이트를 우회한 경로가 생겼다**는
    뜻이고, 위반으로 올린다.
    """
    refs = [ref for item in claims for ref in iter_refs(item)]
    if not refs:
        return
    real = [ref for ref in refs if ref.paperId and ref.recordRef]
    report.citation_reality = len(real) / len(refs)
    if report.citation_reality < 1.0:
        report.violations.append(
            f"인용 실재율 {report.citation_reality:.0%} — 100%가 아니면 게이트를 우회한 것이다"
        )


def _check_answer(report: Layer1Report, answer) -> None:
    if answer is None:
        report.violations.append("근거가 있는데 판단이 비어 있다")
        return
    report.demoted = answer.checks.demoted
    report.regenerated = answer.checks.regenerated
    report.fallback = answer.checks.fallback
    segments = answer.segments
    if not segments:
        report.violations.append("판단에 문장이 0건이다")
        return
    synthesis = sum(1 for s in segments if s.kind is AnswerSegmentKind.synthesis)
    report.synthesis_ratio = synthesis / len(segments)
    if answer.checks.fallback:
        # 폴백은 실패가 아니라 fail-closed의 정상 경로다 — 위반이 아니라 지표로 센다.
        return
    known = range(1, report.claims + 1)
    stray = sorted({n for s in segments for n in s.refs if n not in known})
    if stray:
        report.violations.append(
            f"판단이 없는 근거 번호 {stray}를 가리킨다 — 검사기 A1을 지났어야 한다"
        )


def _recall(case: GoldenCase, claims: list, top_k: int) -> float:
    """정답 논문 중 몇 편이 인용된 논문 집합(상위 k행)에 들어왔나.

    **discovery의 `recall_at_k`와 같은 이름이지만 같은 눈금이 아니다.** 그쪽은 `SearchFn`이
    낸 **랭킹된 id 목록**의 상위 k를 자르고, 이쪽은 **조립된 claim**의 상위 k를 자른 뒤
    논문을 모은다 — refs가 셋 달린 claim 하나가 저기서는 세 자리, 여기서는 한 자리다.
    두 수치를 나란히 놓고 비교하면 안 된다.

    **답변 평가와 섞지 않는다** — 이 값이 낮으면 탐색을 고치고, 이 값이 높은데 판단이
    틀렸으면 판단 층을 고친다. 한 숫자로 합치면 그 구분이 사라진다.
    """
    cited = {
        id_key(ref.paperId) for item in claims[:top_k] for ref in iter_refs(item) if ref.paperId
    }
    expected = {id_key(pid) for pid in case.expected_papers}
    return len(expected & cited) / len(expected)


def summarise(reports: list[Layer1Report]) -> dict[str, object]:
    """§6.3 온라인 지표와 같은 축으로 접는다 — 골든셋과 실서비스가 같은 눈금을 쓴다."""

    def mean(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    return {
        "cases": len(reports),
        "violations": [v for r in reports for v in r.violations],
        "abstain_rate": mean([1.0 if r.abstained else 0.0 for r in reports]),
        # **`is not None`이어야 한다.** 진리값으로 거르면 0.0이 평균에서 빠지는데, 하필
        # 그 0.0이 최선의 경우다 — 종합 문장이 하나도 없는 턴, 인용이 하나도 실재하지 않는
        # 턴. 좋은 쪽과 최악을 동시에 지우고 평균이 위로 뜬다(2026-08-24: 6문항 중 0.0인
        # 1건이 빠져 synthesis_ratio가 0.193 대신 0.232로 보고됐다).
        "citation_reality": mean(
            [r.citation_reality for r in reports if r.citation_reality is not None]
        ),
        "synthesis_ratio": mean(
            [r.synthesis_ratio for r in reports if r.synthesis_ratio is not None]
        ),
        "fallback_rate": mean([1.0 if r.fallback else 0.0 for r in reports]),
        "regenerated_rate": mean([1.0 if r.regenerated else 0.0 for r in reports]),
        "demoted_total": sum(r.demoted for r in reports),
        # 반대 측 탐색 — **주장·비교형에서만** 잰다. 사실형·범위 밖을 분모에 넣으면 면제된
        # 문항이 비율을 눌러 "반대 측을 잘 찾는다"가 문항 구성만 반영하게 된다.
        "counter_probe_rate": mean(
            [
                1.0 if r.counter_probes else 0.0
                for r in reports
                if r.expected_kind in COUNTER_REQUIRED_KINDS and not r.abstained
            ]
        ),
        # 검색 평가는 분리해서 낸다.
        "recall_at_k": mean([r.recall_at_k for r in reports if r.recall_at_k is not None]),
    }
