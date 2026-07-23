"""MockEmailClient 로그 출력 게이트 — 로컬에서만 링크를 찍고, 그 밖에서는 토큰을 지운다.

Mock은 로컬(ENV=local·SES_MOCK)에서만 배선되지만, 배선 실수로 비로컬에서 살아 있어도 bearer
토큰이 로그에 남지 않아야 한다(심층 방어). 두 분기를 모두 고정한다.
"""

import logging

from backend.modules.accounts.integrations.email import MockEmailClient


async def test_mock_email_prints_link_on_local_run(monkeypatch, caplog):
    # 콘솔이 곧 메일함 — 링크가 그대로 보여야 가입→인증 플로우를 로컬에서 완주할 수 있다.
    monkeypatch.setenv("ENV", "local")
    monkeypatch.delenv("SES_MOCK", raising=False)
    client = MockEmailClient()
    with caplog.at_level(logging.INFO):
        await client.send_verification_email("user@example.com", "tok123", "http://x/verify")
    assert "tok123" in caplog.text
    assert "user@example.com" in caplog.text


async def test_mock_email_redacts_link_outside_local(monkeypatch, caplog):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("SES_MOCK", raising=False)
    client = MockEmailClient()
    with caplog.at_level(logging.INFO):
        await client.send_verification_email("user@example.com", "tok123", "http://x/verify")
        await client.send_password_reset_email("user@example.com", "tok456", "http://x/reset")
    assert "tok123" not in caplog.text
    assert "tok456" not in caplog.text
    assert "user@example.com" not in caplog.text
    # 토큰 어트리뷰트 캡처는 로그 게이트와 무관하게 유지된다(테스트 플로우 의존).
    assert client.last_verification_token == "tok123"
    assert client.last_password_reset_token == "tok456"
