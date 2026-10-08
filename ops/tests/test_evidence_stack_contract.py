"""EvidenceStack 계약 — 워커가 U2 읽기 경로를 **온전히** 쓸 수 있는 설정을 들고 있는가.

이 저장소에서 반복된 실패 모양이다: 리더 설정이 API 태스크에만 있고 워커에 없으면,
워커 쪽 기능이 **예외 없이 조용히** 줄어든다. novelty의 `view_figure`가 그랬고
(`test_novelty_stack_contract`), evidence는 `DOCSURI_BEDROCK_MODEL_ID`가 빠져 있어서
코퍼스 검색의 **벡터 leg가 통째로 off**인 채 BM25만으로 돌고 있었다 — 임베딩 호출 실패가
lexical-only 저하로 흡수되므로 로그에도 메트릭에도 "멈출 이유"가 안 보인다(2026-10-06).

값을 리터럴로 두 번 쓰지 않고 **compute_stack의 리더와 대조**한다. 임베딩 모델 컷오버는
한 자리만 고쳐지기 쉽고(그게 이 버그가 생긴 방식이다), 리더 둘이 다른 공간을 쓰면 질의가
다른 공간에서 채점된다(vector-spec §4).
"""

from __future__ import annotations

import re
from pathlib import Path

_STACKS = Path(__file__).resolve().parents[1] / "cdk" / "stacks"
EVIDENCE_SOURCE = (_STACKS / "evidence_stack.py").read_text()
COMPUTE_SOURCE = (_STACKS / "compute_stack.py").read_text()

# U2 리더가 인덱스와 같은 임베딩 공간을 쓰기 위해 한 벌로 필요한 설정(§4).
_READER_ENV = (
    "DOCSURI_OPENSEARCH_ENDPOINT",
    "DOCSURI_OPENSEARCH_INDEX",
    "DOCSURI_BEDROCK_MODEL_ID",
    "DOCSURI_BEDROCK_REGION",
)


def _env_value(source: str, key: str) -> str | None:
    """`'KEY': 'value'` / `"KEY": "value"`의 value. 표현식(f-string 등)이면 None."""
    match = re.search(rf"""['"]{key}['"]\s*:\s*['"]([^'"]+)['"]""", source)
    return match.group(1) if match else None


def test_worker_carries_every_reader_setting() -> None:
    # 인용부호 종류로 찾지 않는다 — 한쪽 스택이 재포맷되면(evidence는 홑따옴표,
    # compute는 겹따옴표) 올바른 스택에서 조용히 실패로 뒤집힌다.
    for key in _READER_ENV:
        assert re.search(rf"""['"]{key}['"]\s*:""", EVIDENCE_SOURCE), (
            f"{key}가 evidence 워커에 없다 — 코퍼스 검색이 조용히 줄어든다"
        )


def test_worker_reads_the_same_embedding_space_as_the_api_reader() -> None:
    for key in ("DOCSURI_BEDROCK_MODEL_ID", "DOCSURI_OPENSEARCH_INDEX", "DOCSURI_BEDROCK_REGION"):
        worker = _env_value(EVIDENCE_SOURCE, key)
        api = _env_value(COMPUTE_SOURCE, key)
        assert api is not None, f"compute_stack에서 {key}를 못 읽었다 — 이 테스트가 낡았다"
        assert worker == api, (
            f"{key}가 갈렸다: 워커={worker!r} API={api!r}. "
            "두 리더가 다른 임베딩 공간을 쓰면 질의가 다른 공간에서 채점된다"
        )


def test_worker_can_invoke_the_query_embedding_model() -> None:
    # 위의 anthropic 정책은 이것을 덮지 않는다(그쪽은 서울 리전의 `anthropic.*`).
    # 없으면 embed가 AccessDenied → lexical-only 저하로 흡수된다.
    assert "foundation-model/cohere.embed-multilingual-v3" in EVIDENCE_SOURCE
    assert re.search(r"""actions=\[['"]bedrock:InvokeModel['"]\]""", EVIDENCE_SOURCE)


def test_worker_can_call_the_cross_encoder_rerank() -> None:
    # U11 코퍼스 검색은 U2 오케스트레이터(`retrieve_ranked`)를 타므로 재랭킹 단계를 지난다.
    # 권한이 없으면 AccessDenied → fail-soft → baseline RRF로 **조용히** 되돌아간다.
    # (활성화 자체는 `DOCSURI_RERANK_MODEL_ARN`이고 그 값은 운영이 넣는다 — 코드에 없다.)
    assert re.search(r"""actions=\[['"]bedrock:Rerank['"]\]""", EVIDENCE_SOURCE)
    assert "foundation-model/cohere.rerank-v3-5:0" in EVIDENCE_SOURCE
