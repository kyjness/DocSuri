from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from docsuri_ingestion.corpus_sources import SourcePaperRecord
from docsuri_ingestion.domain.enums import FailureReason, SourceName
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError

_FIELDS_OF_STUDY = "Computer Science"
_QUERY_TERMS = {
    "cs.AI": "artificial intelligence",
    "cs.CL": "natural language processing",
    "cs.CV": "computer vision",
    "cs.LG": "machine learning",
    "stat.ML": "machine learning",
}


class SemanticScholarCorpusSource:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.semanticscholar.org/graph/v1",
        timeout_seconds: float = 30.0,
        transport: object | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def fetch_incremental(
        self,
        since: datetime,
        categories: Sequence[str],
        until: datetime | None = None,
    ) -> list[SourcePaperRecord]:
        records: list[SourcePaperRecord] = []
        token: str | None = None
        while True:
            params = {
                "query": _query(categories),
                "fields": ",".join(
                    (
                        "paperId",
                        "title",
                        "abstract",
                        "authors",
                        "year",
                        "publicationDate",
                        "externalIds",
                        "openAccessPdf",
                        "isOpenAccess",
                        "updated",
                    )
                ),
                "fieldsOfStudy": _FIELDS_OF_STUDY,
                "limit": "100",
            }
            if token:
                params["token"] = token
            payload = _get_json(
                f"{self._base_url}/paper/search/bulk",
                params=params,
                headers={"x-api-key": self._api_key} if self._api_key else None,
                timeout_seconds=self._timeout_seconds,
                transport=self._transport,
                stage="semantic_scholar",
            )
            for item in payload.get("data", []) or []:
                record = _semantic_record(item)
                if record and _in_window(record, since, until):
                    records.append(record)
            token = payload.get("token")
            if not token:
                return records

    def fetch_pdf(self, record: SourcePaperRecord) -> bytes:
        if not record.pdf_url:
            raise PermanentIngestionError(
                "Semantic Scholar record has no PDF URL",
                reason=FailureReason.FETCH_FAILURE,
                stage="source",
            )
        return _get_bytes(
            record.pdf_url,
            timeout_seconds=self._timeout_seconds,
            transport=self._transport,
            stage="semantic_scholar_pdf",
        )


class OpenAlexCorpusSource:
    def __init__(
        self,
        *,
        base_url: str = "https://api.openalex.org",
        timeout_seconds: float = 30.0,
        transport: object | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def fetch_incremental(
        self,
        since: datetime,
        categories: Sequence[str],
        until: datetime | None = None,
    ) -> list[SourcePaperRecord]:
        records: list[SourcePaperRecord] = []
        cursor = "*"
        while cursor:
            filters = [
                f"from_updated_date:{since.date().isoformat()}",
                "open_access.is_oa:true",
                "type:article",
            ]
            if until is not None:
                filters.append(f"to_updated_date:{until.date().isoformat()}")
            payload = _get_json(
                f"{self._base_url}/works",
                params={
                    "filter": ",".join(filters),
                    "search": _query(categories),
                    "per-page": "100",
                    "cursor": cursor,
                    "select": ",".join(
                        (
                            "id",
                            "ids",
                            "doi",
                            "display_name",
                            "abstract_inverted_index",
                            "authorships",
                            "publication_year",
                            "publication_date",
                            "updated_date",
                            "primary_location",
                            "locations",
                        )
                    ),
                },
                headers=None,
                timeout_seconds=self._timeout_seconds,
                transport=self._transport,
                stage="openalex",
            )
            for item in payload.get("results", []) or []:
                record = _openalex_record(item)
                if record and _in_window(record, since, until):
                    records.append(record)
            cursor = (payload.get("meta") or {}).get("next_cursor")
        return records

    def fetch_pdf(self, record: SourcePaperRecord) -> bytes:
        if not record.pdf_url:
            raise PermanentIngestionError(
                "OpenAlex record has no PDF URL",
                reason=FailureReason.FETCH_FAILURE,
                stage="source",
            )
        return _get_bytes(
            record.pdf_url,
            timeout_seconds=self._timeout_seconds,
            transport=self._transport,
            stage="openalex_pdf",
        )


def _semantic_record(item: dict[str, Any]) -> SourcePaperRecord | None:
    pdf = item.get("openAccessPdf") or {}
    license_url = _license_url(pdf.get("license"))
    pdf_url = _https_url(pdf.get("url"))
    if not pdf_url or not license_url or not item.get("isOpenAccess"):
        return None
    external_ids = item.get("externalIds") or {}
    return SourcePaperRecord(
        source_name=SourceName.SEMANTIC_SCHOLAR,
        source_id=str(item.get("paperId") or ""),
        title=str(item.get("title") or ""),
        abstract=str(item.get("abstract") or ""),
        authors=tuple(
            str(author.get("name"))
            for author in item.get("authors", []) or []
            if author.get("name")
        ),
        published_at=_parse_date(item.get("publicationDate")),
        updated_at=_parse_date(item.get("updated")),
        year=_int_or_none(item.get("year")),
        pdf_url=pdf_url,
        license_url=license_url,
        doi=external_ids.get("DOI"),
        arxiv_id=external_ids.get("ArXiv"),
    )


def _openalex_record(item: dict[str, Any]) -> SourcePaperRecord | None:
    location = item.get("primary_location") or {}
    pdf_url = _https_url(location.get("pdf_url")) or _first_pdf_url(item.get("locations") or [])
    license_url = _license_url(location.get("license"))
    if not pdf_url or not license_url:
        return None
    ids = item.get("ids") or {}
    return SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id=str(item.get("id") or ""),
        title=str(item.get("display_name") or ""),
        abstract=_abstract_text(item.get("abstract_inverted_index") or {}),
        authors=tuple(_openalex_authors(item)),
        published_at=_parse_date(item.get("publication_date")),
        updated_at=_parse_date(item.get("updated_date")),
        year=_int_or_none(item.get("publication_year")),
        pdf_url=pdf_url,
        html_url=_https_url(location.get("landing_page_url")),
        license_url=license_url,
        doi=item.get("doi") or ids.get("doi"),
        arxiv_id=_arxiv_id(ids.get("arxiv")),
    )


