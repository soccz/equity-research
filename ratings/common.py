"""Shared storage, fetching and credential helpers for ratings-v1.

Originals are content addressed under data/ratings/sources and never share pointer
files with the 60-company engine (equitylab.data.fetch_json writes data/sources).
Registrations record the manifest of every original they used, so an offline replay
reads exact files by hash instead of the latest pointer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import ssl
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from equitylab.data import ROOT, canonical, digest, read_verified

PROTOCOL_VERSION = "ratings-v1"
RATINGS = ROOT / "data/ratings"
SOURCES = RATINGS / "sources"
REGISTRATIONS = RATINGS / "v1"
LEDGER = RATINGS / "ledger.jsonl"
MARKETS = ("US", "KR")
RETRYABLE = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """A source could not be retrieved; callers record it instead of substituting data."""


def safe_key(key: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}", key):
        raise ValueError(f"Unsafe source key: {key!r}")
    return key


def sec_user_agent() -> str:
    """SEC fair-access policy requires a declared contact; refuse anonymous requests."""
    value = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in value:
        raise FetchError("SEC_USER_AGENT must name the requester and a contact email")
    return value


def ensure_dart_key(env_file: str | None = None) -> None:
    """Load the OpenDART key into the process environment only; the value is never logged."""
    if os.environ.get("DART_API_KEY"):
        return
    path = env_file or os.environ.get("EQUITY_DART_ENV")
    if not path:
        raise FetchError("DART_API_KEY not configured (set it or EQUITY_DART_ENV)")
    from equitylab.dart import load_key_file

    load_key_file(path)


def store(blob: bytes, key: str, url: str, provider: str, suffix: str) -> dict:
    SOURCES.mkdir(parents=True, exist_ok=True)
    sha = digest(blob)
    path = SOURCES / f"{safe_key(key)}-{sha[:16]}{suffix}"
    if not path.exists():
        path.write_bytes(blob)
    manifest = dict(
        key=key,
        url=url,
        sha256=sha,
        file=str(path.relative_to(ROOT)),
        bytes=len(blob),
        provider=provider,
        retrievedAt=datetime.now(timezone.utc).isoformat(),
    )
    pointer = SOURCES / f"{safe_key(key)}.manifest.json"
    pointer.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def load(manifest: dict) -> bytes:
    """Read an exact original recorded by a registration (hash verified)."""
    return read_verified(ROOT / manifest["file"], manifest["sha256"])


def latest(key: str) -> tuple[bytes, dict]:
    pointer = SOURCES / f"{safe_key(key)}.manifest.json"
    if not pointer.exists():
        raise FetchError(f"No stored original for {key}")
    manifest = json.loads(pointer.read_text())
    return load(manifest), manifest


def fetch(
    url: str,
    key: str,
    *,
    provider: str,
    online: bool = True,
    headers: dict | None = None,
    data: bytes | None = None,
    suffix: str = ".json",
    max_bytes: int = 60_000_000,
    retries: int = 3,
    pause: float = 0.25,
    redact: bool = False,
    keep_status: tuple = (),
) -> tuple[bytes, dict]:
    """Fetch once with retry on 429/5xx; 4xx other than 429 fails immediately.

    ``redact`` keeps credentialed URLs (e.g. OpenDART crtfc_key) out of manifests and errors.
    ``keep_status`` lists HTTP error codes whose response body is itself evidence (e.g.
    Yahoo's 400 "Data doesn't exist" chart error): such a body is stored as an original
    with ``httpStatus`` in its manifest and returned instead of raising.
    Offline mode returns the latest stored original for ``key``.
    """
    if not online:
        return latest(key)
    shown = re.sub(r"crtfc_key=[^&]+", "crtfc_key=REDACTED", url) if redact else url
    agent = {"User-Agent": "EquityResearchRatings/1.0", **(headers or {})}
    request = Request(url, data=data, headers=agent)
    delay = 1.0
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=60) as response:
                blob = response.read(max_bytes + 1)
            if len(blob) > max_bytes:
                raise FetchError(f"{provider}: response over {max_bytes} bytes ({key})")
            time.sleep(pause)
            return blob, store(blob, key, shown, provider, suffix)
        except HTTPError as exc:
            if exc.code in RETRYABLE and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            if exc.code in keep_status:
                blob = exc.read(max_bytes + 1)
                if len(blob) <= max_bytes:
                    time.sleep(pause)
                    manifest = store(blob, key, shown, provider, suffix)
                    manifest["httpStatus"] = exc.code
                    pointer = SOURCES / f"{safe_key(key)}.manifest.json"
                    text = json.dumps(manifest, ensure_ascii=False, indent=2)
                    pointer.write_text(text + "\n")
                    return blob, manifest
            raise FetchError(f"{provider}: HTTP {exc.code} for {key}") from None
        except (HTTPException, ssl.SSLError, OSError) as exc:
            # URLError, timeouts, resets, IncompleteRead and TLS failures: transient.
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise FetchError(f"{provider}: {type(exc).__name__} for {key}") from None
    raise FetchError(f"{provider}: retries exhausted for {key}")


def fetch_json(url: str, key: str, **kwargs) -> tuple[dict, dict]:
    blob, manifest = fetch(url, key, **kwargs)
    return json.loads(blob), manifest


def write_json(path: Path, value) -> str:
    """Write canonical-pretty JSON and return its SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text)
    return digest(text.encode())


def protocol_hash(protocol: dict) -> str:
    return digest(canonical(protocol))
