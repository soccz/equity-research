"""Fama-French 12 industries and financial exclusion for the ratings-v1 universe.

US issuers map SIC to FF12 with Ken French's official Siccodes12 ranges; a SIC no range
covers is 'Other', as in French's convention. The definition is pinned by the hash of its
parsed form, so a stored original with that hash is the same definition. It is used
during a Ken French outage (R12; the manifest records the fetch error as ``fallback``;
offline, when the latest stored original cannot be read) and when Ken French publishes
a changed or unreadable definition (L5; the manifest records the download as
``changed``). The stored original with the pinned definition is kept under its own
pointer (FF12_PINNED_KEY) before any download, since a download moves the latest
pointer to what it fetched; when neither pointer leads to it, the stored
Siccodes12 originals (FF12_KEY-<sha256 prefix>.zip) are searched for it (N4).
Korean issuers map KSIC through data/ratings/reference/ksic-ff12.json (longest prefix
wins). Exclusion follows docs/ratings-v1.md section 2: SIC 6000-6799; KSIC 64, 65, 66, 68
except holding companies (64992). OpenDART codes financial holding companies 64992 as
well, so a 64992 issuer whose registered name contains 금융지주 is excluded as financial.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import re
import zipfile
import zlib

from equitylab.data import ROOT, canonical, digest
from ratings import common
from ratings.common import FetchError, fetch, latest, safe_key

FF12 = (
    "NoDur",
    "Durbl",
    "Manuf",
    "Enrgy",
    "Chems",
    "BusEq",
    "Telcm",
    "Utils",
    "Shops",
    "Hlth",
    "Money",
    "Other",
)
FF12_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Siccodes12.zip"
FF12_KEY = "ken-french-siccodes12"
# Pointer to a stored original whose parsed definition is the pinned one (L5).
FF12_PINNED_KEY = FF12_KEY + "-pinned"
# A Siccodes12 original that does not parse (not an archive, damaged, another layout) ...
FF12_PARSE_ERRORS = (
    ValueError,
    LookupError,
    TypeError,
    EOFError,
    zlib.error,
    zipfile.BadZipFile,
)
# ... or a stored one that cannot be read (no pointer, a missing file, a hash mismatch).
FF12_ERRORS = (FetchError, OSError, *FF12_PARSE_ERRORS)
# Canonical hash of the parsed definition as retrieved on 2026-10-06; a change is reported.
FF12_DEFINITION_SHA256 = (
    "a605678ad15de28e678f759a9c88fb102e3163b1540ef9f53d64cc25733d920a"
)
KSIC_REFERENCE = ROOT / "data/ratings/reference/ksic-ff12.json"
FINANCIAL_SIC = (6000, 6799)
FINANCIAL_KSIC = ("64", "65", "66", "68")
KEPT_KSIC = ("64992",)
FINANCIAL_HOLDING_MARK = "금융지주"


def parse_ff12(blob: bytes) -> list[dict]:
    """Industries in file order: ``[{number, code, description, ranges: [[lo, hi], ...]}]``."""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        entries = [e for e in archive.infolist() if not e.is_dir()]
        if len(entries) != 1 or entries[0].file_size > 1_000_000:
            raise ValueError(
                "Siccodes12.zip must hold exactly one small definition file"
            )
        text = archive.read(entries[0]).decode("latin-1")
    industries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        span = re.fullmatch(r"\s*(\d{4})-(\d{4})(?:\s.*)?", line)
        head = re.fullmatch(r"\s*(\d{1,2})\s+([A-Za-z]+)\s+(.*?)\s*", line)
        if span and industries and int(span[1]) <= int(span[2]):
            industries[-1]["ranges"].append([int(span[1]), int(span[2])])
        elif head and not span:
            industries.append(
                dict(number=int(head[1]), code=head[2], description=head[3], ranges=[])
            )
        else:
            raise ValueError(f"Unrecognised Siccodes12 line: {line.strip()[:40]!r}")
    if tuple(i["code"] for i in industries) != FF12:
        raise ValueError("Siccodes12 industries differ from the FF12 codes")
    spans = sorted(tuple(r) for i in industries for r in i["ranges"])
    if any(a[1] >= b[0] for a, b in zip(spans, spans[1:])):
        raise ValueError("Siccodes12 ranges overlap")
    return industries


def load_ff12(online: bool = True) -> tuple[list[dict], dict]:
    """The FF12 industries and the manifest of the original they were read from.

    Online, the stored original with the pinned definition is first kept under
    FF12_PINNED_KEY (``_keep_pinned``), then Siccodes12 is downloaded:

    - a FetchError (outage, R12) uses the pinned stored original (``_pinned``); its
      manifest carries ``fallback``, the fetch error;
    - a download that does not parse to FF12_DEFINITION_SHA256 (Ken French published a
      changed definition, L5) uses the pinned stored original; its manifest carries
      ``changed`` = the download's {sha256, file, retrievedAt, definitionSha256, error};
    - without a pinned stored original an outage stays a FetchError, a changed
      definition is returned as downloaded (the universe reports
      ff12_definition_changed and registrations refuse the US) and a download that
      does not parse raises its parse error (a universe DATA_ERRORS type).

    Offline reads the latest stored original, and the pinned one when that holds
    another definition or cannot be read (no pointer, a missing file, a hash
    mismatch: then like an outage, ``fallback``); it never writes. The pinned stored
    original is found by ``_pinned``.
    """
    if online:
        _keep_pinned()
    # Online an outage (FetchError) falls back; offline so does an unreadable original.
    unreadable = FetchError if online else FF12_ERRORS
    try:
        blob, manifest = fetch(
            FF12_URL, FF12_KEY, provider="Ken French", online=online, suffix=".zip"
        )
    except unreadable as exc:
        industries, stored, why = _pinned()
        if industries is None:
            raise FetchError(
                f"{exc}; no usable stored Siccodes12 with the pinned definition ({why})"
            ) from None
        return industries, dict(stored, fallback=str(exc))
    try:
        industries = parse_ff12(blob)
    except FF12_PARSE_ERRORS as exc:
        industries, definition, error = None, None, exc
    else:
        definition, error = ff12_hash(industries), None
        if definition == FF12_DEFINITION_SHA256:
            return industries, manifest
    pinned, stored, _ = _pinned()
    if pinned is None:
        if error is not None:
            raise error
        return industries, manifest
    changed = dict(
        sha256=manifest.get("sha256"),
        file=manifest.get("file"),
        retrievedAt=manifest.get("retrievedAt"),
        definitionSha256=definition,
        error=None if error is None else f"{type(error).__name__}: {error}",
    )
    return pinned, dict(stored, changed=changed)


def _pinned() -> tuple:
    """``(industries, manifest, why)`` of a stored original whose parsed definition is
    the pinned one: the original kept under FF12_PINNED_KEY, else the latest under
    FF12_KEY, else (N4) one found among the stored originals (``_stored_pinned``).
    ``(None, None, why)`` when there is none."""
    why = []
    for key in (FF12_PINNED_KEY, FF12_KEY):
        try:
            blob, manifest = latest(key)
            industries = parse_ff12(blob)
        except FF12_ERRORS as exc:
            why.append(f"{key}: {exc}")
            continue
        if ff12_hash(industries) == FF12_DEFINITION_SHA256:
            return industries, manifest, ""
        why.append(f"{key}: the stored Siccodes12 differs from the pinned definition")
    found = _stored_pinned()
    if found is not None:
        return (*found, "")
    why.append(f"no stored {FF12_KEY}-*.zip has the pinned definition")
    return None, None, "; ".join(why)


def _stored_pinned() -> tuple | None:
    """N4: ``(industries, manifest)`` of a stored Siccodes12 original that no pointer
    leads to: a data/ratings/sources/FF12_KEY-<sha256[:16]>.zip (as ratings.common.store
    names it) whose bytes match the hash in its name and whose parsed definition is the
    pinned one, the first by name. Its manifest is rebuilt from the file
    (``retrievedAt`` None: the pointer that held it was replaced; ``located``)."""
    name = re.compile(re.escape(FF12_KEY) + r"-([0-9a-f]{16})\.zip")
    try:
        paths = sorted(common.SOURCES.glob(f"{FF12_KEY}-*.zip"))
    except OSError:
        return None
    for path in paths:
        match = name.fullmatch(path.name)
        if not match:
            continue
        try:
            blob = path.read_bytes()
            sha = digest(blob)
            industries = parse_ff12(blob) if sha[:16] == match[1] else None
        except (OSError, *FF12_PARSE_ERRORS):
            continue
        if industries is None or ff12_hash(industries) != FF12_DEFINITION_SHA256:
            continue
        try:
            file = str(path.relative_to(common.ROOT))
        except ValueError:
            file = str(path)
        return industries, dict(
            key=FF12_KEY,
            url=FF12_URL,
            sha256=sha,
            file=file,
            bytes=len(blob),
            provider="Ken French",
            retrievedAt=None,
            located="stored original without a pointer (sources scan)",
        )
    return None


def _keep_pinned() -> None:
    """Keep the stored original with the pinned definition under FF12_PINNED_KEY before
    a download can move the FF12_KEY pointer to a changed definition (L5). Writes the
    pointer (the original's own manifest, as ratings.common.store writes pointers) only
    when none with the pinned definition is kept yet and the latest original has it."""
    try:
        blob, _ = latest(FF12_PINNED_KEY)
        if ff12_hash(parse_ff12(blob)) == FF12_DEFINITION_SHA256:
            return
    except FF12_ERRORS:
        pass
    try:
        blob, manifest = latest(FF12_KEY)
        if ff12_hash(parse_ff12(blob)) != FF12_DEFINITION_SHA256:
            return
    except FF12_ERRORS:
        return
    pointer = common.SOURCES / f"{safe_key(FF12_PINNED_KEY)}.manifest.json"
    try:
        common.SOURCES.mkdir(parents=True, exist_ok=True)
        pointer.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:
        raise FetchError(f"cannot keep the pinned Siccodes12 original: {exc}") from None


def ff12_hash(industries: list[dict]) -> str:
    return digest(canonical(industries))


def sic_sector(sic: int, industries: list[dict]) -> str:
    for industry in industries:
        if any(lo <= sic <= hi for lo, hi in industry["ranges"]):
            return industry["code"]
    return "Other"


def financial_sic(sic: int) -> bool:
    return FINANCIAL_SIC[0] <= sic <= FINANCIAL_SIC[1]


def financial_ksic(code: str) -> bool:
    return code.startswith(FINANCIAL_KSIC) and not code.startswith(KEPT_KSIC)


def financial_holding(code: str, registered_name: str) -> bool:
    """A kept holding-company code (64992) whose registered name marks a 금융지주회사."""
    return code.startswith(KEPT_KSIC) and FINANCIAL_HOLDING_MARK in (
        registered_name or ""
    )


def load_ksic(path: Path = KSIC_REFERENCE) -> tuple[dict, dict]:
    """``({ksic prefix: FF12 code}, source record)``; the record carries the file SHA-256."""
    blob = path.read_bytes()
    reference = json.loads(blob)
    table = {}
    for group, sizes in (("divisions", (2,)), ("overrides", (3, 4, 5))):
        for code, entry in reference[group].items():
            if not (code.isdigit() and len(code) in sizes and entry["ff12"] in FF12):
                raise ValueError(f"Invalid KSIC reference entry {code!r}")
            table[code] = entry["ff12"]
    for code, sector in table.items():
        if code[:2] not in table:
            raise ValueError(f"KSIC override {code} lacks its division")
        if (sector == "Money") != financial_ksic(code):
            raise ValueError(
                f"KSIC {code}: Money must coincide with financial exclusion"
            )
    record = dict(
        key="ksic-ff12",
        url=None,
        sha256=digest(blob),
        file=str(path.resolve().relative_to(ROOT)),
        bytes=len(blob),
        provider="ratings-v1 reference",
    )
    return table, record


def ksic_sector(code: str, table: dict) -> str | None:
    """FF12 code of the longest matching KSIC prefix, or None for unreadable/unmapped codes."""
    if not re.fullmatch(r"\d{2,5}", code or ""):
        return None
    for size in range(len(code), 1, -1):
        if code[:size] in table:
            return table[code[:size]]
    return None
