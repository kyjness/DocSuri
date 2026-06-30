from __future__ import annotations

import xml.etree.ElementTree as ET

from docsuri_ingestion.domain.enums import FailureReason
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError
from docsuri_ingestion.xmlsafe import safe_fromstring

_TEMPORARY_4XX = {408, 409, 423, 425, 429}


class GrobidHttpClient:
    """Internal GROBID client. The PDF bytes are posted and discarded in-process.

    ``extract_tei`` returns the raw TEI for the structured doc-model parser; ``extract_text``
    is the flattened-text projection (legacy/withdrawal-scan use). Both share one POST. The
    request asks GROBID for ``teiCoordinates`` on figures/formulas so the asset pipeline can
    page-crop them by bbox (FR-17); coordinates are additive — absent ones simply mean no crop.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 30.0,
        coordinate_elements: tuple[str, ...] = ("figure", "formula"),
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._coordinate_elements = coordinate_elements

    def extract_text(self, pdf: bytes) -> str:
        """Flattened reading-order text (TEI ``itertext``). Legacy/withdrawal-scan use."""
        return _tei_to_text(self.extract_tei(pdf))

    def extract_tei(self, pdf: bytes) -> str:
        """Raw TEI XML from ``processFulltextDocument`` (structured doc-model source)."""
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


def _tei_to_text(tei: str) -> str:
    try:
        root = safe_fromstring(tei)
    except ET.ParseError as exc:
        raise PermanentIngestionError(
            "GROBID returned invalid TEI",
            reason=FailureReason.PARSE_FAILURE,
            stage="grobid",
        ) from exc
    text = " ".join(part.strip() for part in root.itertext() if part.strip())
    if not text:
        raise PermanentIngestionError(
            "GROBID returned empty TEI",
            reason=FailureReason.PARSE_FAILURE,
            stage="grobid",
        )
    return text
