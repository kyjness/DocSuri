from __future__ import annotations

import ipaddress
import os
import re
from urllib.parse import urlparse

ALLOWED_EXTERNAL_HOSTS = frozenset(
    {
        "github.com",
        "api.github.com",
        "huggingface.co",
        "kaggle.com",
        "www.kaggle.com",
        "paperswithcode.com",
        "zenodo.org",
        "notion.com",
        "api.notion.com",
    }
)


def sanitize_external_query(text: str, *, max_len: int = 180) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned[:max_len]


def encrypt_secret(plaintext: str) -> str:
    """US-NV8(#258)/SEC-8 — Notion 연결 토큰 대칭 암호화(Fernet). 키 미구성은 ValueError."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def _fernet():
    from cryptography.fernet import Fernet

    key = os.getenv("DOCSURI_NOTION_TOKEN_KEY")
    if not key:
        raise ValueError("Notion 연결 저장소가 구성되지 않았습니다.")
    return Fernet(key.encode("utf-8"))


def is_safe_external_url(url: str, allowed_hosts: set[str] | frozenset[str] | None = None) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return False
    hosts = allowed_hosts or ALLOWED_EXTERNAL_HOSTS
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in hosts)
