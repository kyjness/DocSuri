"""env 파서 헬퍼 — 유닛 settings 사본의 시맨틱 보존 검증."""

from __future__ import annotations

import pytest

from docsuri_shared.env import EnvConfigError, env_flag, env_float, env_int


def test_env_flag_defaults_off_and_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("X_FLAG", raising=False)
    assert env_flag("X_FLAG") is False
    assert env_flag("X_FLAG", default=True) is True
    monkeypatch.setenv("X_FLAG", "TRUE")
    assert env_flag("X_FLAG") is True
    monkeypatch.setenv("X_FLAG", "enabled")  # 오탈자류 — fail closed
    assert env_flag("X_FLAG") is False
    monkeypatch.setenv("X_FLAG", "")
    assert env_flag("X_FLAG", default=True) is True  # 빈 값 = 미설정


def test_env_int_and_float_parse_or_default(monkeypatch) -> None:
    monkeypatch.delenv("X_NUM", raising=False)
    assert env_int("X_NUM", 7) == 7
    assert env_float("X_NUM", 0.5) == 0.5
    monkeypatch.setenv("X_NUM", "42")
    assert env_int("X_NUM", 7) == 42
    monkeypatch.setenv("X_NUM", "0.25")
    assert env_float("X_NUM", 0.5) == 0.25


def test_malformed_numeric_value_raises_loudly(monkeypatch) -> None:
    # 잘못된 한도 값으로 조용히 기동하지 않는다 — composition root에서 즉시 실패.
    # 타입이 EnvConfigError인 것이 계약이다 — composition root가 "설정 오류"만 골라 재던지고
    # 나머지 예외는 마운트 실패로 담아두려면 plain ValueError와 구별돼야 한다. 변수명도 포함.
    monkeypatch.setenv("X_NUM", "abc")
    with pytest.raises(EnvConfigError, match="X_NUM"):
        env_int("X_NUM", 7)
    with pytest.raises(EnvConfigError, match="X_NUM"):
        env_float("X_NUM", 0.5)
