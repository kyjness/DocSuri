"""출처 포트 — 검색·승격·DocModel 읽기. 도메인은 구현을 모른다.

세 포트가 한 파일에 있는 이유는 **하나의 개념을 나눠 갖기 때문**이다: 논문을
찾고(검색), 본문을 확보하고(승격), 읽는다(DocModel). 실패 표현도 함께 맞춘다 —
승격 실패는 예외가 아니라 결과값이고, 그래야 루프가 초록 범위로 계속한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    "ContinuationSeedPort",
    "CorpusSearchPort",
    "DocModelReadPort",
    "LiveLookupResult",
    "LivePaperLookupPort",
    "PaperCandidate",
    "PaperIndexQueuePort",
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


@dataclass(frozen=True, slots=True)
class LiveLookupResult:
    """조회 결과 + **어느 소스가 빠졌는지**.

    저하가 **계약에 있어야 하는** 이유는 소비자가 둘이기 때문이다: 도구가 모델에게 알리고
    (안 알리면 모델은 "이게 전부"라고 믿는다 — novelty 실측), 마감이 확인 범위 줄에
    "실시간 조회 불가"를 싣는다(§7). 둘 다 **필수 출력**이다.

    초안은 포트에 `search() -> tuple[PaperCandidate, ...]`만 두고 저하는 어댑터가 덧붙인
    `lookup()`으로 날랐는데, 그러면 도구가 `getattr`로 그 메서드를 찾아야 하고 **선언된
    프로토콜만 만족하는 구현은 저하를 조용히 버린다** — 화면은 "그런 논문이 없다"를 내고,
    사용자는 "다시 물어보기" 대신 "주제 넓히기"를 한다(정반대 행동이다).
    """

    candidates: tuple[PaperCandidate, ...]
    degraded_sources: tuple[str, ...] = ()


class LivePaperLookupPort(Protocol):
    def lookup(self, query: str) -> LiveLookupResult:
        """코퍼스 밖 논문 실시간 조회 — 제목·초록만 확보한다. 본문은 승격이 담당한다.

        구현이 여러 소스를 합성하더라도 **부분 저하는 예외가 아니다** — 살아 있는 소스의
        결과를 돌려주고 죽은 소스는 `degraded_sources`에 싣는다. 구성된 소스가 **전부**
        죽었을 때만 `SearchUnavailable`이다(§7). 단일 소스 구현이면 저하는 빈 튜플이다.
        """
        ...


class ContinuationSeedPort(Protocol):
    def seeds_from(self, turn_id: str) -> tuple[Any, ...]:
        """직전 턴이 찾아 둔 논문 핸들 — 이어가기의 씨앗(설계 §3.4). 없으면 빈 튜플.

        **포트로 두는 이유**: 이것만 I/O다(다른 씨앗은 요청을 읽는다). PR 2가 정확히 이
        이유로 스냅샷 접근을 러너에서 뺐다 — 러너에 매달았더니 5개 라우트가 LLM 러너에
        묶여, 러너가 구성되지 않는 배포에서 세션 삭제가 500이 됐다. 포트가 없으면 대역도
        타입 검사도 없고, 러너가 그 객체에 무엇을 물어봐도 되는지 적힌 곳이 없다.
        """
        ...


class PaperIndexQueuePort(Protocol):
    def enqueue_index(self, paper_ids: list[str]) -> None:
        """실시간 조회로 찾은 논문을 **백그라운드 색인**에 올린다(설계 §2.6 4단계).

        색인은 U1이 한다 — 여기서 하는 것은 요청뿐이고 결과를 기다리지 않는다(INV-EV-7과
        같은 경계). 그래서 반환값이 없고 **실패는 삼킨다**: 색인은 다음 질문을 위한 것이라
        지금 이 턴의 답에 아무 영향이 없고, 실패로 턴을 깨면 사용자가 얻는 것만 잃는다.

        이것이 "쓸수록 코퍼스가 그쪽으로 자란다"의 구현이다 — 없으면 같은 논문을 매 턴
        실시간으로 다시 조회하고, 코퍼스는 영원히 자라지 않는다.

        **목록을 받는다.** 한 턴이 올릴 논문은 도구 상한만큼(최대 여덟 편) 되는데, 한 편씩
        부르면 그 수만큼 왕복이 응답 반환 앞에 얹힌다.
        """
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
