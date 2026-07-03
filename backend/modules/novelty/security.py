from __future__ import annotations

import ipaddress
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
