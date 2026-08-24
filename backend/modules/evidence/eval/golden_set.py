"""골든셋 초기분(설계 v3 §6.1) — 유형 6종 균형, **작고 검수 대기**.

이것은 회귀·배선 검사용이지 품질 모델이 아니다. `discovery/eval/golden_set.py`가 13건으로
같은 역할을 하는 것과 같은 급이고, 설계의 "시작 규모 50문항"은 성숙 규모(200~500)로 가는
경로의 표지이지 이 파일의 합격선이 아니다. 실서비스 실패 사례를 승격해 키운다.

**두 종류가 섞여 있다.**

- `expected_papers`가 **비어 있는 문항** — 정답 라벨이 필요 없는 검사에만 쓴다(인용 실재율,
  게이트 탈락률, 종합 문장 비율, 범위 밖 질문의 검색 0회). 질문만 있으면 성립한다.
- `expected_papers`가 **있는 문항** — recall@k와 2층 심판이 쓴다. 여기 실린 논문 id는
  배포 코퍼스(`docsuri-deploy-v1`)에서 **초록을 직접 읽고** 고른 것이다.

`expected_papers`의 한계를 정직하게 적어 둔다: 후보는 코퍼스 안에서 골랐으므로 이 집합은
"코퍼스에 있는 정답"이지 "세상에 있는 정답"이 아니다. 코퍼스 밖 문항(`out_of_corpus`)이
그 경계를 일부러 건드린다. 그리고 **우리 랭킹 순위로 고르지 않았다** — 순위로 고르면
recall@k가 자동으로 1.0이 되어 아무 것도 측정하지 못한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["GOLDEN_CASES", "GoldenCase", "QuestionType"]


class QuestionType(StrEnum):
    """§6.1의 유형 6종. `question_kind`(모델 선언)와 다른 축이다 — 이쪽은 사람이 라벨한다."""

    COMPARISON = "comparison"
    CLAIM = "claim"
    FACT = "fact"
    FOLLOW_UP = "follow_up"
    OUT_OF_CORPUS = "out_of_corpus"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """문항 하나.

    `expected_kind`는 모델이 선언해야 하는 `question_kind`다 — `follow_up`·`out_of_corpus`는
    선언 어휘에 없으므로(그것은 탐색 형태이지 질문 종류가 아니다) 각각 이전 턴의 종류를
    따른다. `prior_topic`이 있으면 후속 턴으로 돌린다.
    """

    name: str
    question: str
    type: QuestionType
    expected_kind: str | None = None
    # 코퍼스에서 초록을 읽고 고른 정답 논문(버전 없는 bare id). 비어 있으면 무라벨 문항이다.
    expected_papers: tuple[str, ...] = ()
    # 기대하는 판단 방향 — 2층 심판의 채점 기준이다. 무라벨 문항은 비워 둔다.
    expected_direction: str = ""
    prior_topic: str | None = None
    note: str = ""
    # 사람 검수를 통과한 라벨인가. 새 문항의 기본값은 False다 — 검수되지 않은 라벨로
    # 잰 recall@k와 심판 점수는 "내가 정한 정답으로 내가 채점한 값"이라 품질 지표가
    # 아니고, 그 사실이 코드에 보여야 한다.
    reviewed: bool = False


# --- 라벨 문항 — 정답 논문·판단 방향이 붙는다(recall@k · 2층 심판) -------------------
#
# 각 항목의 `note`는 **왜 그 논문인가**를 적는다. 라벨을 나중에 되짚을 때 근거가 남아야
# 한다 — 라벨만 남으면 그것이 판단인지 추측인지 구분되지 않는다.

_LABELLED: tuple[GoldenCase, ...] = (
    GoldenCase(
        name="rag_reduces_hallucination",
        question="RAG가 LLM의 환각을 실제로 줄여?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        expected_papers=("2005.11401", "2309.01431", "2401.15884"),
        expected_direction=(
            "조건부 긍정. 검색이 맞으면 줄지만 검색이 틀리면 오히려 악화된다는 조건을 밝혀야 "
            "한다. 무조건 '줄어든다'는 단정은 오답."
        ),
        note=(
            "2005.11401은 RAG 원안(파라미터 지식의 한계와 provenance를 문제로 세운다). "
            "2309.01431은 노이즈·거부·통합·반사실 4축으로 RAG의 병목을 계량한다. "
            "2401.15884는 '검색이 틀리면 어떻게 되나'를 정면으로 다룬다 — 조건이 갈리는 "
            "지점을 이 셋이 함께 만든다."
        ),
        reviewed=True,
    ),
    GoldenCase(
        name="lora_vs_full_finetuning",
        question="LoRA가 전체 파인튜닝보다 좋아?",
        type=QuestionType.COMPARISON,
        expected_kind="comparison",
        expected_papers=("2106.09685", "2104.08691", "1902.00751"),
        expected_direction=(
            "조건부. 배포·비용 축에서는 파라미터 효율 쪽이 유리하고, 품질은 규모·과제에 "
            "따라 갈린다. 코퍼스에 정면 비교 실험이 없으므로 **한쪽 근거만 있다**는 사실을 "
            "밝히는 답이 맞다(§2.3 '부분')."
        ),
        note=(
            "2106.09685가 LoRA 원안. 2104.08691은 규모가 커질수록 프롬프트 튜닝이 전체 "
            "파인튜닝에 수렴한다고 보고해 '조건'의 축(규모)을 준다. 1902.00751은 어댑터로 "
            "같은 축을 2019년에 세운다. 'LoRA Learns Less and Forgets Less'(2405.09673)는 "
            "**코퍼스에 없다** — 그래서 이 문항은 한쪽만 있는 상태를 정직하게 말하는지 본다."
        ),
        reviewed=True,
    ),
    GoldenCase(
        name="cot_prompting_definition",
        question="Chain-of-Thought 프롬프팅은 무엇을 하는 방법이야?",
        type=QuestionType.FACT,
        expected_kind="fact",
        expected_papers=("2201.11903",),
        expected_direction=(
            "중간 추론 단계를 생성하게 해서 복잡한 추론 성능을 올리는 프롬프팅 방법. "
            "사실형이므로 반대 측 탐색은 필요 없다."
        ),
        note=(
            "2201.11903이 원안이고 코퍼스에 있다. **처음에는 '언제 나왔어?'로 물었는데 "
            "그것이 잘못된 라벨이었다**(2026-08-24 실측): 출판 연도는 논문 **본문에 글자 "
            "그대로 없어서** 게이트가 인용을 정당하게 떨어뜨리고 턴이 기권한다(추출 3건 "
            "전부 탈락). 이 에이전트는 색인 메타가 아니라 본문 인용으로만 답하므로, "
            "사실형 문항은 **본문에 실재하는 사실**이어야 성립한다."
        ),
        reviewed=True,
    ),
    GoldenCase(
        name="self_consistency_follow_up",
        question="그중에서 디코딩 전략을 바꾼 쪽만 다시 정리해 줘",
        type=QuestionType.FOLLOW_UP,
        expected_kind="claim",
        expected_papers=("2203.11171",),
        expected_direction=(
            "이전 턴의 논문 집합에서 좁혀야 한다. 새 검색 없이 self-consistency 쪽으로 "
            "좁혀지면 통과."
        ),
        prior_topic="Chain-of-Thought 프롬프팅을 처음 제안한 논문은 언제 나왔어?",
        note="2203.11171은 CoT 위에서 **디코딩**을 바꾼 것이라 좁히기의 정답이 하나로 떨어진다.",
        reviewed=True,
    ),
    GoldenCase(
        name="post_training_quantization_accuracy",
        question="8비트 사후 양자화가 정확도를 지킬 수 있어?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        expected_papers=("2211.10438",),
        expected_direction=(
            "조건부 긍정 — 활성값 이상치를 다루는 기법이 있어야 한다는 조건을 밝힌다."
        ),
        note="2211.10438(SmoothQuant)이 W8A8에서 정확도 보존을 정면으로 주장한다.",
        reviewed=True,
    ),
    GoldenCase(
        name="rag_evaluation_without_references",
        question="RAG 파이프라인을 정답 없이 평가할 수 있어?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        expected_papers=("2309.15217",),
        expected_direction="긍정. reference-free 평가 틀이 있다는 근거를 대야 한다.",
        note="2309.15217(Ragas)이 reference-free를 명시한다.",
        reviewed=True,
    ),
    GoldenCase(
        name="mamba_state_space_beats_transformer",
        question="상태공간 모델이 긴 문맥에서 트랜스포머를 앞선다는 근거가 있어?",
        type=QuestionType.OUT_OF_CORPUS,
        expected_kind="claim",
        expected_papers=(),
        expected_direction=(
            "코퍼스에서 근거를 못 찾으면 §2.3의 '없음'으로 정직하게 말해야 한다. "
            "실시간 조회(PR 4)가 붙기 전에는 이것이 정답이다 — 지어내면 오답."
        ),
        note=(
            "정답 논문을 일부러 비워 둔다. 코퍼스 경계를 건드리는 문항이라, PR 4에서 "
            "실시간 조회가 붙으면 기대가 '찾아온다'로 바뀐다. 그때 이 항목이 바뀌는 것 "
            "자체가 그 기능이 실제로 붙었다는 증거다."
        ),
        reviewed=True,
    ),
)


# --- 무라벨 문항 — 정답 라벨이 필요 없는 검사에 쓴다 --------------------------------
#
# 인용 실재율 100%·게이트 탈락률·종합 문장 비율·범위 밖 검색 0회는 질문만 있으면 성립한다.
# 이 문항들은 검수 대상이 아니다.

_UNLABELLED: tuple[GoldenCase, ...] = (
    GoldenCase(
        name="scope_small_talk",
        question="오늘 점심 뭐 먹을까?",
        type=QuestionType.OUT_OF_SCOPE,
        expected_kind="out_of_scope",
        note="§2.4 — 검색을 한 번도 하지 않고 안내문으로 끝나야 한다.",
    ),
    GoldenCase(
        name="scope_write_code",
        question="파이썬으로 이진 탐색 짜 줘",
        type=QuestionType.OUT_OF_SCOPE,
        expected_kind="out_of_scope",
        note="§2.4 — 논문으로 답할 질문이 아니다. 비용을 쓰기 전에 끊어야 한다.",
    ),
    GoldenCase(
        name="scope_personal_opinion",
        question="너는 어느 쪽이 더 낫다고 생각해?",
        type=QuestionType.OUT_OF_SCOPE,
        expected_kind="out_of_scope",
        note="개인 의견 요구 — 문헌 근거로 답하는 질문이 아니다.",
    ),
    GoldenCase(
        name="claim_distillation_beats_pruning",
        question="지식 증류가 가지치기보다 압축률 대비 성능이 좋아?",
        type=QuestionType.COMPARISON,
        expected_kind="comparison",
        note="비교형 무라벨 — 갈리는 조건을 말하는지, 단정하지 않는지를 본다.",
    ),
    GoldenCase(
        name="claim_instruction_tuning_generalises",
        question="인스트럭션 튜닝이 안 배운 과제에도 일반화돼?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        note="주장형 무라벨 — 인용 실재율과 종합 비율을 본다.",
    ),
    GoldenCase(
        name="fact_transformer_year",
        question="트랜스포머 구조를 제안한 논문은 몇 년도야?",
        type=QuestionType.FACT,
        expected_kind="fact",
        note="사실형 무라벨 — 수치가 근거에 실재하는지(A2)를 본다.",
    ),
    GoldenCase(
        name="follow_up_narrow_by_year",
        question="그중에서 2023년 이후만",
        type=QuestionType.FOLLOW_UP,
        expected_kind="claim",
        prior_topic="RAG가 LLM의 환각을 실제로 줄여?",
        note="좁히기 무라벨 — 새 검색 없이 이전 집합에서 줄이는지 본다(연도 인자는 PR 4).",
    ),
)

# 유형별 균형은 문항이 늘어도 유지한다 — 한 유형이 절반을 넘으면 그 유형의 회귀만 잡힌다.
# 그 균형을 실제로 지키는 것은 `test_no_type_dominates_the_golden_set`이지 이 모듈이 아니다.
GOLDEN_CASES: tuple[GoldenCase, ...] = _LABELLED + _UNLABELLED


def labelled_cases() -> tuple[GoldenCase, ...]:
    """정답 논문이 붙은 문항 — recall@k와 2층 심판이 쓴다."""
    return tuple(case for case in GOLDEN_CASES if case.expected_papers)


def pending_review() -> tuple[GoldenCase, ...]:
    """아직 사용자 검수를 받지 않은 라벨 문항."""
    return tuple(case for case in _LABELLED if not case.reviewed)
