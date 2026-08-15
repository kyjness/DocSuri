#!/usr/bin/env python
"""Local-readiness smoke — walk the non-agent surface in-process against local infra.

The 2026-07 local migration only E2E-verified search/papers/summary;
everything else was left un-exercised, so gaps (a feature flag left off, a real_wiring adapter
never switched off Bedrock, a mock read path) only surfaced when stumbled on by eye. This walks
each non-agent module's representative flow ONCE, against the real adapters + local stores
(Postgres / OpenSearch / s3proxy / Redis), and classifies every step. Re-run it after each
refactor as a "is local still healthy" check.

Auth is real: it provisions an ACTIVE USER (idempotent, via the accounts CredentialRepository),
logs in through `/auth/login`, and carries the issued `session_id` cookie — so the U6 gateway
middleware resolves `request.state.principal` exactly as in production, uniformly across modules.

Agents (u11 evidence / u12 novelty / research) are OUT OF SCOPE — they are being re-architected.

Usage (from repo root, with the backend venv and .env sourced):

    set -a; source .env; set +a
    backend/.venv/bin/python tools/local/smoke.py             # free surface only
    backend/.venv/bin/python tools/local/smoke.py --with-llm  # + a few paid confirmations
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Make `backend.*` importable however the script is launched (repo root = two levels up).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx

TEST_EMAIL = os.getenv("SMOKE_EMAIL", "smoke@local.test")
# Meets PasswordPolicy: >=10 chars, upper, digit, special.
TEST_PASSWORD = os.getenv("SMOKE_PASSWORD", "SmokeLocal#2026")
# A paper re-ingested with the current parser (@10) so the read path has real content.
KNOWN_PAPER = os.getenv("SMOKE_PAPER_ID", "2402.01809")

OK, DEGRADED, FAIL, SKIP = "ok", "degraded", "fail", "skip"


@dataclass
class Step:
    module: str
    label: str
    method: str
    path: str
    body: dict | None = None
    expect: set[int] = field(default_factory=lambda: {200})
    paid: bool = False
    # (json) -> (verdict, note) refinement when the status is accepted; empty-but-legit stays ok.
    check: object | None = None


@dataclass
class Result:
    step: Step
    status: int
    verdict: str
    note: str = ""


def provision_user() -> str:
    """Idempotently ensure an ACTIVE USER account exists locally; return its account id."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.modules.accounts.models import AccountStatus, UserRole
    from backend.modules.accounts.password import get_password_hasher
    from backend.modules.accounts.repository.credential import (
        AccountTable,
        Base,
        CredentialRepository,
    )

    db_url = os.environ["DATABASE_URL"]
    if db_url.startswith("postgresql://"):  # mirror the app engine (backend/db.py) — pin psycopg3
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://") :]
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)  # local bootstrap; no-op once migrated
    session = sessionmaker(bind=engine)()
    try:
        repo = CredentialRepository(session)
        account = repo.get_by_email(TEST_EMAIL)
        if account is None:
            account = AccountTable(
                email=TEST_EMAIL,
                password_hash=get_password_hasher().hash(TEST_PASSWORD),
                status=AccountStatus.ACTIVE.value,
                role=UserRole.USER.value,
            )
            session.add(account)
            session.flush()
        elif account.status != AccountStatus.ACTIVE.value:
            account.status = AccountStatus.ACTIVE.value
            repo.update_account(account)
        session.commit()
        return account.id
    finally:
        session.close()


def _session_cookie(login_response: httpx.Response) -> str | None:
    # The cookie is Secure, so httpx's jar drops it over the in-process http base_url — read it
    # straight off Set-Cookie instead and carry it as an explicit Cookie header.
    for set_cookie in login_response.headers.get_list("set-cookie"):
        if set_cookie.startswith("session_id="):
            return set_cookie.split(";", 1)[0].split("=", 1)[1]
    return None


# --- per-step refinements: catch a 2xx that is actually a degraded/empty local state -----------
def _search_check(body: dict) -> tuple[str, str]:
    hits = body.get("results") or body.get("cards") or body.get("hits") or []
    if not hits:
        return DEGRADED, "0 results (empty index or mock read path?)"
    return OK, f"{len(hits)} results"


def _docmodel_check(body: dict) -> tuple[str, str]:
    sections = body.get("sections") or (body.get("docModel") or {}).get("sections") or []
    return (OK, f"{len(sections)} sections") if sections else (DEGRADED, "no sections")


def _summary_check(body: dict) -> tuple[str, str]:
    anchors = body.get("anchors")
    if anchors is None and isinstance(body.get("summary"), dict):
        anchors = body["summary"].get("anchors")
    n = len(anchors) if isinstance(anchors, list) else 0
    outcome = body.get("outcome") or body.get("state") or "?"
    return (OK, f"{n} anchors, outcome={outcome}") if n else (DEGRADED, f"0 anchors, outcome={outcome}")


