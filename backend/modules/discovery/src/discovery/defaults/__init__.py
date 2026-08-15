"""Production defaults for the U6 ports — the no-op / in-memory path taken when a hook is
not injected.

These are NOT test doubles: ``build_real_orchestrator`` and the app-shell both construct them
on the serving path (a search still has to run when CloudWatch, the cost guard, or the event
bus is absent). They lived under the old ``mocks`` package only because that package predated
the real adapters; the name made "can we delete the mocks?" unanswerable.
"""
