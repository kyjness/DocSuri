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

# --- PR 4 확대분 — 라벨 문항(초록을 읽고 고름, 검수 대기) --------------------------
#
# 배포 색인(`docsuri-deploy-v1`, 논문 3,281편)에서 **초록을 직접 읽고** 골랐다. 우리 랭킹
# 순위로 고르지 않았다 — 순위로 고르면 recall@k가 자동으로 1.0이 되어 아무것도 못 잰다.
#
# 검수 완료 2026-08-25 — `reviewed=True`이고 채점 표본(`labelled_cases()`)에 든다.
#
# 새 문항은 `reviewed=False`로 들어온다. 그동안 그 문항의 `expected_papers`는 채점에 쓰이지
# 않는다(`labelled_cases()`가 거른다) — 검수 전 recall@k와 심판 점수는 "내가 정한 정답으로
# 내가 채점한 값"이라 품질 지표가 아니기 때문이다. 그 불변식은
# `test_unreviewed_labels_never_reach_the_scoring_path`가 **합성 사례로** 지킨다: 검수 대기가
# 비어 있는 날에도 규칙이 살아 있어야 하고, 실제 데이터로 검사하면 그날 아무것도 안 보면서
# 초록으로 남는다.

_LABELLED_PR4: tuple[GoldenCase, ...] = (
    GoldenCase(
        name="moe_scales_without_proportional_compute",
        question="Mixture-of-Experts가 파라미터를 늘리면서 연산량은 안 늘릴 수 있어?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        expected_papers=("2101.03961", "2112.06905", "2106.05974"),
        expected_direction=(
            "조건부 긍정. 토큰당 활성 파라미터만 늘지 않는 것이고 총 메모리·통신 비용은 "
            "늘어난다는 조건을 밝혀야 한다. '연산량이 안 는다'는 단정은 오답."
        ),
        note=(
            "2101.03961(Switch)이 희소 활성화로 파라미터-연산 분리를 정면으로 주장하고, "
            "2112.06905(GLaM)이 같은 축을 학습·추론 비용 수치로 받친다. 2106.05974는 비전에서 "
            "같은 것을 재현해 주장이 한 도메인에 국한되지 않음을 보인다."
        ),
        reviewed=True,
    ),
    GoldenCase(
        name="dpo_vs_rlhf_reward_model",
        question="DPO가 보상 모델을 쓰는 RLHF보다 나아?",
        type=QuestionType.COMPARISON,
        expected_kind="comparison",
        expected_papers=("2305.18290", "2306.17492"),
        expected_direction=(
            "조건부. 파이프라인 단순함·안정성에서는 DPO 쪽이고 품질은 과제·데이터에 따라 "
            "갈린다. 코퍼스에 정면 대규모 비교가 얇으므로 '한쪽 근거만 있다'를 밝히는 답이 맞다."
        ),
        note=(
            "2305.18290이 DPO 원안이고 보상 모델 없이 같은 목적을 푼다고 주장한다. "
            "2306.17492(PRO)가 선호 랭킹 쪽에서 같은 축을 세워 비교 지점을 만든다."
        ),
        reviewed=True,
    ),
    GoldenCase(
        name="compute_optimal_model_size",
        question="같은 연산 예산이면 모델을 키우는 게 나아 데이터를 늘리는 게 나아?",
        type=QuestionType.COMPARISON,
        expected_kind="comparison",
        expected_papers=("2203.15556", "2001.08361"),
        expected_direction=(
            "**문헌이 갈리는 대표 문항이다.** 2001.08361은 모델 크기 쪽에 무게를 뒀고 "
            "2203.15556이 그것을 뒤집어 데이터를 같이 키워야 한다고 보고한다. 갈림 지점이 "
            "'학습 토큰 수를 함께 스케일했는가'임을 말해야 한다."
        ),
        note=(
            "두 논문이 같은 질문에 다른 답을 낸 실측 사례라, 조건 분기와 갈림 지점을 실제로 "
            "쓰는지 보는 데 가장 좋은 문항이다."
        ),
        reviewed=True,
    ),
    GoldenCase(
        name="smoothquant_vs_qat",
        question="8비트로 줄일 때 학습을 다시 하는 것과 사후 양자화 중 뭘 써야 해?",
        type=QuestionType.COMPARISON,
        expected_kind="comparison",
        expected_papers=("2211.10438", "2305.17888", "2306.00978"),
        expected_direction=(
            "조건부. 재학습 비용을 감당할 수 있으면 QAT가 유리하고, 못 하면 이상치를 다루는 "
            "PTQ 기법으로 상당 부분 회수된다는 조건을 밝혀야 한다."
        ),
        note=(
            "2211.10438(SmoothQuant)·2306.00978(AWQ)이 PTQ 쪽, 2305.17888(LLM-QAT)이 QAT 쪽 "
            "축을 세운다. 셋이 함께 있어야 조건이 갈리는 지점이 생긴다."
        ),
        reviewed=True,
    ),
    GoldenCase(
        name="longformer_handles_long_documents",
        question="긴 문서를 통째로 넣으려면 어텐션을 어떻게 바꿔야 해?",
        type=QuestionType.FACT,
        expected_kind="fact",
        expected_papers=("2004.05150", "1904.10509"),
        expected_direction=(
            "희소·국소 어텐션으로 이차 복잡도를 낮춘다. 사실형이므로 반대 측 탐색은 필요 없다."
        ),
        note=(
            "2004.05150(Longformer)이 슬라이딩 윈도우+전역 어텐션을, 1904.10509(Sparse "
            "Transformer)가 그 앞선 희소 패턴을 본문에 명시한다 — 둘 다 방법이 본문에 "
            "글자 그대로 있어 사실형 문항으로 성립한다."
        ),
        reviewed=True,
    ),
    GoldenCase(
        name="linformer_linear_attention",
        question="어텐션 복잡도를 선형으로 낮춘 방법이 있어?",
        type=QuestionType.FACT,
        expected_kind="fact",
        expected_papers=("2006.04768",),
        expected_direction="저차원 사영으로 선형 복잡도를 만든다는 방법을 본문 인용으로 대야 한다.",
        note="2006.04768(Linformer)이 선형 복잡도를 제목과 본문에서 정면으로 주장한다.",
        reviewed=True,
    ),
    GoldenCase(
        name="prompt_injection_defenses_hold",
        question="프롬프트 인젝션 방어가 실제로 막아줘?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        expected_papers=("2503.00061", "2306.05499", "2507.15219"),
        expected_direction=(
            "부정 쪽으로 기운 조건부. 방어가 제안되지만 적응형 공격에 뚫린다는 반대 근거가 "
            "코퍼스에 있으므로, 그것을 못 찾고 '막아준다'고 하면 오답이다."
        ),
        note=(
            "2503.00061이 '적응형 공격이 방어를 깬다'를 정면으로 보고한다 — **반대 측 탐색이 "
            "있어야만 제대로 답할 수 있는 문항**이라 §3.3 바닥 2의 회귀로 쓴다."
        ),
        reviewed=True,
    ),
    GoldenCase(
        name="self_rag_improves_over_plain_rag",
        question="RAG에 자기 비판을 붙이면 나아져?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        expected_papers=("2310.11511", "2305.06983"),
        expected_direction=(
            "긍정 쪽 조건부 — 검색 시점·필요성 판단을 모델이 하게 한 것이 이득의 출처다."
        ),
        note=(
            "2310.11511(Self-RAG)이 자기 반성 토큰을, 2305.06983(FLARE)이 능동 검색 시점을 "
            "다룬다. 둘이 같은 축의 서로 다른 손잡이다."
        ),
        reviewed=True,
    ),
    GoldenCase(
        name="context_window_extension_by_interpolation",
        question="학습한 길이보다 긴 문맥을 쓰려면 어떻게 해?",
        type=QuestionType.FACT,
        expected_kind="fact",
        expected_papers=("2306.15595",),
        expected_direction="위치 인코딩을 보간해 확장한다는 방법이 본문에 실재해야 한다.",
        note="2306.15595(Position Interpolation)가 방법을 본문에 수식과 함께 명시한다.",
        reviewed=True,
    ),
    GoldenCase(
        name="distillation_needs_a_teacher",
        question="지식 증류로 작은 모델을 만들면 성능을 얼마나 지켜?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        expected_papers=("1908.09355", "2006.05525"),
        expected_direction=(
            "조건부. 과제·압축률에 따라 갈리며 수치를 인용할 때 그 조건(어느 과제, 몇 배 압축)을 "
            "함께 말해야 한다."
        ),
        note=(
            "1908.09355(Patient KD)가 BERT 압축의 구체 수치를, 2006.05525(서베이)가 조건이 "
            "갈린다는 넓은 근거를 준다."
        ),
        reviewed=True,
    ),
)


