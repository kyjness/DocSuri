"""Scrubber regression: real secrets redacted, non-secret 40-char tokens preserved.

Guards the fix for the false-positive ***REDACTED_SECRET*** findings (design-review
audit H1): the generic 40-char base64 heuristic must NOT run over document content.

Run: pytest, or `python tests/test_scrub_credentials.py`.
"""

from design_reviewer.validation.loader import scrub_credentials


def test_real_secrets_are_redacted() -> None:
    akia = "AKIAIOSFODNN7EXAMPLE"  # 16 upper-alnum after AKIA
    assert akia not in scrub_credentials(f"key = {akia}")
    js = '{"aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}'
    assert "wJalrXUtnFEMI" not in scrub_credentials(js)


def test_non_secret_long_tokens_are_preserved() -> None:
    # 64-char sha256 hex and a 40-char hex id: NOT secrets, must survive untouched.
    sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    hex40 = "a" * 40
    ident = "IngestionResilienceServiceOrchestratorAdapter"  # 45-char identifier
    for token in (sha, hex40, ident):
        assert token in scrub_credentials(f"see {token} in the design"), token
    assert "REDACTED_SECRET" not in scrub_credentials(
        f"{sha} {hex40} {ident}"
    )


if __name__ == "__main__":
    test_real_secrets_are_redacted()
    test_non_secret_long_tokens_are_preserved()
    print("OK")
