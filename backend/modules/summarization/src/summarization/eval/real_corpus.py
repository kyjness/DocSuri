"""Held-out numeric-grounding corpus built from REAL paper result figures (QT-1).

Unlike ``numeric_corpus`` (a synthetic fraction spectrum) the *source* spans here are real
result/Table figures excerpted from open-access arXiv papers (BERT, ResNet, ViT, RoBERTa,
EfficientNet, CLIP, GPT-3, T5). Only the minimal numeric spans needed to verify a draft are
stored — NOT the paper bodies (SEC-3: keep just the spans). Drafts are constructed: a
*faithful* draft quotes the paper's real figures; a *fabricated* draft replaces a controlled
share of them with figures absent from the span, so a sweep over
``_NUMERIC_MISMATCH_THRESHOLD`` traces the false-pass / false-abstain curve on realistic
numeric density.

Labeling: clear ends (few or most figures fabricated) are ``confident=True`` (assertable).
The policy-sensitive middle (⅓ … ⅔ of figures unverifiable) is ``confident=False`` — whether
"about half the numbers are unsupported" counts as fabricated is a REVIEWER/policy call (OP/team
owns the final label), not derivable from data. Each fabricated figure is chosen well clear of
every source figure (and of its ×100 / rounding-band neighborhood) so the intended ungrounded
fraction is exact — verified by running the validator (see ``tests/test_real_corpus.py``).
"""

from __future__ import annotations

from ..domain.models import GroundingInput, RefinedSource, SummaryDraft
from .grounding_eval import GroundingEvalCase


def _case(
    name: str,
    source_body: str,
    grounded: tuple[str, ...],
    fabricated: tuple[str, ...],
    expected: str,
    rationale: str,
    *,
    confident: bool,
) -> GroundingEvalCase:
    """Build a numeric case. ``source_body`` is the real excerpted span; ``grounded`` figures
    appear in it, ``fabricated`` figures do not. The draft's results list both, fixing the
    ungrounded fraction at ``len(fabricated) / (len(grounded) + len(fabricated))``."""
    figures = ", ".join(f"{x} percent" for x in (*grounded, *fabricated))
    draft = SummaryDraft(
        tldr="A concise summary of the paper's contribution.",
        contributions=("The primary contribution.",),
        method="The method is described in full.",
        results=f"Reported figures: {figures}.",
        limitations="The stated limitations.",
        reproducibility={"code": "released", "data": "public"},
        anchors=(),
    )
    return GroundingEvalCase(
        name=name,
        gi=GroundingInput(draft=draft, refined=RefinedSource(body=source_body, captions=())),
        expected=expected,
        rationale=rationale,
        confident=confident,
    )


# --- Real source spans (verbatim numeric excerpts) ---------------------------------------
# Tight spans: only the figures a case verifies against, so a fabricated draft number cannot
# accidentally ground against an unrelated figure left in the body.

_BERT = (
    "BERT pushes the GLUE score to 80.5, MultiNLI accuracy to 86.7, and SQuAD v1.1 Test F1 "
    "to 93.2; on dev it reaches 84.4 on MNLI-m and 92.7 on SST-2."
)
_RESNET = (
    "An ensemble of residual nets achieves 3.57 error on the ImageNet test set; the 152-layer "
    "ResNet has a single-model top-5 error of 4.49, and the 110-layer net reaches 6.43 on "
    "CIFAR-10. Plain 18- vs 34-layer validation error is 27.94 and 28.54."
)
_VIT = (
    "The best model reaches 88.55 on ImageNet, 90.72 on ImageNet-ReaL, and 94.55 on CIFAR-100; "
    "the self-supervised ViT-B/16 reaches 79.9 on ImageNet."
)
_ROBERTA = (
    "RoBERTa scores 88.5 on the GLUE leaderboard; static masking gives 84.3 MNLI-m and 92.5 "
    "SST-2, and the full model reaches 94.6 and 89.4 SQuAD 1.1/2.0 F1."
)
_EFFNET = (
    "EfficientNet-B7 achieves 84.3 top-1 accuracy on ImageNet; B4 improves top-1 from 76.3 to "
    "83.0, and EfficientNets reach 91.7 on CIFAR-100."
)
_CLIP = (
    "CLIP improves ImageNet accuracy from a proof of concept 11.5 to 76.2 zero-shot, reaching "
    "95 top-5 accuracy; there is an average train-test overlap of 3.2."
)
_GPT3 = (
    "GPT-3 reaches 81.5 F1 on CoQA zero-shot, 64.3 accuracy on TriviaQA zero-shot rising to "
    "71.2 few-shot, and 86.4 in the few-shot setting on another task; perplexity on PTB is 20.5."
)
_T5 = (
    "The baseline T5 averages 83.28 on GLUE, 80.88 on SQuAD, and 71.36 on SuperGLUE, and "
    "scores 19.24 on CNN/DM."
)


