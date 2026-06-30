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

# P1 seed: model/abbreviation names kept in English (keep-as-is) — biggest cheap win (§9.1).
SEED_KEEP_AS_IS: tuple[str, ...] = (
    "Transformer", "BERT", "GPT", "LoRA", "RAG", "LLM", "CNN", "RNN", "LSTM", "ViT",
    "ResNet", "ImageNet", "SOTA", "MLP", "GAN", "VAE", "ReLU", "Adam", "SGD",
)

# P1 seed: core domain mappings enforced in the prompt for consistency.
SEED_MAPPINGS: tuple[TermMapping, ...] = (
    TermMapping("attention", "어텐션", prompt_enforced=True),
    TermMapping("embedding", "임베딩", prompt_enforced=True),
    TermMapping("fine-tuning", "파인튜닝", prompt_enforced=True),
    TermMapping("latent space", "잠재 공간", prompt_enforced=True),
)


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

    def glossary_version(self, user_id: str | None) -> int:
        """The user's current ``glossary_ver`` (0 = shared baseline, no personal terms). Folds
        into the cache key so a personal-term edit invalidates the user's cached results. A repo
        fault degrades to the shared baseline (0) rather than failing the request — versioning is
        advisory, off the response-critical path."""
        if self._repo is None or user_id is None:
            return 0
        try:
            return self._repo.get_glossary_version(user_id)
        except Exception:  # noqa: BLE001 — versioning failure → shared baseline (degrade, not fail)
            return 0

    def prompt_glossary_signature(self, user_id: str | None) -> int:
        """Stable CONTENT identity of the user's prompt-enforced terms (0 = none), for the summary
        cache key. Summary output varies ONLY with prompt-enforced terms (they ride into the
        prompt; post-substitution terms touch translation only), so the summary cache must key on
        exactly that subset — keying on the full ``glossary_ver`` would needlessly fork the cache
        per user on a translate-only term edit (NFR-C1).

        It is a content HASH, not a counter: a filtered ``MAX(glossary_ver) WHERE prompt_enforced``
        is non-monotonic — demoting the max prompt-enforced term to post-substitution leaves the
        value unchanged, so a stale summary would be served (BR-S1 invalidation miss). The hash
        changes whenever the prompt-enforced set is added to / edited / demoted, and is unchanged
        by post-substitution-only edits. Degrades to baseline (0) on a repo fault, like
        [[glossary_version]]."""
        if self._repo is None or user_id is None:
            return 0
        try:
            terms = self._repo.get_user_glossary(user_id)
        except Exception:  # noqa: BLE001 — versioning failure → shared baseline (degrade, not fail)
            return 0
        enforced = sorted((m.term_from, m.term_to) for m in terms if m.prompt_enforced)
        if not enforced:
            return 0
        digest = hashlib.sha256(repr(enforced).encode("utf-8")).hexdigest()
        # Positive content id; 0 is reserved above for "no prompt-enforced terms" (shared baseline).
        return int(digest[:12], 16)

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
        ``glossary_ver``. Phase 1 default ``prompt_enforced=False`` → simple-noun
        post-substitution (translation only). Raises when no repository is configured."""
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
