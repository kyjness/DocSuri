from __future__ import annotations

from docsuri_ingestion.docmodel.tei import tei_to_text
from docsuri_ingestion.domain.enums import FailureReason
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError
from docsuri_ingestion.ports import RawContentStorePort

# GROBID writes this when its own parse throws. The text is the only thing that separates
# "this PDF broke the parser" from "the server is unwell" — both are 500.
_DOCUMENT_CRASH_MARKER = "An exception occurred while running Grobid"
_TEMPORARY_4XX = {408, 409, 423, 425, 429}

# Tier name under which TEI lives in the shared raw store, beside "pdf" / "ar5iv". Same store,
# same key shape ({prefix}/{paperId}/v{version}/{tier}) — TEI is another representation of the
# same source bytes, so it needs no cache of its own.
_TEI_TIER = "tei"


class GrobidHttpClient:
    """Internal GROBID client. The PDF bytes are posted and discarded in-process.

    ``extract_tei`` returns the raw TEI for the structured doc-model parser; ``extract_text``
    is the flattened-text projection (legacy/withdrawal-scan use). Both share one POST. The
    request asks GROBID for ``teiCoordinates`` on figures/formulas so the asset pipeline can
    page-crop them by bbox (FR-17); coordinates are additive — absent ones simply mean no crop.

    ``head`` is asked for as well, and not for cropping: GROBID files every ``<figure>`` after
    every ``<div>``, so TEI order says nothing about where a float belonged, and section-title
    coordinates are what lets the parser put one back. ``p`` would be finer but 0.8.0 does not
    coordinate it (asked for, none come back), so a section is as close as this path gets.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 30.0,
        coordinate_elements: tuple[str, ...] = ("figure", "formula", "head"),
        raw_store: RawContentStorePort | None = None,
        cache_mode: str = "off",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._coordinate_elements = coordinate_elements
        # Two-pass TEI cache — see IngestionSettings.grobid_cache_mode for why it exists.
        self._raw_store = raw_store
        self._cache_mode = cache_mode

    def extract_text(self, pdf: bytes) -> str:
        """Flattened reading-order text (TEI ``itertext``). Legacy/withdrawal-scan use."""
        return tei_to_text(self.extract_tei(pdf))

    def extract_tei(
        self, pdf: bytes, *, paper_id: str | None = None, version: int | None = None
    ) -> str:
        """Raw TEI XML from ``processFulltextDocument`` (structured doc-model source).

        ``paper_id``/``version`` are the cache key. Without them the cache is skipped entirely and
        this is the plain HTTP call it always was — a caller that cannot name the paper cannot
        take part in the two-pass split, and silently sharing one unkeyed entry would be worse.
        """
        cached = self._cached_tei(paper_id, version)
        if cached is not None:
            return cached
        if self._cache_mode == "only" and self._raw_store is not None:
            # A miss in `only` mode means pass 1 did not cover this paper. Loud, not silent:
            # returning "" here would hand the builder an empty TEI, which reads downstream as
            # "this paper has no structured form" — indistinguishable from a genuinely
            # unparseable PDF, and it would be recorded that way permanently.
            raise RetriableIngestionError(
                "TEI not in cache and GROBID calls are disabled (grobid_cache_mode=only)",
                reason=FailureReason.DEPENDENCY_UNAVAILABLE,
                stage="grobid",
            )
        tei = self._post_tei(pdf)
        self._store_tei(tei, paper_id, version)
        return tei

    def _cached_tei(self, paper_id: str | None, version: int | None) -> str | None:
        if self._cache_mode == "off" or self._raw_store is None:
            return None
        if paper_id is None or version is None:
            return None
        cached = self._raw_store.get_raw(paper_id, version, _TEI_TIER)
        return cached.decode("utf-8") if cached else None

    def _store_tei(self, tei: str, paper_id: str | None, version: int | None) -> None:
        if self._cache_mode != "prefer" or self._raw_store is None:
            return
        if paper_id is None or version is None or not tei:
            return
        self._raw_store.put_raw(
            paper_id,
            version,
            _TEI_TIER,
            tei.encode("utf-8"),
            content_type="application/tei+xml; charset=utf-8",
        )

    def _post_tei(self, pdf: bytes) -> str:
        import httpx

        # GROBID reads ``teiCoordinates`` as a repeated form field naming the elements whose
        # page/bbox coordinates to emit (the ``coords`` attribute), enabling bbox page-crops.
        data = {"teiCoordinates": list(self._coordinate_elements)}
        try:
            response = httpx.post(
                f"{self._base_url}/api/processFulltextDocument",
                files={"input": ("paper.pdf", pdf, "application/pdf")},
                data=data,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise RetriableIngestionError(
                "GROBID timed out", reason=FailureReason.TIMEOUT, stage="grobid"
            ) from exc
        except httpx.HTTPError as exc:
            raise RetriableIngestionError(
                "GROBID request failed",
                reason=FailureReason.DEPENDENCY_UNAVAILABLE,
                stage="grobid",
            ) from exc
        if response.status_code >= 500:
            # A 500 CARRYING GROBID'S OWN EXCEPTION MARKER IS ABOUT THE DOCUMENT, NOT THE SERVER.
            # GROBID answers a PDF it cannot handle with 500 and this body; a server that is
            # actually unwell does not get far enough to write it (the connection errors above
            # cover that). Treating it as an availability failure is what let one paper take
            # others down: it is retried five times, the breaker reads five consecutive failures
            # as "GROBID is down", and every paper queued behind it fails without reaching the
            # dependency at all. Measured 2026-08-23 on the last three of the ⑧-2 list —
            # 1911.01941 raises IndexOutOfBoundsException inside GROBID on every attempt, and the
            # other two parsed fine the moment they were sent on their own.
            if _DOCUMENT_CRASH_MARKER in response.text:
                raise PermanentIngestionError(
                    "GROBID crashed on this PDF",
                    reason=FailureReason.PARSE_FAILURE,
                    stage="grobid",
                )
            raise RetriableIngestionError(
                "GROBID server error",
                reason=FailureReason.DEPENDENCY_UNAVAILABLE,
                stage="grobid",
            )
        if response.status_code in _TEMPORARY_4XX:
            reason = (
                FailureReason.RATE_LIMITED
                if response.status_code == 429
                else FailureReason.DEPENDENCY_UNAVAILABLE
            )
            raise RetriableIngestionError(
                "GROBID temporary rejection",
                reason=reason,
                stage="grobid",
            )
        if response.status_code >= 400:
            raise PermanentIngestionError(
                "GROBID rejected PDF",
                reason=FailureReason.PARSE_FAILURE,
                stage="grobid",
            )
        # TEI from an internal sidecar; the entity-expansion + 32 MB size cap lives in the
        # downstream ``safe_fromstring`` parse (xmlsafe), and the input PDF is itself fetch-capped.
        return response.text
