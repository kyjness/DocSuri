"""Korean josa (조사) allomorph selection shared by units that emit Korean prose.

Only what the Hangul syllable-block formula settles lives here. Deciding the final
sound of a non-Hangul term (an English word's Korean reading, an acronym) needs
domain knowledge — a glossary, a curated reading table — so callers keep that and
hand in the answer, or accept the best-effort passthrough.

Used by u7 term masking (which adds its own keep-as-is reading table) and by u12
agent replies (Hangul labels only).
"""

from __future__ import annotations

__all__ = ["PARTICLE_PAIRS", "attach_particle", "final_jamo", "select_particle"]

# (form-after-batchim, form-after-vowel). (으)로 is special-cased in select_particle
# — ㄹ받침 takes the short 로, like a vowel ending.
PARTICLE_PAIRS: dict[str, tuple[str, str]] = {
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


def final_jamo(term: str) -> tuple[bool, bool] | None:
    """(has_batchim, is_rieul) of a Hangul-final term, or None when not Hangul-final.

    None means "undeterminable here", not "no batchim" — callers that own a reading
    table for non-Hangul terms answer it themselves.
    """
    stripped = term.rstrip()
    if not stripped:
        return None
    last = stripped[-1]
    if not ("가" <= last <= "힣"):
        return None
    code = (ord(last) - 0xAC00) % 28
    return (code != 0, code == 8)


def select_particle(particle: str, final: tuple[bool, bool] | None) -> str:
    """The allomorph of ``particle`` for a final sound described by ``final``.

    Returns ``particle`` unchanged for an unknown particle or an undeterminable
    final — best effort, never a wrong-looking guess.
    """
    pair = PARTICLE_PAIRS.get(particle)
    if pair is None or final is None:
        return particle
    has_batchim, is_rieul = final
    if particle in ("으로", "로"):
        return "로" if (not has_batchim or is_rieul) else "으로"
    after_batchim, after_vowel = pair
    return after_batchim if has_batchim else after_vowel


def attach_particle(term: str, particle: str) -> str:
    """``term`` followed by the right allomorph — avoids user-visible "계획을(를)"."""
    return f"{term}{select_particle(particle, final_jamo(term))}"
