"""U3 accounts 테스트 공용 픽스처.

`make_app`·`db_session`은 `test_controller_http.py`가 만들어 둔 것이고, 그 파일이 정본이다
(bare app + DI 시임 오버라이드 — U4 library의 conftest 패턴을 미러링한다). 여기서는 **다시
정의하지 않고 재노출만** 한다: 두 벌로 두면 한쪽만 고쳐져 같은 이름의 픽스처가 다르게
동작한다.

conftest에 두는 이유는 pytest가 이름으로 주입해 주기 때문이다 — 테스트 모듈이 픽스처를
직접 import하면 함수 인자가 그 이름을 가려 F811이 난다.
"""

from __future__ import annotations

from tests.accounts.test_controller_http import (  # noqa: F401
    db_session,
    make_app,
)
