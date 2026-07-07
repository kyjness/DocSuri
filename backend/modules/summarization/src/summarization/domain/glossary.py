"""GlossaryResolver — seed (P1) ∪ personal (P2) with two application paths (BR-S4 / Q8).

핵심 용어 보존은 프롬프트 단계에서 강제하고(keep-as-is + core mappings → prompt),
후치환은 사용자 선호 용어에 한정하여 단순 명사를 교정한다(deterministic post-substitution,
no LLM re-call). Post-substitution is restricted to simple nouns so Korean particle
attachment ("어텐션을/어텐션이") stays safe.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence

from ..ports.ports import GlossaryRepositoryPort
from .models import Glossary, TermMapping

# --- Shared seed glossary (§9.1) — SELECTION RULE ---------------------------------------------
# Evidence table + A/B/C/D grading + per-term sources live in the design record
# (functional-design/glossary-term-decisions.md); the governing rule is BR-S4. This seed is a
# small, GOVERNED, shared artifact injected into EVERY summary/translate prompt — not a dictionary.
# It is finalized once and frozen; the long tail of per-reader preferences is absorbed by the
# personal glossary, not by growing this seed. Two categories, by an explicit rule:
#   • keep-as-is (영어 유지): proper model/architecture names & abbreviations. Translating these
#     invites bad 음차/오역 and breaks source cross-reference, so they ride into the prompt as
#     "keep English". Justified by the RULE (proper name/abbrev), so obvious names may be listed
#     without per-term grading.
#   • prompt-enforced mappings (강한): ONLY high-frequency 음차 concept terms a general LLM is at
#     real risk of mis-translating into a wrong Korean word (attention→'주의', embedding→'매장').
#     Criterion: grade A/B AND enforcement-worth AND high-frequency. A-grade self-evident terms
#     (신경망·역전파…) are OMITTED — the LLM already renders them right, so seeding them only
#     inflates the prompt. C (mixed, e.g. gradient) / D (contested, e.g. regularization) excluded.
SEED_KEEP_AS_IS: tuple[str, ...] = (
    # Architectures / models
    "Transformer", "BERT", "GPT", "T5", "BART", "RoBERTa", "CLIP", "ViT", "ResNet", "U-Net",
    "CNN", "RNN", "LSTM", "MLP", "GAN", "VAE", "GNN", "MoE", "LoRA", "RAG",
    # Training / alignment techniques (kept as coined — 'fine-tuning' is C-grade as a mapping
    # (파인튜닝/미세조정 mixed), so the mis-translation risk is sidestepped by keeping it English)
    "fine-tuning", "RLHF", "SFT", "PPO", "DPO", "PEFT",
    # Abbreviations / activations / optimizers
    "LLM", "SOTA", "ReLU", "Adam", "SGD",
    # Datasets / metrics (English acronyms in results sections)
    "ImageNet", "BLEU", "ROUGE", "F1", "AUC", "IoU",
)

# Prompt-enforced (강한) mappings — mis-translation-risk 음차 concept terms only (see rule above).
SEED_MAPPINGS: tuple[TermMapping, ...] = (
    TermMapping("attention", "어텐션", prompt_enforced=True),
    TermMapping("embedding", "임베딩", prompt_enforced=True),
    TermMapping("latent space", "잠재 공간", prompt_enforced=True),
)

# Lowercased keep-as-is set, precomputed once for O(1) membership — the response builder uses it to
# mark which kept terms are DocSuri standard (BR-S4), on every translate serialization.
SEED_KEEP_AS_IS_LOWER: frozenset[str] = frozenset(t.lower() for t in SEED_KEEP_AS_IS)


# --- kept-term display filter (BR-S4) -----------------------------------------------------------
# The model's free-form ``keptTerms`` (terms it left in English) also sweeps up math NOTATION —
# Greek variables (theta, eta), sub/superscripted symbols (W_q, L_att^sm), expressions
# (L(w+delta), O(rho^2)), LaTeX fragments (mathbb{E}, sqrt{2eta T}) — which are noise in the 원어
# 유지 용어 list. This deterministic predicate keeps keyword/name-like terms and drops notation, so
# the glossary shows words, not symbols. (Seeds are curated, so this only prunes free-form terms.)

# Greek-letter names + LaTeX command tokens that, standing alone, are notation, not a keyword.
# Layer/function names (Softmax, ReLU, Sigmoid…) are intentionally EXCLUDED — those are real terms.
_MATH_WORDS: frozenset[str] = frozenset(
    {
        "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta",
        "vartheta", "iota", "kappa", "lambda", "mu", "nu", "xi", "pi", "varpi", "rho", "varrho",
        "sigma", "varsigma", "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega",
        "nabla", "partial", "langle", "rangle", "odot", "oplus", "otimes", "cdot", "cdots",
        "ldots", "mid", "mathbb", "mathrm", "mathcal", "mathbf", "mathsf", "boldsymbol", "bm",
        "widehat", "widetilde", "hat", "tilde", "bar", "vec", "sqrt", "argmax", "argmin", "sum",
        "prod", "forall", "exists", "infty", "leftarrow", "rightarrow", "mapsto", "top", "ell",
    }
)

# Characters that signal a math expression / LaTeX fragment. Hyphen and '+' are allowed so real
# names survive (CIFAR-100, TimeMixer++); braces/parens/subscripts/relations/commas are not.
_MATH_CHARS: frozenset[str] = frozenset("{}\\^_()[]=<>|/,~⟨⟩∇√∂⊙⊕⊗·×∑∏∈≤≥≈≠±∗•←→↦")
_SUBTOKEN_RE = re.compile(r"[\s\-,]+")


def is_glossary_worthy(term: str) -> bool:
    """True when a kept term reads as a keyword/name worth a glossary chip; False when it is math
    notation the model reported as 'kept' (Greek vars, ``W_q``, ``L(w+delta)``, ``mathbb{E}``…).

    Rejects: length ≤ 1; any math metacharacter; any whitespace/hyphen/comma-delimited
    sub-token that is a Greek-letter/LaTeX-command word."""
    t = term.strip()
    if len(t) <= 1:
        return False
    if any(c in _MATH_CHARS for c in t):
        return False
    return not any(sub.lower() in _MATH_WORDS for sub in _SUBTOKEN_RE.split(t) if sub)


def term_in_text(term: str, text: str) -> bool:
    """True when a seed keep-as-is term (kept in English) actually occurs in the translated text.

    The keep-as-is seed list rides into EVERY translate prompt, so the model echoes the whole list
    back in ``keptTerms`` even for terms absent from the paper. Presence must therefore be verified
    against the text — mirroring the mapping branch's ``eff in translated_text`` check — so 표준/
    원어 유지 용어 shows only terms this paper really uses (BR-S4). Case-insensitive, alphanumeric
    word boundaries (so "F1"/"T5" don't match inside "F12", and "U-Net"/"fine-tuning" match)."""
    if not term or not text:
        return False
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.I) is not None