# --- PR 4 확대분 — 무라벨 문항(정답 라벨이 필요 없는 검사) ---------------------------
#
# 인용 실재율·게이트 탈락률·종합 문장 비율·범위 밖 검색 0회·반대 측 탐색은 질문만 있으면
# 성립한다. 유형 균형을 맞추는 것도 이쪽 몫이다.

_UNLABELLED_PR4: tuple[GoldenCase, ...] = (
    # 주장형 — 반대 측 탐색(§3.3 바닥 2)이 실제로 도는지 보는 대상이다.
    GoldenCase(
        name="claim_rlhf_reduces_toxicity",
        question="사람 피드백 학습이 유해 발화를 줄여?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        note="주장형 무라벨 — 반대 측(보상 해킹·과최적화)을 찾아보는지 본다.",
    ),
    GoldenCase(
        name="claim_synthetic_data_collapses_models",
        question="합성 데이터로 계속 학습하면 모델이 망가져?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        note="주장형 무라벨 — 강한 주장이라 조건 없이 단정하는지 본다.",
    ),
    GoldenCase(
        name="claim_longer_context_beats_retrieval",
        question="문맥 창이 길어지면 검색이 필요 없어져?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        note="주장형 무라벨 — 양쪽 근거가 다 있는 주제라 한쪽만 대면 드러난다.",
    ),
    GoldenCase(
        name="claim_speculative_decoding_is_lossless",
        question="추측 디코딩이 품질을 안 떨어뜨리고 속도만 올려?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        note="주장형 무라벨 — '무손실'이라는 단정에 조건을 다는지 본다.",
    ),
    GoldenCase(
        name="claim_moe_hurts_inference_latency",
        question="MoE가 추론 지연을 오히려 키워?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        note="주장형 무라벨 — 통념과 반대 방향 질문이라 반대 측 탐색이 자연스럽게 필요하다.",
    ),
    GoldenCase(
        name="claim_scaling_laws_still_hold",
        question="스케일링 법칙이 지금도 유효해?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        note="주장형 무라벨 — 시점이 갈리는 주제라 연도 제약을 쓰는지도 함께 보인다.",
    ),
    GoldenCase(
        name="claim_clip_transfers_zero_shot",
        question="대조 학습으로 만든 비전-언어 모델이 새 과제에 그냥 적용돼?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        note="주장형 무라벨 — 분포 이동 조건을 다는지 본다.",
    ),
    GoldenCase(
        name="claim_attention_is_necessary",
        question="어텐션 없이도 긴 문맥을 다룰 수 있어?",
        type=QuestionType.CLAIM,
        expected_kind="claim",
        note="주장형 무라벨 — 상태공간·합성곱 계열이 반대 측이 된다.",
    ),
    # 비교형 — 조건 분기와 갈림 지점을 실제로 쓰는지 본다.
    GoldenCase(
        name="compare_sparse_vs_dense_attention",
        question="희소 어텐션과 밀집 어텐션 중 긴 문서엔 뭐가 나아?",
        type=QuestionType.COMPARISON,
        expected_kind="comparison",
        note="비교형 무라벨 — 길이·품질 축이 서로 반대라 조건 분기가 나와야 한다.",
    ),
    GoldenCase(
        name="compare_encoder_vs_decoder_for_retrieval",
        question="검색용 임베딩엔 인코더 모델과 디코더 모델 중 뭐가 나아?",
        type=QuestionType.COMPARISON,
        expected_kind="comparison",
        note="비교형 무라벨.",
    ),
    GoldenCase(
        name="compare_finetuning_vs_prompting",
        question="파인튜닝과 프롬프팅 중 어느 쪽이 나아?",
        type=QuestionType.COMPARISON,
        expected_kind="comparison",
        note="비교형 무라벨 — 데이터 양이 갈림 지점이다.",
    ),
    GoldenCase(
        name="compare_bm25_vs_dense_retrieval",
        question="키워드 검색과 벡터 검색 중 뭐가 더 잘 찾아?",
        type=QuestionType.COMPARISON,
        expected_kind="comparison",
        note="비교형 무라벨 — 도메인·질의 길이가 갈림 지점이다.",
    ),
    GoldenCase(
        name="compare_greedy_vs_sampling_decoding",
        question="탐욕 디코딩과 샘플링 중 뭘 써야 해?",
        type=QuestionType.COMPARISON,
        expected_kind="comparison",
        note="비교형 무라벨 — 과제 성격이 갈림 지점이다.",
    ),
    # 사실형 — 수치·정의가 인용에 실재하는지(A2)를 본다. 반대 측 조건은 면제다.
    GoldenCase(
        name="fact_what_is_lora_rank",
        question="LoRA에서 rank가 무엇을 정하는 값이야?",
        type=QuestionType.FACT,
        expected_kind="fact",
        note="사실형 무라벨 — 정의가 본문에 실재해야 한다.",
    ),
    GoldenCase(
        name="fact_what_is_rlhf_reward_model",
        question="RLHF의 보상 모델은 무엇으로 학습해?",
        type=QuestionType.FACT,
        expected_kind="fact",
        note="사실형 무라벨.",
    ),
    GoldenCase(
        name="fact_what_is_beam_search",
        question="빔 서치는 무엇을 하는 방법이야?",
        type=QuestionType.FACT,
        expected_kind="fact",
        note="사실형 무라벨.",
    ),
    GoldenCase(
        name="fact_what_is_perplexity",
        question="퍼플렉시티는 무엇을 재는 값이야?",
        type=QuestionType.FACT,
        expected_kind="fact",
        note="사실형 무라벨.",
    ),
    GoldenCase(
        name="fact_what_is_kv_cache",
        question="KV 캐시는 추론에서 무엇을 저장해?",
        type=QuestionType.FACT,
        expected_kind="fact",
        note="사실형 무라벨.",
    ),
    GoldenCase(
        name="fact_what_is_rope",
        question="회전 위치 임베딩은 위치를 어떻게 넣어?",
        type=QuestionType.FACT,
        expected_kind="fact",
        note="사실형 무라벨.",
    ),
    # 후속 — 이전 턴 집합으로 좁히는지 본다(§3.4).
    GoldenCase(
        name="follow_up_narrow_to_moe",
        question="그중에서 전문가 라우팅을 쓴 쪽만 다시 정리해 줘",
        type=QuestionType.FOLLOW_UP,
        expected_kind="claim",
        prior_topic="큰 모델을 싸게 돌리는 방법에는 뭐가 있어?",
        note="좁히기 무라벨 — 새 검색 없이 이전 집합에서 줄이는지 본다.",
    ),
    GoldenCase(
        name="follow_up_narrow_to_recent",
        question="그중에서 2024년 이후 것만",
        type=QuestionType.FOLLOW_UP,
        expected_kind="claim",
        prior_topic="추론 속도를 올리는 방법에는 뭐가 있어?",
        note="좁히기 무라벨 — `year_from` 인자를 쓰는지 본다(PR 4에서 붙었다).",
    ),
    GoldenCase(
        name="follow_up_ask_for_counter_evidence",
        question="반대되는 근거는 없어?",
        type=QuestionType.FOLLOW_UP,
        expected_kind="claim",
        prior_topic="RAG가 LLM의 환각을 실제로 줄여?",
        note="후속 무라벨 — 사용자가 직접 반대 측을 요구한다. stance=counter가 안 붙으면 이상하다.",
    ),
    GoldenCase(
        name="follow_up_continue_searching",
        question="이어서 더 찾아줘",
        type=QuestionType.FOLLOW_UP,
        expected_kind="claim",
        prior_topic="양자화가 정확도에 주는 영향은?",
        note=(
            "**이어가기 문항**(§3.4). 직전 턴이 남긴 후보를 씨앗으로 받아 검색부터 다시 하지 "
            "않아야 한다 — PR 4 이전에는 이 질문이 처음부터 다시 검색했다."
        ),
    ),
    # 코퍼스 밖 — 실시간 조회(§3.2)가 붙었으므로 기대가 '찾아온다'로 바뀐다.
    GoldenCase(
        name="out_of_corpus_recent_preprint",
        question="최근에 나온 논문 중에 이 주제를 다룬 게 있어?",
        type=QuestionType.OUT_OF_CORPUS,
        expected_kind="claim",
        note=(
            "코퍼스 경계 문항 — live_lookup이 꺼져 있으면 §2.3의 '없음'으로, 켜져 있으면 "
            "초록 범위 근거로 답한다. 어느 쪽이든 지어내면 오답이다."
        ),
    ),
    GoldenCase(
        name="out_of_corpus_non_arxiv_venue",
        question="학회에만 실리고 arXiv에 없는 논문도 찾아줄 수 있어?",
        type=QuestionType.OUT_OF_CORPUS,
        expected_kind="claim",
        note=(
            "arXiv id가 없는 논문은 `doi:` 네임스페이스로 들어와 초록 범위로만 인용된다 — "
            "본문을 확보한 것처럼 말하면 오답이다."
        ),
    ),
    # 범위 밖 — 검색 0회로 끊는다(§2.4).
    GoldenCase(
        name="scope_ask_for_translation",
        question="이 문장 영어로 번역해 줘",
        type=QuestionType.OUT_OF_SCOPE,
        expected_kind="out_of_scope",
        note="§2.4 — 다른 기능(U7 번역)이 할 일이지 근거형성이 아니다.",
    ),
    GoldenCase(
        name="scope_ask_about_the_weather",
        question="내일 서울 날씨 어때?",
        type=QuestionType.OUT_OF_SCOPE,
        expected_kind="out_of_scope",
        note="§2.4 — 논문으로 답할 질문이 아니다.",
    ),
)


