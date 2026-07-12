"""Deterministic standard-term enforcement by placeholder masking (BR-S4).

전문 번역에서 DocSuri **표준 용어**(seed keep-as-is + seed mappings)는 첫 번역부터 강제돼야 하는데,
프롬프트 지시만으로는 LLM이 무시하면 ``Transformer``→"변환기", ``attention``→"주의"처럼 뚫린다. 사후
후치환으로는 못 잡는다 — "변환기"가 ``Transformer``에서 왔는지, "주의"가 ``attention``에서 왔는지
사후엔 알 수 없기 때문이다(다의어 오치환 위험). 그래서 **번역 전** 소스(영어) 세그먼트의 표준 용어를
opaque 토큰(``⟦G7⟧``)으로 치환하고, LLM은 토큰을 그대로 보존하도록 지시받는다. **serve 시점**에
토큰을 effective 렌더링(seed 기본값 또는 사용자 강한 오버라이드)으로 복원하므로 표준 용어의 최종
표기가 LLM 판단과 무관하게 **결정적으로** 보장된다.

토큰↔용어 배정은 seed에서 결정적으로 재계산한다(저장하지 않음): 같은 seed면 생성·serve가 같은 표를
만든다. seed 변경은 캐시 키의 ``seed_ver``가 흡수한다. 캐시 base는 **토큰을 그대로 보유**하고 복원은
항상 serve에서 일어나므로, 표준 용어 편집은 재생성 없이 다음 serve의 재렌더로 즉시 반영된다(매핑만
갱신). 복원 시 한국어 조사(은/는·이/가·을/를·와/과·(으)로)를 복원 용어의 받침으로 재정규화한다 —
placeholder는 LLM에 받침 정보를 주지 못하므로 매핑(→한국어)에서 조사가 어긋나기 때문이다.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# --- token scheme ------------------------------------------------------------
# ``⟦G{i}⟧`` — mathematical white brackets + a ``G`` (glossary) marker + the seed index. AI/ML
# papers effectively never use these brackets as content, and the model treats the run as an opaque
# identifier (reinforced by a prompt instruction to preserve ``⟦N⟧`` verbatim). The restore regex is
# whitespace-tolerant (``⟦ G 7 ⟧``) so a model that pads the token still round-trips.
_TOKEN_OPEN = "⟦"  # noqa: S105 — a bracket delimiter, not a secret
_TOKEN_CLOSE = "⟧"  # noqa: S105 — a bracket delimiter, not a secret


def token_for(index: int) -> str:
    return f"{_TOKEN_OPEN}G{index}{_TOKEN_CLOSE}"


# Whitespace-tolerant token finder (``⟦ G 7 ⟧``) — used to verify the model returned every planted
# token (a dropped token = a vanished standard term, which no read-time step can resurrect).
_TOKEN_FIND_RE = re.compile(rf"{_TOKEN_OPEN}\s*G\s*(\d+)\s*{_TOKEN_CLOSE}")


def found_token_indices(text: str) -> set[int]:
    """Set of token indices present in ``text`` (tolerant to whitespace padding by the model)."""
    return {int(m.group(1)) for m in _TOKEN_FIND_RE.finditer(text)}


def contains_token(text: str) -> bool:
    """True if the string carries a placeholder token (bracket). The model sometimes echoes the
    masked tokens back in its free-form ``keptTerms`` ("I kept ⟦G0⟧ verbatim"), so the serve step
    uses this to keep those internal artifacts out of the user-facing 원어 유지 용어 list. The
    bracket chars never occur in real paper terms, so their mere presence marks a token artifact."""
    return _TOKEN_OPEN in text or _TOKEN_CLOSE in text


# Korean josa allomorph pairs — (form-after-batchim, form-after-vowel). (으)로 is special-cased
# (ㄹ받침 takes 로, like a vowel) in :func:`normalize_particle`.
_PARTICLE_PAIRS: dict[str, tuple[str, str]] = {
    "은": ("은", "는"),
    "는": ("은", "는"),
    "이": ("이", "가"),
    "가": ("이", "가"),
    "을": ("을", "를"),
    "를": ("을", "를"),
    "과": ("과", "와"),
    "와": ("과", "와"),
    "으로": ("으로", "로"),
    "로": ("으로", "로"),
}
# Longest-first so ``으로`` wins over ``로`` (they don't share a first char, but keep it explicit).
_PARTICLE_ALT = "|".join(sorted(_PARTICLE_PAIRS, key=len, reverse=True))

# has-batchim flag for the fixed keep-as-is set, by the term's Korean *reading* (음독), for josa
# normalization when the restored term is English (a token carries no phonetic info, so the model's
# particle after ``⟦G0⟧`` is arbitrary). Only confident readings are listed; ambiguous ones (T5,
# ViT, MoE, PEFT…) are omitted → the model's particle is left as-is (best-effort, BR-S4 note).
_KEEPASIS_BATCHIM: dict[str, bool] = {
    "transformer": False,  # 트랜스포머
    "bert": False,  # 버트
    "gpt": False,  # 지피티
    "bart": False,  # 바트
    "roberta": False,  # 로베르타
    "clip": True,  # 클립(ㅂ)
    "resnet": True,  # 레스넷(ㅅ)
    "u-net": True,  # 유넷(ㅅ)
    "cnn": True,  # 씨엔엔(ㄴ)
    "rnn": True,  # 알엔엔(ㄴ)
    "lstm": True,  # 엘에스티엠(ㅁ)
    "gan": True,  # 간(ㄴ)
    "gnn": True,  # 지엔엔(ㄴ)
    "lora": False,  # 로라
    "rag": True,  # 래그(ㄱ)
    "fine-tuning": True,  # 파인튜닝(ㅇ)
    "llm": True,  # 엘엘엠(ㅁ)
    "sota": False,  # 소타
    "relu": False,  # 렐루
    "adam": True,  # 아담(ㅁ)
    "sgd": False,  # 에스지디
    "imagenet": True,  # 이미지넷(ㅅ)
    "bleu": False,  # 블루
    "rouge": False,  # 루지
    "f1": True,  # 에프원(ㄴ)
    "auc": False,  # 에이유씨
    "iou": False,  # 아이오유
}


@dataclass(frozen=True, slots=True)
class MaskEntry:
    index: int
    term_from: str  # English source form matched in the paper (e.g. "attention", "Transformer")
    kind: str  # "keepasis" | "mapping"
    seed_render: str  # default rendering (keepasis → English original; mapping → Korean target)

    @property
    def token(self) -> str:
        return token_for(self.index)


@dataclass(frozen=True)
class MaskTable:
    entries: tuple[MaskEntry, ...]

    def by_index(self, index: int) -> MaskEntry | None:
        return self._by_index.get(index)

    def __post_init__(self) -> None:
        # frozen (no slots) → __dict__ exists; cache an index lookup for O(1) restore.
        object.__setattr__(self, "_by_index", {e.index: e for e in self.entries})


def build_mask_table() -> MaskTable:
    """Deterministic token↔term table from the SHARED SEED constants (not any user's glossary): user
    overrides never change token identity — only the *rendering* at serve. keep-as-is terms take
    indices first, then seed mappings, so the assignment is stable across generation and serve for
    one seed version (seed edits self-invalidate via the cache key's ``seed_ver``). Reading the code
    constants directly (rather than a passed ``Glossary``) keeps the table robust no matter what
    glossary the caller holds. Lazy import avoids a module cycle (glossary imports models only)."""
    from .glossary import SEED_KEEP_AS_IS, SEED_MAPPINGS

    entries: list[MaskEntry] = []
    i = 0
    for term in SEED_KEEP_AS_IS:
        entries.append(MaskEntry(i, term, "keepasis", term))
        i += 1
    for m in SEED_MAPPINGS:
        entries.append(MaskEntry(i, m.term_from, "mapping", m.term_to))
        i += 1
    return MaskTable(tuple(entries))


def _boundary_re(term: str) -> re.Pattern[str]:
    # Word boundaries: "F1"/"T5" don't match inside "F12", and "U-Net"/"fine-tuning"/"latent space"
    # match as written. ``_`` counts as a boundary char too, so a term inside an identifier
    # (``attention_weights``, ``gpt_config``) is NOT masked into a corrupted mixed token — that
    # occurrence falls back to the prompt's variant guidance. Case-insensitive so a lowercase
    # occurrence ("transformer") is still caught (restored to canonical casing).
    body = re.escape(term)
    return re.compile(rf"(?<![A-Za-z0-9_]){body}(?![A-Za-z0-9_])", re.IGNORECASE)


def mask_text(text: str, table: MaskTable) -> tuple[str, set[int]]:
    """Replace every standard-term occurrence in an ENGLISH source segment with its token.

    Longest-term-first so ``fine-tuning`` masks before any ``fine`` and ``latent space`` before
    ``latent``. Returns the masked text and the set of token indices actually planted (so the caller
    can verify the model returned them all — a dropped token means a vanished concept). Tokens are
    inert to later passes (``⟦G7⟧`` contains no term-boundary match), so sequential replace is safe.
    """
    planted: set[int] = set()
    for entry in sorted(table.entries, key=lambda e: len(e.term_from), reverse=True):
        pattern = _boundary_re(entry.term_from)
        if pattern.search(text):
            text = pattern.sub(entry.token, text)
            planted.add(entry.index)
    return text, planted


def _final_jamo(term: str) -> tuple[bool, bool] | None:
    """(has_batchim, is_rieul) of the term's final sound, or None when undeterminable.

    Hangul: exact via the syllable-block formula. Non-Hangul (English keep-as-is): the curated
    reading table; None (→ leave the model's particle) for uncurated/ambiguous terms."""
    t = term.rstrip()
    if not t:
        return None
    c = t[-1]
    if "가" <= c <= "힣":
        code = (ord(c) - 0xAC00) % 28
        return (code != 0, code == 8)
    has_batchim = _KEEPASIS_BATCHIM.get(t.lower())
    if has_batchim is None:
        return None
    return (has_batchim, False)


def normalize_particle(term: str, particle: str) -> str:
    """Return the correct josa allomorph for ``particle`` following ``term``.

    Exact for a Hangul-final term (mappings, Korean overrides); for an English keep-as-is term it
    uses the curated reading, else returns the model's ``particle`` unchanged (best-effort)."""
    pair = _PARTICLE_PAIRS.get(particle)
    if pair is None:
        return particle
    info = _final_jamo(term)
    if info is None:
        return particle
    has_batchim, is_rieul = info
    if particle in ("으로", "로"):
        # (으)로: vowel-ending AND ㄹ받침 take the short 로; other 받침 take 으로.
        return "로" if (not has_batchim or is_rieul) else "으로"
    after_batchim, after_vowel = pair
    return after_batchim if has_batchim else after_vowel


# Whitespace-tolerant token (``⟦ G 7 ⟧``) optionally followed by a josa that is NOT itself the first
# syllable of the next word. The negative lookahead ``(?![가-힣])`` is the disambiguator: in
# ``⟦G7⟧은닉층`` the ``은`` is followed by ``닉`` (Hangul) → the optional josa group fails to match,
# so ``은닉층`` stays intact and only the token is replaced. A josa is consumed only when followed
# by whitespace / punctuation / end-of-text.
_RENDER_RE = re.compile(
    rf"{_TOKEN_OPEN}\s*G\s*(\d+)\s*{_TOKEN_CLOSE}(?:({_PARTICLE_ALT})(?![가-힣]))?"
)
# Defensive final sweep: any residual token-like run (e.g. index the table doesn't know) is removed
# so a raw ``⟦…⟧`` never reaches the reader.
_RESIDUAL_RE = re.compile(rf"{_TOKEN_OPEN}\s*G?\s*\d*\s*{_TOKEN_CLOSE}")


def render_tokens(
    text: str, table: MaskTable, effective: Callable[[MaskEntry], str]
) -> tuple[str, set[int]]:
    """Restore tokens → ``effective`` rendering with josa normalization; return (text, seen idx).

    ``effective(entry)`` yields the rendering to insert (seed default, or the user's strong
    override). ``seen`` is the set of token indices found — the caller uses it to build the
    standardGlossary from terms that actually occur (exact, no string-match heuristic). A residual
    unknown token is swept to empty so no ``⟦…⟧`` leaks to the reader (fail-soft)."""
    seen: set[int] = set()

    def _repl(m: re.Match[str]) -> str:
        entry = table.by_index(int(m.group(1)))
        if entry is None:
            return ""  # unknown index (seed drift) — drop the marker; residual sweep also guards
        seen.add(entry.index)
        rendered = effective(entry)
        particle = m.group(2)
        if particle:
            return rendered + normalize_particle(rendered, particle)
        return rendered

    out = _RENDER_RE.sub(_repl, text)
    if _RESIDUAL_RE.search(out):
        # A token the render regex didn't recognise survived (corruption beyond tolerant matching).
        # Strip it so the reader never sees ``⟦…⟧``; observed for diagnosis (BR-S4 fail-soft).
        logger.warning("masking: residual token(s) swept from rendered translation")
        out = _RESIDUAL_RE.sub("", out)
    return out, seen
