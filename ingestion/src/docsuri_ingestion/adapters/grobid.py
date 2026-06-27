from __future__ import annotations

import xml.etree.ElementTree as ET

from docsuri_ingestion.domain.enums import FailureReason
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError

_TEMPORARY_4XX = {408, 409, 423, 425, 429}


class GrobidHttpClient:
    """Internal GROBID client. The PDF bytes are posted and discarded in-process."""

    def __init__(self, *, base_url: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def extract_text(self, pdf: bytes) -> str:
        import httpx

        try:
            response = httpx.post(
                f"{self._base_url}/api/processFulltextDocument",
                files={"input": ("paper.pdf", pdf, "application/pdf")},
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
        return _tei_to_text(response.text)


def _tei_to_text(tei: str) -> str:
    try:
        root = ET.fromstring(tei)
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
