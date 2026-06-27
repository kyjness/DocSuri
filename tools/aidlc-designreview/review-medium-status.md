# Medium Findings Status

1. ✅ **SearchHistoryService deduplication correlation missing**: Addressed using `requestId` in dedupe_key.
2. ✅ **LibraryItemMeta lacks retraction propagation**: Addressed by consuming `PaperRetractedEvent` in U4.
3. ✅ **Personalization Decision lacks bounds**: Addressed by enforcing `[-0.1, 0.1]` bounds in U9/U2.
4. ✅ **U7/U6 Grounding Abstraction Divergence**: Addressed in `shared/ports.md`.
5. ✅ **U7 Map-Reduce Grounding Risk**: Addressed in U7 business rules.
6. ✅ **SearchGatewayPort Verification Rule**: Addressed in U4 `business-logic-model.md` with Contract Test requirement.
7. ✅ **VectorSpec PIN Process Underspecified**: Addressed in `shared/vector-spec.md` with `modelVer` tagging and U2 runtime check.
8. ✅ **AccountDeleted DLQ/Tracking**: Addressed via `AccountPurged` and U3 cascade tracking.
9. ✅ **PendingDTO Polling Contract**: Addressed in U7 `domain-entities.md`.
10. ✅ **doc-model Lazy Build Trigger**: Addressed in `events.md` via `DocModelBuildRequestedEvent`.
11. ✅ **U10 Mypage Undefined**: Defined in `components.md` and `services.md`.
12. ✅ **U11 Research Agent Undefined**: Noted as under construction in PR #183 (skipped as per user).
