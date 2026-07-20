"""emit_metric 헬퍼 — 포트 시그니처 강제 + best-effort 보증."""

from __future__ import annotations

from docsuri_shared.observability import emit_metric


class _Hub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float, dict]] = []

    def emit_metric(self, name: str, value: float, tags: dict) -> None:
        self.calls.append((name, value, tags))


def test_emits_full_port_signature() -> None:
    hub = _Hub()
    emit_metric(hub, "novelty.job_created")
    emit_metric(hub, "gateway.latency", 12.5, {"route": "/x"})
    assert hub.calls == [
        ("novelty.job_created", 1.0, {}),
        ("gateway.latency", 12.5, {"route": "/x"}),
    ]


def test_none_hub_and_raising_hub_never_fail_the_caller() -> None:
    emit_metric(None, "noop")  # 허브 미구성 — no-op

    class _Boom:
        def emit_metric(self, *args) -> None:
            raise RuntimeError("metrics down")

    emit_metric(_Boom(), "novelty.job_created")  # 예외가 새지 않는다