def _openalex_authors(item: dict[str, Any]) -> list[str]:
    authors = []
    for authorship in item.get("authorships", []) or []:
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(str(name))
    return authors


def _get_json(
    url: str,
    *,
    params: dict[str, str],
    headers: dict[str, str] | None,
    timeout_seconds: float,
    transport: object | None,
    stage: str,
) -> dict[str, Any]:
    return _response_json(
        _request(
            url,
            params=params,
            headers=headers,
            timeout_seconds=timeout_seconds,
            transport=transport,
            stage=stage,
        ),
        stage,
    )


def _get_bytes(
    url: str, *, timeout_seconds: float, transport: object | None, stage: str
) -> bytes:
    return _request(
        url,
        params=None,
        headers=None,
        timeout_seconds=timeout_seconds,
        transport=transport,
        stage=stage,
    ).content


def _request(
    url: str,
    *,
    params: dict[str, str] | None,
    headers: dict[str, str] | None,
    timeout_seconds: float,
    transport: object | None,
    stage: str,
):
    import httpx

    try:
        with httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
        ) as client:
            response = client.get(url, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise RetriableIngestionError(
            "external corpus request timed out", reason=FailureReason.TIMEOUT, stage=stage
        ) from exc
    except httpx.HTTPError as exc:
        raise RetriableIngestionError(
            "external corpus request failed",
            reason=FailureReason.FETCH_FAILURE,
            stage=stage,
        ) from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise RetriableIngestionError(
            f"external corpus source returned {response.status_code}",
            reason=FailureReason.RATE_LIMITED
            if response.status_code == 429
            else FailureReason.FETCH_FAILURE,
            stage=stage,
        )
    if response.status_code >= 400:
        raise PermanentIngestionError(
            f"external corpus source returned {response.status_code}",
            reason=FailureReason.FETCH_FAILURE,
            stage=stage,
        )
    return response


def _response_json(response, stage: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise PermanentIngestionError(
            "external corpus source returned invalid JSON",
            reason=FailureReason.PARSE_FAILURE,
            stage=stage,
        ) from exc
    if not isinstance(payload, dict):
        raise PermanentIngestionError(
            "external corpus source returned non-object JSON",
            reason=FailureReason.PARSE_FAILURE,
            stage=stage,
        )
    return payload


def _query(categories: Sequence[str]) -> str:
    terms = sorted({_QUERY_TERMS.get(category, category) for category in categories})
    return " ".join(terms) or "machine learning"


def _in_window(
    record: SourcePaperRecord,
    since: datetime,
    until: datetime | None,
) -> bool:
    timestamp = record.updated_at or record.published_at or since
    return timestamp > since and (until is None or timestamp <= until)


def _first_pdf_url(locations: list[dict[str, Any]]) -> str | None:
    for location in locations:
        pdf_url = _https_url(location.get("pdf_url"))
        if pdf_url:
            return pdf_url
    return None


def _https_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith(("https://", "http://")):
        return value
    return None


def _license_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if "creativecommons.org" in normalized or "arxiv.org/licenses/nonexclusive" in normalized:
        return value.strip()
    cc = normalized.replace("_", "-").replace(" ", "-")
    if cc in {"cc-by", "ccby"}:
        return "https://creativecommons.org/licenses/by/4.0/"
    if cc in {"cc-by-sa", "ccbysa"}:
        return "https://creativecommons.org/licenses/by-sa/4.0/"
    if cc in {"cc0", "cc-zero"}:
        return "https://creativecommons.org/publicdomain/zero/1.0/"
    return None


def _parse_date(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _abstract_text(inverted: dict[str, list[int]]) -> str:
    words: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for position in positions:
            words.append((position, word))
    return " ".join(word for _, word in sorted(words))


def _arxiv_id(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.rstrip("/").rsplit("/", 1)[-1]
