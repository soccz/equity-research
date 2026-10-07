#!/usr/bin/env python3
"""Assemble the public Pages artifact: the committed site/ unchanged plus the ratings page.

    python scripts/build_ratings_page.py --site site --out OUT

OUT receives a byte-for-byte copy of site/ and a ratings/ folder: the page sources from
pages/ratings/ and data derived only from the committed public ratings files
(data/ratings/ledger.jsonl, v1/<YYYY-MM>.json, the latest evaluation/<D>.json). The
ledger's hash chain, every registration file's SHA-256 and protocol hash are verified
through ratings.registry first; if that fails, the page shows only that the ledger did
not verify (never partial data). Dry runs, rehearsals and work files are never read.

The assembled folder is then checked: OUT minus ratings/ equals site/; a throwaway
copy with a manifest listing every file passes equitylab.publication.verify_site
(file set, hashes, forbidden strings, relative links); ratings/manifest.json matches
its files. The derived files depend only on their inputs (no wall clock), and
ratings/manifest.json carries a contentDigest of everything a visitor receives from
ratings/ except the build commit, so the deploy can be skipped when nothing changed.

``--preview-dry-run FILE`` (local only, never used by the workflow) shows a dry-run
file as a month under a "시험 실행 미리보기 — 공식 등급 아님" banner.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from equitylab import ledger  # noqa: E402
from equitylab.publication import verify_site  # noqa: E402
from ratings import rating, registry  # noqa: E402

PAGE = ROOT / "pages/ratings"
PAGE_FILES = ("index.html", "ratings.css", "ratings.js", "glossary.ko.json")
EVALUATIONS = ROOT / "data/ratings/evaluation"
COLUMNS = (
    "id",
    "market",
    "ticker",
    "name",
    "sector",
    "label",
    "labelReason",
    "previousLabel",
    "percentile",
    "composite",
    "marketCap",
    "fcfYield",
    "cashProfitability",
    "momentum12_1",
    "zFcfYield",
    "zCashProfitability",
    "zMomentum",
    "cfoTTM",
    "capexTTM",
    "assets",
    "close",
    "closeDate",
    "currency",
    "filedAt",
    "issues",
    "reason",
    "zBasis",
    "fundamentalsError",
)
# Per-market evaluation summary fields shown on the page (ratings.evaluate._summary).
SUMMARY = (
    "complete",
    "inProgress",
    "pending",
    "frozen",
    "frozenWithUnresolved",
    "unresolvedMembers",
    "revisedAfterFreeze",
    "missedRegistrations",
    "seriesErrors",
    "valuedThrough",
    "primary",
    "primaryNonNeutral",
    "avoid",
    "spread",
    "ic",
)


class BuildError(RuntimeError):
    """The assembled artifact failed a check; nothing may be deployed."""


def digest(blob: bytes) -> str:
    return sha256(blob).hexdigest()


def dump(value) -> bytes:
    """Deterministic JSON bytes (sorted keys, no spaces, UTF-8, trailing newline)."""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode()


def rounded(value, places: int):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return round(float(value), places)


def money(value):
    return None if value is None else int(round(float(value)))


def view_row(row: dict) -> list:
    """One registration row as the page's compact column list (COLUMNS)."""
    signals, z = row.get("signals") or {}, row.get("z") or {}
    inputs = row.get("inputs") or {}
    values = dict(
        id=row.get("id"),
        market=row.get("market"),
        ticker=row.get("ticker"),
        name=row.get("name"),
        sector=row.get("sector"),
        label=row.get("label"),
        labelReason=row.get("labelReason"),
        previousLabel=row.get("previousLabel"),
        percentile=rounded(row.get("percentile"), 4),
        composite=rounded(row.get("composite"), 4),
        marketCap=money(row.get("marketCap")),
        fcfYield=rounded(signals.get("fcfYield"), 6),
        cashProfitability=rounded(signals.get("cashProfitability"), 6),
        momentum12_1=rounded(signals.get("momentum12_1"), 6),
        zFcfYield=rounded(z.get("fcfYield"), 3),
        zCashProfitability=rounded(z.get("cashProfitability"), 3),
        zMomentum=rounded(z.get("momentum12_1"), 3),
        cfoTTM=money(inputs.get("cfoTTM")),
        capexTTM=money(inputs.get("capexTTM")),
        assets=money(inputs.get("assets")),
        close=rounded(inputs.get("close"), 4),
        closeDate=inputs.get("closeDate"),
        currency=inputs.get("currency"),
        filedAt=inputs.get("filedAt"),
        issues=sorted(set(row.get("issues") or [])),
        reason=row.get("reason"),
        zBasis=sorted({b for b in (row.get("zBasis") or {}).values() if b}) or None,
        fundamentalsError=(inputs.get("fundamentalsError") or None),
    )
    return [values[c] for c in COLUMNS]


