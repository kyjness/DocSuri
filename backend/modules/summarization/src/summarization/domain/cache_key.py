"""Cache-key construction — immutable identity (§11 / BR-S1 / INV-5).

Identity = (paper, version, task, lang, persona, glossaryVer, [ownerId], [seedVer], modelVer,
promptVer). ``glossaryVer`` here is the PROMPT-ENFORCED content signature (glossary.signature_of):
the artifact varies only with terms that ride into the prompt, so adding/editing a prompt-enforced
term changes the key (miss → regenerate) while a post-substitution (weak) edit does NOT — weak
terms are a read-time overlay on the shared base (NFR-C1). A positive signature is owner-scoped
(distinct per-user term sets must not collide); signature 0 (no prompt-enforced terms) is the
owner-agnostic shared baseline. ``seedVer`` appends only when the shared seed diverges from its
shipped baseline, so a seed edit self-invalidates. Same key ⇒ same artifact, forever.
"""

from __future__ import annotations

from docsuri_shared.docmodel_contract import DOCMODEL_PARSER_VERSION

from .models import Persona, Scope, SummaryCacheKey, SummaryRequest, Task

# Prompt template version — bump to invalidate all derived objects (key changes).
PROMPT_VER = "p1"
# Translate base FORMAT version — appended to the translate key only, so it invalidates translate
# artifacts WITHOUT needlessly regenerating summaries. Bump when the cached translate base changes
# shape. ``m1`` = masked standard-term tokens rendered at serve (BR-S4): older token-free bases
# render as a no-op, so this rotation past them makes new deterministic bases regenerate cleanly.
TRANSLATE_FORMAT_VER = "m1"


def _docmodel_generation(parser_version: str) -> str:
    """Compact, path-safe segment for a doc-model parser version: the generation integer after
    ``@`` (``docmodel-parser@4`` → ``"4"``). Falls back to the raw string if it has no ``@``."""
    _, sep, gen = parser_version.rpartition("@")
    return gen if sep else parser_version


def build_cache_key(
    request: SummaryRequest,
    *,
    glossary_ver: int,
    model_ver: str,
    user_id: str | None,
    seed_ver: str = "",
    docmodel_parser: str = DOCMODEL_PARSER_VERSION,
) -> SummaryCacheKey:
    # Identity dimensions (§11): summary varies by persona (2 variants), scope fixed to
    # full; translate varies by scope (abstract|full), persona-agnostic (single).
    is_summary = request.task == Task.SUMMARY
    scope = Scope.FULL if is_summary else request.scope
    # Translate is persona-agnostic (BR-S10): pin persona to a constant so an incoming persona
    # (the FE only toggles it for summary) can't mint redundant per-persona translate entries
    # for identical output — wasted LLM spend (NFR-C1). Mirrors the scope special-case above.
    persona = request.persona if is_summary else Persona.EXPERT
    # Translate keys carry the base-format version so a format change invalidates only translate
    # artifacts (summaries keep the bare PROMPT_VER, untouched).
    prompt_ver = PROMPT_VER if is_summary else f"{PROMPT_VER}-{TRANSLATE_FORMAT_VER}"
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
        prompt_ver=prompt_ver,
        seed_ver=seed_ver,
        docmodel_ver=_docmodel_generation(docmodel_parser),
    )