def _seed_signature() -> str:
    """Short content hash of the shared seed glossary (keep-as-is + prompt-enforced mappings).

    The seed rides into every summary/translate prompt, so it is part of the derived artifact's
    identity — editing it changes the base output. Folding this hash into the cache path makes a
    seed edit self-invalidate (new path → miss → regenerate) with no manual version bump."""
    payload = (
        tuple(SEED_KEEP_AS_IS),
        tuple((m.term_from, m.term_to, m.prompt_enforced) for m in SEED_MAPPINGS),
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()[:8]


SEED_VER = _seed_signature()

# Frozen marker of the seed shipped when the cache-key seed dimension was introduced. The seed
# segment is OMITTED from the cache path while ``SEED_VER`` equals this, so existing summary/
# translate objects stay valid on deploy (no gratuitous cache-wide regeneration). Editing the seed
# above changes ``SEED_VER`` → the segment appears → exactly the affected objects invalidate.
# NEVER update this literal to match a seed edit — doing so would defeat the invalidation.
# NOTE: as of the strong-term finalization (fine-tuning demoted to keep-as-is + keep-as-is
# enrichment) the shipped seed intentionally DIVERGES from this frozen baseline, so the segment is
# now ACTIVE and this deploy self-invalidates prior seed-based artifacts (empty corpus → ~0 cost).
_SEED_BASELINE_VER = "344c3ccb"


def seed_cache_segment() -> str:
    """Cache-path seed segment: empty while the seed matches the shipped baseline, else the
    current ``SEED_VER`` (so the path changes only when the seed actually changes)."""
    return "" if SEED_VER == _SEED_BASELINE_VER else SEED_VER


logger = logging.getLogger(__name__)


class GlossaryResolver:
    def __init__(self, repo: GlossaryRepositoryPort | None = None) -> None:
        self._repo = repo

    def resolve(self, user_id: str | None) -> Glossary:
        overrides: Sequence[TermMapping] = ()
        if self._repo is not None and user_id is not None:
            try:
                overrides = tuple(self._repo.get_user_glossary(user_id))
            except Exception:  # noqa: BLE001 — personal-term overrides are OPTIONAL; a repo fault
                # (DB unavailable, table not yet migrated) must not abstain the whole summary/
                # translate. Degrade to the shared seed glossary (no personal terms).
                logger.warning(
                    "personal glossary lookup failed — degrading to seed-only", exc_info=True
                )
                overrides = ()
        return Glossary(
            seed_mappings=SEED_MAPPINGS,
            keep_as_is=SEED_KEEP_AS_IS,
            user_overrides=tuple(overrides),
        )

    @staticmethod
    def signature_of(glossary: Glossary) -> int:
        """Stable CONTENT identity of the user's PROMPT-ENFORCED override terms (0 = none), from an
        already-resolved ``Glossary`` (pure — no I/O). This is the cache identity for BOTH tasks:
        the derived artifact varies only with prompt-enforced terms (they ride into the prompt),
        while post-substitution (weak) terms are applied as a read-time overlay on a SHARED base,
        so a weak-only edit must NOT fork the cache (NFR-C1).

        It is a content HASH, not a counter: a filtered ``MAX(glossary_ver) WHERE prompt_enforced``
        is non-monotonic — demoting the max prompt-enforced term to post-substitution leaves the
        value unchanged, so a stale artifact would be served (BR-S1 invalidation miss). The hash
        changes whenever the prompt-enforced set is added to / edited / demoted, and is unchanged
        by post-substitution-only edits."""
        enforced = sorted(
            (m.term_from, m.term_to) for m in glossary.user_overrides if m.prompt_enforced
        )
        if not enforced:
            return 0
        digest = hashlib.sha256(repr(enforced).encode("utf-8")).hexdigest()
        # Positive content id; 0 is reserved above for "no prompt-enforced terms" (shared baseline).
        return int(digest[:12], 16)

    def prompt_glossary_signature(self, user_id: str | None) -> int:
        """Convenience: resolve the user's glossary and return its prompt-enforced content
        signature (see [[signature_of]]). Degrades to baseline (0) on a repo fault via
        [[resolve]]."""
        return self.signature_of(self.resolve(user_id))

    def list_user_terms(self, user_id: str) -> Sequence[TermMapping]:
        """Return the user's personal term overrides (owner-scoped, SEC-8). Empty when no
        repository is configured — used to pre-fill the badge editor (read-only)."""
        if self._repo is None:
            return ()
        return tuple(self._repo.get_user_glossary(user_id))

    def upsert_term(
        self, user_id: str, term_from: str, term_to: str, *, prompt_enforced: bool = False
    ) -> int:
        """Persist a personal term override (owner-scoped, SEC-8); return the bumped
        ``glossary_ver``. ``prompt_enforced=False`` → simple-noun post-substitution (translation
        only); ``True`` → the term rides into the prompt (강한). A personal strong term may override
        ANY term — including a shared seed mapping (e.g. attention) — for that user only; the
        override takes precedence over the seed in the prompt (see ``_glossary_block``). Raises
        ``RuntimeError`` when no repository is configured."""
        if self._repo is None:
            raise RuntimeError("glossary repository is not configured")
        return self._repo.upsert_term(
            user_id, term_from, term_to, prompt_enforced=prompt_enforced
        )

    @staticmethod
    def post_substitute(text: str, glossary: Glossary) -> str:
        """Deterministic post-substitution for user-preference simple nouns (no LLM re-call).

        Only ``prompt_enforced=False`` overrides are applied here (simple noun swaps);
        whole-word, longest-first to avoid partial overlaps. Idempotent (PBT-S3).
        """
        post = [m for m in glossary.user_overrides if not m.prompt_enforced]
        for m in sorted(post, key=lambda x: len(x.term_from), reverse=True):
            # Leading boundary only: Korean attaches particles directly to the noun
            # ("어텐션을/어텐션이"), so a trailing ``(?!\w)`` would block the swap. Matching at a
            # left boundary replaces just the noun and leaves the particle intact (particle-safe).
            # The replacement is a function (not a string) so a user-supplied ``term_to`` is
            # inserted literally — backslash sequences (e.g. ``\g<0>``) are NOT interpreted as
            # regex backreferences (input-injection safe now that term_to is user-writable).
            text = re.sub(
                rf"(?<!\w){re.escape(m.term_from)}", lambda _match, repl=m.term_to: repl, text
            )
        return text