def month_view(
    content: dict, ledger_block: dict | None, preview: bool, event: dict | None = None
) -> dict:
    rows = sorted(
        content.get("rows") or [],
        key=lambda r: (
            str(r.get("market")),
            r.get("percentile") is None,
            -(r.get("percentile") or 0),
            str(r.get("ticker")),
        ),
    )
    block = ledger_block or {}
    return dict(
        month=content.get("month"),
        kind=content.get("kind"),
        preview=preview,
        asOf=content.get("asOf"),
        registeredAt=content.get("registeredAt"),
        registrationDay=content.get("registrationDay"),
        protocolHash=content.get("protocolHash"),
        labels=content.get("labels"),
        ledger=dict(
            sequence=block.get("sequence"),
            eventId=block.get("eventId"),
            eventHash=block.get("hash"),
            recordedAt=block.get("recordedAt"),
            fileSha256=(event or {}).get("fileSha256"),
        ),
        columns=list(COLUMNS),
        rows=[view_row(r) for r in rows],
    )


def gate_view(event: dict | None) -> dict | None:
    if not event:
        return None
    keys = (
        "market",
        "asOf",
        "verdict",
        "rate",
        "threshold",
        "computable",
        "nonFinancial",
        "recordedAt",
        "protocolHash",
        "hash",
    )
    return {k: event.get(k) for k in keys if k in event}


def evaluation_view(path: Path | None) -> dict | None:
    if path is None:
        return None
    result = json.loads(path.read_text())
    periods = []
    for p in result.get("periods") or []:
        prefer = ((p.get("portfolios") or {}).get(rating.PREFER)) or {}
        periods.append(
            dict(
                market=p.get("market"),
                month=p.get("month"),
                status=p.get("status"),
                entry=p.get("entry"),
                exit=p.get("exit"),
                frozen=bool(p.get("frozen")),
                flags=sorted(p.get("flags") or []),
                errors=len(p.get("errors") or []),
                preferNetSectorExcess=rounded(prefer.get("netSectorExcess"), 6),
                spread=rounded(p.get("spread"), 6),
                ic=rounded(p.get("ic"), 4),
            )
        )
    summary = result.get("summary") or {}
    return dict(
        file=f"data/ratings/evaluation/{path.name}",
        through=result.get("through"),
        valuedThrough=result.get("valuedThrough"),
        official=result.get("official"),
        summary={
            market: {k: values.get(k) for k in SUMMARY}
            for market, values in sorted(summary.items())
            if isinstance(values, dict)
        },
        periods=periods,
    )


def latest_evaluation() -> Path | None:
    files = sorted(EVALUATIONS.glob("*.json")) if EVALUATIONS.exists() else []
    return files[-1] if files else None


def schedule() -> dict:
    gate = registry.gate_rule()
    return dict(
        gateAsOf=gate["asOf"],
        gateDate=gate["date"],
        thresholds=gate["thresholds"],
        firstAsOf="2026-10-30",
        windowSessions=int(registry.setting("registrationWindowSessions")),
        reviewDate="2028-11-30",
    )


def commit() -> str | None:
    found = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return found.stdout.strip() or None if found.returncode == 0 else None


