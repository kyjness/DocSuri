"""U7 grounding fidelity evaluation harness (QT-1).

Runs labeled summary-grounding cases through the deterministic ``GroundingValidator`` and
reports fabrication leaks (false-pass) and over-abstention (false-abstain). This is the
*summary-domain* counterpart to the shared ``GroundingEnforcementHook.run_eval_set`` (which
covers *search* grounding) — the two domains use different validators (ports.md §2.1).

Scope: harness + labeled corpora (seed, synthetic fraction spectrum, real-figure held-out).
``_NUMERIC_MISMATCH_THRESHOLD`` was recalibrated 0.5 → 0.4 from these corpora (US-S6,
2026-07-10): the zero-error plateau across all 32 labeled cases is [0.40, 0.50) and 0.4 is its
strict edge — see the rationale next to the constant in ``domain/grounding.py``. Any future
change must re-run this harness and may only move stricter (lower), never looser (C-2).
"""
