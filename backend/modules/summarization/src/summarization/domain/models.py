"""U7 domain entities (domain-entities.md).

Internal pipeline shapes are frozen dataclasses; the external response union
(``SummaryResponse``) exposes only SEC-9-safe fields via ``to_dict`` (INV-3). The
``shared/dtos/summarization`` contract is PROVISIONAL — these module-local shapes stand
in until it is promoted (U4 library precedent).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from docsuri_shared.dtos import DocModel


class Task(StrEnum):
    SUMMARY = "summary"
    TRANSLATE = "translate"


class Persona(StrEnum):
    EXPERT = "expert"
    BEGINNER = "beginner"


class Scope(StrEnum):
    """Translate source scope. summary is always full text (scope ignored)."""

    ABSTRACT = "abstract"
    FULL = "full"


class TargetLang(StrEnum):
    KO = "ko"


class SourceKind(StrEnum):
    FULL_TEXT = "full_text"
    ABSTRACT = "abstract"


class AnchorTarget(StrEnum):
    SECTION = "section"
    TABLE = "table"
    FIGURE = "figure"


# --- Request / context -------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AuthSession:
    """Authenticated principal injected by the U6 gateway (SEC-8). U7 trusts it."""

    user_id: str


@dataclass(frozen=True, slots=True)
class RequestContext:
    auth_session: AuthSession
    request_id: str


@dataclass(frozen=True, slots=True)
class SummaryRequest:
    """Result-card on-demand action (FR-12/13). ``persona`` applies to summary only.

    View presets were dropped (Q9 폐기): there is no ``view`` request field and no view-derived
    generation variant — persona (expert/beginner) is the only generation axis. Any display
    slicing (full / tl;dr / per-section) is a pure U5 client-render concern over the same §3
    JSON, never a U7 input or cache-identity component.
    """

    paper_id: str
    version: int
    task: Task
    target_lang: TargetLang = TargetLang.KO
    persona: Persona = Persona.EXPERT
    scope: Scope = Scope.ABSTRACT  # translate only (abstract|full); summary = full text
    abstract: str | None = None  # carried for translate / full-text fallback (Q1)


# --- Cache key (immutable, §11 / BR-S1) --------------------------------------
@dataclass(frozen=True, slots=True)
class SummaryCacheKey:
    paper_id: str
    version: int
    task: Task
    target_lang: TargetLang
    scope: Scope
    persona: Persona
    glossary_ver: int
    model_ver: str
    prompt_ver: str
    # Owner of a personalized artifact (set only when glossary_ver > 0). glossary_ver is a
    # per-user counter, not a content identity, so two different users can both be at ver=1
    # with different terms — without owner scoping their keys would collide and one would be
    # served the other's personalized translation. None for the shared baseline (ver == 0).
    owner_id: str | None = None

    def object_path(self) -> str:
        """S3 object path (infrastructure-design §2.1). Immutable → permanent (INV-5).

        ``glossaryVer`` is part of the path so a personal-term change (glossaryVer++) yields a
        new key → cache miss → re-translation (BR-S1: invalidation by key change, no manual
        flush). Personalized artifacts (glossary_ver > 0) additionally carry ``owner_id`` so
        per-user counters that share an integer don't collide across users; the baseline
        (glossary_ver == 0, no personal terms) stays owner-agnostic and shared.
        """
        owner = f"_u{self.owner_id}" if self.owner_id else ""
        return (
            f"summaries/{self.paper_id}/v{self.version}/"
            f"{self.task}_{self.target_lang}_{self.scope}_{self.persona}"
            f"_g{self.glossary_ver}{owner}_{self.model_ver}_{self.prompt_ver}.json"
        )

    def redis_key(self) -> str:
        """Hot-cache key in the ``sum:`` keyspace (infrastructure-design §2.2)."""
        return "sum:" + self.object_path()


# --- Source / refinement (§4 / BR-S3) ----------------------------------------
@dataclass(frozen=True, slots=True)
class SourceText:
    kind: SourceKind
    raw: str = ""  # plain text (abstract, or legacy .txt full text); empty when doc_model is set
    # (D2) structured doc-model full-text input — preferred over plain `.txt` when available.
    # The refiner takes sections/tables/formulas/captions from it directly (no regex guessing).
    doc_model: DocModel | None = None
    fallback_reason: str | None = None  # set when summary fell back to abstract (Q1/NFR-R2)


@dataclass(frozen=True, slots=True)
class DocModelLookup:
    """Result of a doc-model read (BR-30/D6): the cached artifact on a hit, or ``building`` when
    a lazy build was (re)triggered on a miss so the client polls again. ``building`` stays False
    when no build queue is wired — the router then surfaces ``source_unavailable`` (prior
    behavior preserved)."""

    doc: DocModel | None = None
    building: bool = False
    retry_after_ms: int | None = None


@dataclass(frozen=True, slots=True)
class Section:
    label: str  # "" when only a span could be derived (Q6 span-only degrade)
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Table:
    """A doc-model table projected for the LLM input + grounding (D8 — numbers visible).

    ``rows`` are the structured cell texts (row-major); ``label`` is the paper's anchor label
    ("Table 3"); ``anchor`` is the doc-model block id. Carried on ``RefinedSource`` so the
    grounding gate can resolve table anchors and numeric matches against real data."""

    label: str
    rows: tuple[tuple[str, ...], ...]
    caption: str = ""
    anchor: str = ""


@dataclass(frozen=True, slots=True)
class RefinedSource:
    body: str
    sections: tuple[Section, ...] = ()
    tables: tuple[Table, ...] = ()  # doc-model structured tables — data visible to LLM (D8)
    captions: tuple[str, ...] = ()  # Table/Figure captions — preserved (Q2)
    formulas: tuple[str, ...] = ()  # LaTeX — preserved, never translated
    preserved: tuple[str, ...] = ()  # Appendix, Supplementary Results, etc. (Step 36)
    token_count: int = 0


# --- Glossary (§9.1 / BR-S4) -------------------------------------------------
@dataclass(frozen=True, slots=True)
class TermMapping:
    term_from: str
    term_to: str
    prompt_enforced: bool = True  # False → deterministic post-substitution (simple noun)


@dataclass(frozen=True, slots=True)
class Glossary:
    seed_mappings: tuple[TermMapping, ...] = ()
    keep_as_is: tuple[str, ...] = ()
    user_overrides: tuple[TermMapping, ...] = ()


# --- Generation output (§3) --------------------------------------------------
@dataclass(frozen=True, slots=True)
class Anchor:
    field_name: str
    target: AnchorTarget
    span: str
    label: str = ""  # "" when section derivation failed → span-only (Q6)


@dataclass(frozen=True, slots=True)
class SummaryDraft:
    tldr: str
    contributions: tuple[str, ...]
    method: str
    results: str
    limitations: str
    reproducibility: dict[str, str]  # {"code": ..., "data": ...}
    anchors: tuple[Anchor, ...]
    truncated: bool = False  # Set when LLM output was truncated (Step 33)


@dataclass(frozen=True, slots=True)
class TranslationDraft:
    """Structured translation output (BR-S18 / FR-13, PR-2): a 'translated doc-model' —
    the source doc-model with text fields (section titles, paragraphs, list items,
    table/figure captions) in Korean and structural/verbatim fields (block & section ids,
    formula LaTeX, table numeric cells, figure assetRefs) copied unchanged. The client
    renders it with the SAME rich viewer as the original body."""

    doc_model: DocModel
    kept_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TranslationSegment:
    """One translatable text unit of a doc-model, keyed by a deterministic ``id`` derived
    from the source block/section id (BR-S18). The LLM returns ``id → 번역텍스트`` so the
    translator re-injects text into the source structure without the model dropping or
    reordering blocks."""

    id: str
    text: str


@dataclass(frozen=True, slots=True)
class TranslationSegmentsResult:
    """Gateway translation result: ``translations`` maps segment id → Korean text;
    ``kept_terms`` are terms left untranslated (BR-S4)."""

    translations: dict[str, str]
    kept_terms: tuple[str, ...] = ()


# --- Grounding (Q4 — U7-owned deterministic gate) ----------------------------
@dataclass(frozen=True, slots=True)
class GroundingInput:
    draft: SummaryDraft
    refined: RefinedSource


@dataclass(frozen=True, slots=True)
class Violation:
    kind: str  # anchor_missing | numeric_mismatch | schema_incomplete | truncated | empty
    field_name: str


@dataclass(frozen=True, slots=True)
class AnchorVerdict:
    ok: bool
    violations: tuple[Violation, ...] = ()
    outcome: str = "pass"  # pass | abstain
    # Anchors that passed the existence check (option D): the orchestrator swaps the draft's
    # anchors for these before assembling, so unverifiable anchors (table/paraphrase/math) are
    # dropped rather than abstaining the whole summary.
    kept_anchors: tuple[Anchor, ...] = ()


# --- Terminal response union (BR-S9 / Q5) ------------------------------------
@dataclass(frozen=True, slots=True)
class SummaryResultDTO:
    task: Task
    summary: SummaryDraft | None = None
    translation: TranslationDraft | None = None
    meta: dict[str, str] = field(default_factory=dict)
    cached: bool = False

    def to_dict(self) -> dict:
        """SEC-9 whitelist — only user-facing fields (no tokens/cost/cache-key/model id)."""
        out: dict = {
            "status": "ok",
            "task": str(self.task),
            "meta": self.meta,
            "cached": self.cached,
        }
        if self.summary is not None:
            s = self.summary
            out["summary"] = {
                "tldr": s.tldr,
                "contributions": list(s.contributions),
                "method": s.method,
                "results": s.results,
                "limitations": s.limitations,
                "reproducibility": s.reproducibility,
                "anchors": [
                    {
                        "field": a.field_name,
                        "target": str(a.target),
                        "span": a.span,
                        "label": a.label,
                    }
                    for a in s.anchors
                ],
            }
        if self.translation is not None:
            # Mirror the doc-model read path (router): emit the translated doc-model with
            # ``exclude_none`` so absent optional fields stay absent (schema parity).
            out["translation"] = {
                "docModel": self.translation.doc_model.model_dump(
                    mode="json", exclude_none=True
                ),
                "keptTerms": list(self.translation.kept_terms),
            }
        return out


@dataclass(frozen=True, slots=True)
class AbstainDTO:
    reason: str

    def to_dict(self) -> dict:
        return {"status": "abstain", "reason": self.reason}


@dataclass(frozen=True, slots=True)
class PendingDTO:
    """A long-input summary (MAP_REDUCE band) is being produced by a background job (BR-S6/BR-S8);
    the client re-requests after ``retry_after_ms`` and gets the result on a cache hit."""

    retry_after_ms: int | None = None

    def to_dict(self) -> dict:
        body: dict = {"status": "pending"}
        if self.retry_after_ms is not None:
            body["retryAfterMs"] = self.retry_after_ms
        return body


@dataclass(frozen=True, slots=True)
class CostDegradedDTO:
    message: str = "AI 요약 일시 중단"

    def to_dict(self) -> dict:
        return {"status": "cost_degraded", "message": self.message}


@dataclass(frozen=True, slots=True)
class SourceUnavailableDTO:
    reason: str

    def to_dict(self) -> dict:
        return {"status": "source_unavailable", "reason": self.reason}


SummaryResponse = (
    SummaryResultDTO | PendingDTO | AbstainDTO | CostDegradedDTO | SourceUnavailableDTO
)


# --- FR-17 multimodal asset read DTOs (display-only; produced by U1, read by U7) ----
@dataclass(frozen=True, slots=True)
class StoredAsset:
    """Internal manifest row read from ``paper_asset`` (carries ``object_ref``)."""

    asset_id: str
    type: str  # figure | table
    ordinal: int
    caption: str
    source_mode: str  # structured | page-crop
    object_ref: str  # internal — NOT exposed (SEC-9); presigned before leaving U7
    page_ref: int | None = None
    bbox: list | None = None


@dataclass(frozen=True, slots=True)
class AssetRef:
    """Public asset view-model — a short-lived signed ``url`` only (SEC-9, BR-S15)."""

    asset_id: str
    type: str
    ordinal: int
    caption: str
    source_mode: str
    url: str  # presigned; object_ref/internal meta never exposed
    page_ref: int | None = None
    bbox: list | None = None

    def to_dict(self) -> dict:
        return {
            "assetId": self.asset_id,
            "type": self.type,
            "ordinal": self.ordinal,
            "caption": self.caption,
            "sourceMode": self.source_mode,
            "url": self.url,
            "pageRef": self.page_ref,
            "bbox": self.bbox,
        }