def derive(preview: list) -> tuple[dict, dict]:
    """(index, {month: view}) from the committed public files (and previews)."""
    index = dict(
        status="ok",
        protocol=dict(
            version=rating.PROTOCOL.get("version", "ratings-v1"),
            hash=rating.PROTOCOL_HASH,
        ),
        schedule=schedule(),
        gates=dict(US=None, KR=None),
        months=[],
        evaluation=None,
        preview=bool(preview),
        ledger=None,
    )
    months = {}
    try:
        events = ledger.read(registry.LEDGER)
        registrations = registry.registrations(strict=True)
        head = registry.ledger_head()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        index.update(status="ledger_invalid", error=f"{type(exc).__name__}: {exc}")
        return index, months
    index["ledger"] = head
    for market in ("US", "KR"):
        index["gates"][market] = gate_view(registry.gate(market))
    by_month = {
        e.get("month"): e for e in events if e.get("type") == registry.EVENT_TYPE
    }
    for content in registrations:
        event = by_month.get(content.get("month"))
        view = month_view(content, content.get("ledger"), preview=False, event=event)
        months[view["month"]] = view
    for path in preview:
        content = json.loads(Path(path).read_text())
        if content.get("kind") != "dry-run":
            raise BuildError(f"{path}: --preview-dry-run takes dry-run files only")
        view = month_view(content, None, preview=True)
        view["month"] = f"{view['month']}-preview"
        months[view["month"]] = view
    for name in sorted(months):
        view = months[name]
        index["months"].append(
            dict(
                month=name,
                preview=view["preview"],
                asOf=view["asOf"],
                registeredAt=view["registeredAt"],
                labels=view["labels"],
                eventHash=view["ledger"]["eventHash"],
                fileSha256=view["ledger"]["fileSha256"],
                data=f"data/{name}.json",
            )
        )
    index["evaluation"] = evaluation_view(latest_evaluation())
    return index, months


def content_digest(files: dict[str, bytes]) -> str:
    """SHA-256 over the ratings folder's files (path and hash of each, sorted). It is
    taken before the build commit is added, so equal content gives an equal digest."""
    hashed = sha256()
    for relative in sorted(files):
        hashed.update(f"{relative}\0{digest(files[relative])}\n".encode())
    return hashed.hexdigest()


def assemble(site: Path, out: Path, preview: list) -> dict:
    site, out = site.resolve(), out.resolve()
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(site, out, symlinks=True)
    folder = out / "ratings"
    (folder / "data").mkdir(parents=True)
    index, months = derive(preview)
    files = {name: (PAGE / name).read_bytes() for name in PAGE_FILES}
    for name, view in months.items():
        files[f"data/{name}.json"] = dump(view)
    index["contentDigest"] = content_digest({**files, "data/index.json": dump(index)})
    index["commit"] = commit()
    files["data/index.json"] = dump(index)
    for relative, blob in files.items():
        (folder / relative).write_bytes(blob)
    manifest = dict(
        contentDigest=index["contentDigest"],
        commit=index["commit"],
        status=index["status"],
        preview=index["preview"],
        files={
            p.relative_to(folder).as_posix(): digest(p.read_bytes())
            for p in sorted(folder.rglob("*"))
            if p.is_file()
        },
    )
    (folder / "manifest.json").write_bytes(dump(manifest))
    check(site, out)
    return manifest


def check(site: Path, out: Path) -> None:
    """The three checks of the assembled artifact (BuildError on any failure)."""
    base = {
        p.relative_to(site).as_posix(): p.read_bytes()
        for p in site.rglob("*")
        if p.is_file()
    }
    assembled = {
        p.relative_to(out).as_posix(): p.read_bytes()
        for p in out.rglob("*")
        if p.is_file() and not p.relative_to(out).as_posix().startswith("ratings/")
    }
    if base != assembled:
        raise BuildError("the assembled artifact differs from site/ outside ratings/")
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "pages"
        shutil.copytree(out, copy)
        listed = {
            p.relative_to(copy).as_posix(): digest(p.read_bytes())
            for p in copy.rglob("*")
            if p.is_file() and p.name != "site-manifest.json"
        }
        (copy / "site-manifest.json").write_bytes(dump(dict(files=listed)))
        try:
            verify_site(copy)
        except ValueError as exc:
            raise BuildError(f"verify_site: {exc}") from None
    manifest = json.loads((out / "ratings/manifest.json").read_text())
    for relative, expected in manifest["files"].items():
        if digest((out / "ratings" / relative).read_bytes()) != expected:
            raise BuildError(f"ratings/manifest.json does not match {relative}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--site", default=str(ROOT / "site"))
    p.add_argument("--out", required=True)
    p.add_argument("--preview-dry-run", nargs="*", default=[])
    args = p.parse_args(argv)
    try:
        manifest = assemble(Path(args.site), Path(args.out), args.preview_dry_run)
    except BuildError as exc:
        print(f"build_ratings_page: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            dict(
                status=manifest["status"],
                preview=manifest["preview"],
                contentDigest=manifest["contentDigest"],
                files=len(manifest["files"]),
            )
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