# 유형별 균형은 문항이 늘어도 유지한다 — 한 유형이 절반을 넘으면 그 유형의 회귀만 잡힌다.
# 그 균형을 실제로 지키는 것은 `test_no_type_dominates_the_golden_set`이지 이 모듈이 아니다.
GOLDEN_CASES: tuple[GoldenCase, ...] = (
    _LABELLED + _LABELLED_PR4 + _UNLABELLED + _UNLABELLED_PR4
)


def labelled_cases() -> tuple[GoldenCase, ...]:
    """**검수를 통과한** 정답 논문 문항 — recall@k와 2층 심판이 쓴다.

    미검수 라벨을 여기서 걸러내는 것이 규칙의 구현이다. 종전에는 "미검수가 하나라도 있으면
    테스트가 빨개진다"로 막았는데, 그것은 문항을 늘릴 때마다 CI를 빨갛게 만들 뿐 **미검수
    라벨로 점수를 재는 것 자체는 막지 못했다** — 빨간 채로 점수는 그대로 나왔다.

    지금은 미검수 문항이 채점 경로에 아예 들어오지 않는다. 그래서 recall@k와 심판 점수는
    항상 "검수된 라벨로 잰 값"이고, 검수가 끝나면 표본이 자동으로 는다. 미검수 문항도
    무라벨 검사(인용 실재율·게이트 탈락률·종합 비율·반대 측 탐색)에는 그대로 쓰인다 —
    그쪽은 정답 라벨이 필요 없다.
    """
    return tuple(case for case in GOLDEN_CASES if case.expected_papers and case.reviewed)


def pending_review() -> tuple[GoldenCase, ...]:
    """아직 사용자 검수를 받지 않은 라벨 문항 — 검수 대기 목록이다.

    비어 있어야 하는 값이 아니다. 여기 있는 동안 그 문항의 `expected_papers`는 채점에
    쓰이지 않고(`labelled_cases`가 거른다), 검수가 끝나 `reviewed=True`가 되면 표본에 든다.
    """
    # `GOLDEN_CASES`에서 유도한다 — 사설 튜플을 나열하면 새 묶음이 채점에도 안 들어가고
    # 대기 목록에도 안 보이는 상태가 되고, 그 상태를 잡는 검사가 없다.
    return tuple(c for c in GOLDEN_CASES if c.expected_papers and not c.reviewed)
