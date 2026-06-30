"""U7 grounding fidelity evaluation harness (QT-1).

Runs labeled summary-grounding cases through the deterministic ``GroundingValidator`` and
reports fabrication leaks (false-pass) and over-abstention (false-abstain). This is the
*summary-domain* counterpart to the shared ``GroundingEnforcementHook.run_eval_set`` (which
covers *search* grounding) — the two domains use different validators (ports.md §2.1).

Scope (scaffold): harness + a small, REVIEW-pending seed set that records current behavior.
It deliberately does NOT recalibrate ``_NUMERIC_MISMATCH_THRESHOLD`` — threshold tuning needs
a larger held-out labeled corpus (OP/team-owned) so a strict value doesn't regress into
over-abstention.
"""
