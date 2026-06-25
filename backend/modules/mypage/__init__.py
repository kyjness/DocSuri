"""U10 My Page module — subscription status (mock, no real PG/billing).

Track: U10 (마이페이지). Deploy unit ① (the modular-monolith backend). Synchronous
get/subscribe/cancel only — no payment gateway, no webhook, no billing-cycle enforcement (Q10
decision: "하는 척만"). Mounted by the app-shell (``backend/wiring.py``) with the mock-first
in-memory adapter by default; the SQL adapter swaps in for production.

Other U10 menu items are intentionally NOT owned here: 관심 논문은 U4 ``GET /library``를,
로그아웃은 U3 ``POST /logout``을 프런트엔드가 그대로 호출한다 (다른 유닛 코드 변경 없음).
"""

__version__ = "0.1.0"
