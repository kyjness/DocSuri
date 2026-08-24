"""출처 포트 — 검색·승격·DocModel 읽기. 도메인은 구현을 모른다.

세 포트가 한 파일에 있는 이유는 **하나의 개념을 나눠 갖기 때문**이다: 논문을
찾고(검색), 본문을 확보하고(승격), 읽는다(DocModel). 실패 표현도 함께 맞춘다 —
승격 실패는 예외가 아니라 결과값이고, 그래야 루프가 초록 범위로 계속한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    "CorpusSearchPort",
    "DocModelReadPort",
    "ExternalPaperSearchPort",
    "PaperCandidate",
    "PaperPromotionPort",
    "PromotionResult",
    "SearchUnavailable",
    "YearBound",
]


class SearchUnavailable(RuntimeError):
    """검색 인덱스·외부 소스 장애 — 해당 도구만 실패하고 루프는 계속한다."""


@dataclass(frozen=True, slots=True)
class PaperCandidate:
    """검색이 돌려주는 후보 1건.

    내부 점수·청크 id는 담지 않는다(INV-EV-5). `abstract`는 외부 후보의 유일한
    대조 텍스트이자 승격 판단 재료다.
    """

    paper_id: str
    record_ref: str
    title: str
    abstract: str = ""


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """`fetch_paper` 결과 — 실패도 **정상 결과값**이다(예외로 루프를 깨지 않는다).

    `outcome`은 `PromotionOutcome` 문자열. `doc_model`은 성공했을 때만 채워진다.
    """

    outcome: str
    doc_model: Any | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class YearBound:
    """발표 연도 제약(양끝 포함, `None`이면 무제한) — §2.5 "2023년 이후만"의 인자 형태.

    프롬프트 당부가 아니라 인자인 이유는 그것이 지켜지는지 **기계로 판정되기 때문**이고,
    후처리가 아니라 **질의로 내려가는** 이유는 상위 k에 해당 연도가 없을 때 후처리가
    "그런 논문이 없다"와 구분되지 않는 0건을 내기 때문이다.
    """

    start: int | None = None
    end: int | None = None

    @property
    def bounded(self) -> bool:
        return self.start is not None or self.end is not None


class CorpusSearchPort(Protocol):
    def search(
        self, query: str, *, phrase: bool = False, years: YearBound | None = None
    ) -> tuple[PaperCandidate, ...]:
        """내부 코퍼스 하이브리드 검색. `phrase=True`면 정확 문구 검색."""
        ...


class ExternalPaperSearchPort(Protocol):
    def search(self, query: str) -> tuple[PaperCandidate, ...]:
        """코퍼스 밖 논문 검색 — 제목·초록만 확보한다. 본문은 승격이 담당한다."""
        ...


class PaperPromotionPort(Protocol):
    def promote(self, paper_id: str) -> PromotionResult:
        """본문 취득 + DocModel 생성을 U1에 **요청**하고 완료를 기다린다.

        DocModel의 단일 writer는 U1이다(INV-EV-7) — 여기서 직접 쓰지 않는다.
        워커 미가동·시간 초과는 실패가 아니라 `timed_out` 결과이며, 호출자는
        초록 범위로 계속한다.
        """
        ...


class DocModelReadPort(Protocol):
    def get_doc_model(self, paper_id: str) -> Any | None:
        """확보된 DocModel 읽기. 없으면 None(개별 실패는 건너뛴다)."""
        ...
