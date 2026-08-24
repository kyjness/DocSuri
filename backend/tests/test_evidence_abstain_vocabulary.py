"""`abstainReason`은 닫힌 어휘다 — 백엔드가 내는 코드가 전부 그 안에 있어야 한다.

`TurnErrorResult.error_code`는 `str`이고 `service`가 어휘 밖 코드를 `unknown`으로 수렴시키는
다리를 둔다. 그 다리가 **실제 생산자**를 위해 도는 일은 없어야 한다 — 생산자 리터럴이
어휘 밖이면 화면이 그 사유를 영영 구분하지 못한다. 여기서 리터럴을 소스에서 긁어 대조한다.
"""

from __future__ import annotations

import re
from pathlib import Path

from docsuri_shared._generated.dtos.evidence_schema import AbstainReason

_EVIDENCE = Path(__file__).resolve().parents[1] / "modules" / "evidence"
_LITERAL = re.compile(r"""error_code=['"]([a-z_]+)['"]""")


def test_every_error_code_literal_is_an_abstain_reason():
    found = {
        m.group(1)
        for path in _EVIDENCE.rglob("*.py")
        if "testing" not in path.parts
        for m in _LITERAL.finditer(path.read_text(encoding="utf-8"))
    }

    assert found, "리터럴을 하나도 못 찾았다 — 정규식이 소스와 어긋났다"
    stray = sorted(code for code in found if code not in AbstainReason.__members__)
    assert stray == [], f"어휘 밖 error_code: {stray}"
