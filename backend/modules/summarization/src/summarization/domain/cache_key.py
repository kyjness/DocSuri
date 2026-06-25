"""Cache-key construction — immutable identity (§11 / BR-S1 / INV-5).

Identity = (paper, version, task, lang, persona, glossaryVer, [ownerId], modelVer, promptVer).
``glossaryVer`` invalidates a user's own cache on a term edit (per-user counter, bumped on
upsert). But that counter is NOT a content identity — two different users can both sit at
ver=1 with different terms — so personalized artifacts (glossaryVer > 0) also key on
``ownerId`` to keep them from colliding across users. The baseline (glossaryVer == 0, no
personal terms) is owner-agnostic and shared. Same key ⇒ same artifact, forever.
"""

from __future__ import annotations

from .models import Persona, Scope, SummaryCacheKey, SummaryRequest, Task

# Prompt template version — bump to invalidate all derived objects (key changes).
PROMPT_VER = "p1"


def build_cache_key(
    request: SummaryRequest, *, glossary_ver: int, model_ver: str, user_id: str | None
) -> SummaryCacheKey:
    # Identity dimensions (§11): summary varies by persona (2 variants), scope fixed to
    # full; translate varies by scope (abstract|full), persona-agnostic (single).
    is_summary = request.task == Task.SUMMARY
    scope = Scope.FULL if is_summary else request.scope
    # Translate is persona-agnostic (BR-S10): pin persona to a constant so an incoming persona
    # (the FE only toggles it for summary) can't mint redundant per-persona translate entries
    # for identical output — wasted LLM spend (NFR-C1). Mirrors the scope special-case above.
    persona = request.persona if is_summary else Persona.EXPERT
    # Personalized artifacts (the user has terms ⇒ glossary_ver > 0) are owner-scoped so a
    # per-user version integer shared across users does not collapse to one key. The baseline
    # (ver 0) stays owner-agnostic so identical un-personalized results de-dup across users.
    owner_id = user_id if glossary_ver > 0 else None
    return SummaryCacheKey(
        paper_id=request.paper_id,
        version=request.version,
        task=request.task,
        target_lang=request.target_lang,
        scope=scope,
        persona=persona,
        glossary_ver=glossary_ver,
        owner_id=owner_id,
        model_ver=model_ver,
        prompt_ver=PROMPT_VER,
    )