def _citation_check(body: dict) -> tuple[str, str]:
    edges = body.get("edges") or []
    return (OK, f"{len(edges)} edges") if edges else (DEGRADED, "0 edges (S2 rate-limit / no refs?)")


def steps() -> list[Step]:
    p = KNOWN_PAPER
    return [
        Step("accounts", "session", "GET", "/auth/session"),
        Step("discovery", "search", "POST", "/api/search",
             {"query": "graph neural network"}, check=_search_check),
        Step("paper", "meta", "GET", f"/api/papers/{p}"),
        Step("paper", "doc-model", "GET", f"/api/papers/{p}/doc-model", check=_docmodel_check),
        Step("paper", "assets", "GET", f"/api/papers/{p}/assets"),
        Step("glossary", "glossary", "GET", "/api/glossary"),
        Step("library", "items", "GET", "/library/items"),
        Step("library", "history", "GET", "/library/history"),
        Step("library", "saved-searches", "GET", "/library/saved-searches"),
        Step("personalization", "settings", "GET", "/api/personalization/settings"),
        Step("personalization", "recently-viewed", "GET", "/mypage/recently-viewed"),
        Step("mypage", "account-profile", "GET", "/mypage/account-profile"),
        Step("mypage", "consents", "GET", "/mypage/consents"),
        Step("mypage", "subscription", "GET", "/mypage/subscription"),
        # 404 is the correct "no ORCID linked" state for a fresh account, not a gap.
        Step("mypage", "orcid-profile", "GET", "/mypage/orcid-profile", expect={200, 404}),
        # ops dashboard is ADMIN-gated; a USER 403 is the correct authz outcome, not a gap.
        Step("ops", "dashboard", "GET", "/ops/dashboard", expect={200, 403}),
        Step("ops", "incidents", "GET", "/ops/incidents", expect={200, 403}),
        # --- paid (only with --with-llm): Bedrock a few cents, S2 live ---
        Step("summarize", "summary", "POST", "/api/summarize",
             {"task": "summary", "paperId": p, "persona": "expert", "scope": "abstract"},
             paid=True, check=_summary_check),
        Step("summarize", "translate", "POST", "/api/summarize",
             {"task": "translate", "paperId": p, "scope": "abstract"}, paid=True),
        Step("citation", "citation-tree", "GET", f"/api/papers/{p}/citation-tree",
             paid=True, check=_citation_check),
    ]


async def run(with_llm: bool) -> list[Result]:
    from backend.main import app

    results: list[Result] = []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://smoke") as client:
        login = await client.post(
            "/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        if login.status_code != 200:
            raise SystemExit(f"login failed ({login.status_code}): {login.text[:300]}")
        sid = _session_cookie(login)
        if not sid:
            raise SystemExit("login succeeded but no session_id cookie was issued")
        headers = {"cookie": f"session_id={sid}"}

        for step in steps():
            if step.paid and not with_llm:
                results.append(Result(step, 0, SKIP, "paid — pass --with-llm"))
                continue
            try:
                resp = await client.request(
                    step.method, step.path, json=step.body, headers=headers, timeout=120.0
                )
            except Exception as exc:  # noqa: BLE001 — a hop that raises is itself the finding
                results.append(Result(step, 0, FAIL, f"{type(exc).__name__}: {exc}"))
                continue
            if resp.status_code not in step.expect:
                results.append(Result(step, resp.status_code, FAIL, resp.text[:160]))
                continue
            verdict, note = OK, f"HTTP {resp.status_code}"
            if step.check is not None and resp.status_code == 200:
                try:
                    verdict, note = step.check(resp.json())
                except Exception as exc:  # noqa: BLE001
                    verdict, note = DEGRADED, f"unparseable body: {exc}"
            results.append(Result(step, resp.status_code, verdict, note))
    return results


def report(results: list[Result]) -> int:
    icon = {OK: "✓", DEGRADED: "~", FAIL: "✗", SKIP: "·"}
    width = max(len(f"{r.step.module}/{r.step.label}") for r in results)
    print(f"\nLocal-readiness smoke — paper={KNOWN_PAPER}\n" + "─" * (width + 30))
    for r in results:
        name = f"{r.step.module}/{r.step.label}".ljust(width)
        print(f"  {icon[r.verdict]} {name}  {r.verdict:8} {r.note}")
    counts = {v: sum(1 for r in results if r.verdict == v) for v in (OK, DEGRADED, FAIL, SKIP)}
    print("─" * (width + 30))
    print(f"  {counts[OK]} ok · {counts[DEGRADED]} degraded · {counts[FAIL]} fail · {counts[SKIP]} skip\n")
    return 1 if counts[FAIL] else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--with-llm", action="store_true", help="include paid routes (Bedrock/S2)")
    args = ap.parse_args()
    if "DATABASE_URL" not in os.environ:
        raise SystemExit("DATABASE_URL not set — run `set -a; source .env; set +a` first")
    provision_user()
    return report(asyncio.run(run(args.with_llm)))


if __name__ == "__main__":
    sys.exit(main())