REAL_CORPUS: tuple[GroundingEvalCase, ...] = (
    # ---- Clear faithful (0 ungrounded) — all figures real ----
    _case(
        "bert_faithful_0of5", _BERT,
        ("80.5", "86.7", "93.2", "84.4", "92.7"), (),
        "faithful", "All five GLUE/MNLI/SQuAD/SST-2 figures appear verbatim in the source.",
        confident=True,
    ),
    _case(
        "resnet_faithful_0of4", _RESNET,
        ("3.57", "4.49", "6.43", "27.94"), (),
        "faithful", "ImageNet/CIFAR error figures all present in the source span.",
        confident=True,
    ),
    _case(
        "vit_faithful_0of4", _VIT,
        ("88.55", "90.72", "94.55", "79.9"), (),
        "faithful", "ImageNet/ReaL/CIFAR-100 and self-supervised figures all grounded.",
        confident=True,
    ),
    _case(
        "roberta_faithful_0of5", _ROBERTA,
        ("88.5", "84.3", "92.5", "94.6", "89.4"), (),
        "faithful", "GLUE/MNLI/SST-2/SQuAD figures all present in the source span.",
        confident=True,
    ),
    _case(
        "gpt3_faithful_0of5", _GPT3,
        ("81.5", "64.3", "71.2", "86.4", "20.5"), (),
        "faithful", "CoQA/TriviaQA/few-shot/perplexity figures all grounded.",
        confident=True,
    ),
    # ---- matcher-precision faithful (rounding band / percent↔fraction) ----
    _case(
        "vit_rounding_faithful", _VIT,
        ("94.5",), (),
        "faithful",
        "94.5 is a correct rounding of source 94.55 (within half-a-ULP); matcher grounds it.",
        confident=True,
    ),
    _case(
        "clip_fraction_faithful", _CLIP,
        ("0.762",), (),
        "faithful",
        "0.762 is the fraction form of source 76.2 percent (×100); matcher grounds it.",
        confident=True,
    ),
    # ---- low ungrounded (a stray/mis-transcribed figure) — still faithful ----
    _case(
        "efficientnet_faithful_1of4", _EFFNET,
        ("84.3", "76.3", "83.0"), ("59.1",),
        "faithful",
        "Three figures grounded, one stray (59.1) absent → 1/4 = 0.25 ≤ 0.5, a tolerable "
        "single mis-transcription, summary still faithful.",
        confident=True,
    ),
    _case(
        "bert_faithful_1of5", _BERT,
        ("80.5", "86.7", "93.2", "84.4"), ("57.7",),
        "faithful",
        "One absent figure out of five (0.20) — a minor slip, not fabrication.",
        confident=True,
    ),
    # ---- policy-sensitive middle (⅓ … ⅔) — PROBES, reviewer's label ----
    _case(
        "bert_probe_1of3", _BERT,
        ("80.5", "86.7"), ("50.3",),
        "faithful",
        "1/3 = 0.33 ungrounded. Below the recalibrated 0.4 so the gate PASSES; whether one "
        "unsupported figure among three is 'fabricated' is a policy call.",
        confident=False,
    ),
    _case(
        "resnet_probe_2of5", _RESNET,
        ("3.57", "4.49", "6.43"), ("11.1", "22.2"),
        "faithful",
        "2/5 = 0.40 ungrounded — the largest faithful share in the corpora, sitting exactly ON "
        "the recalibrated threshold: passes via strict `>` (0.40 is not > 0.4). This case is "
        "the evidence the threshold cannot go below 0.4 without over-abstaining.",
        confident=False,
    ),
    _case(
        "roberta_probe_2of4", _ROBERTA,
        ("88.5", "84.3"), ("12.6", "45.1"),
        "fabricated",
        "2/4 = 0.50 exactly — a false-pass under the pre-Phase-3 threshold 0.5 (0.50 is not "
        "> 0.5). Settled by the US-S6 recalibration to 0.4: the gate now ABSTAINS (caught).",
        confident=False,
    ),
    _case(
        "gpt3_probe_2of3", _GPT3,
        ("81.5",), ("33.4", "47.8"),
        "fabricated",
        "2/3 = 0.67 ungrounded. Above the threshold so the gate ABSTAINS; label leans "
        "fabricated but the exact policy at this density is the reviewer's.",
        confident=False,
    ),
    # ---- clear fabricated (majority / all figures invented) ----
    _case(
        "vit_fabricated_3of5", _VIT,
        ("88.55", "90.72"), ("33.1", "44.2", "55.3"),
        "fabricated",
        "3/5 = 0.60 ungrounded (> 0.5) → abstain. Most figures invented.",
        confident=True,
    ),
    _case(
        "clip_fabricated_3of4", _CLIP,
        ("76.2",), ("31.5", "42.6", "53.7"),
        "fabricated",
        "3/4 = 0.75 ungrounded → abstain. Only one real figure among four.",
        confident=True,
    ),
    _case(
        "t5_fabricated_2of3", _T5,
        ("83.28",), ("41.1", "52.2"),
        "fabricated",
        "2/3 = 0.67 ungrounded → abstain. Majority of reported figures absent from source.",
        confident=True,
    ),
    _case(
        "gpt3_fabricated_4of4", _GPT3,
        (), ("12.1", "23.2", "34.3", "45.4"),
        "fabricated",
        "4/4 = 1.00 ungrounded → abstain. Every reported figure invented.",
        confident=True,
    ),
    _case(
        "resnet_headline_fabricated", _RESNET,
        (), ("9.91",),
        "fabricated",
        "A single fabricated headline error figure (9.91) absent from source → 1/1 abstain.",
        confident=True,
    ),
)

REAL_CONFIDENT: tuple[GroundingEvalCase, ...] = tuple(c for c in REAL_CORPUS if c.confident)
REAL_PROBES: tuple[GroundingEvalCase, ...] = tuple(c for c in REAL_CORPUS if not c.confident)
