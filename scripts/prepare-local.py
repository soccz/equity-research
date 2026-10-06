"""Package the private research workspace with provenance, without models or keys."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab.pipeline import load_latest


def files():
    roots = [
        ROOT / name
        for name in (
            "local.html",
            "start.py",
            "README.md",
            "requirements.txt",
            "requirements-offline.lock",
            "requirements-verification.txt",
            "equitylab",
            "app",
            "docs",
            "scripts",
            "tests",
            "prototype/styles.css",
            "data/sources",
            "data/runs",
            "data/ledger",
            "data/evaluation",
            "data/local-reviews",
            "data/local-evaluations",
            "data/coverage-reviews",
            "data/coverage-evaluations",
            "data/coverage-transfer-evaluations",
            "data/question-selections",
            "data/filing-readings",
            "artifacts/live",
            "artifacts/local",
        )
    ]
    roots.extend((ROOT / "data").glob("*.json"))
    selected = set()
    for root in roots:
        for p in root.rglob("*") if root.is_dir() else [root]:
            if not p.is_file() or p.is_symlink():
                continue
            relative = p.relative_to(ROOT)
            if any(x.startswith(".") or x == "__pycache__" for x in relative.parts):
                continue
            if p.suffix in (".pyc", ".tmp", ".partial"):
                continue
            if p.suffix == ".lock" and relative != Path("requirements-offline.lock"):
                continue
            selected.add(p)
    return sorted(selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    snapshot = load_latest()
    selected = files()
    if args.check_only:
        print(
            f"Private package: {len(selected)} files, {sum(p.stat().st_size for p in selected)/1e6:.1f} MB before compression; models/runtime/keys excluded"
        )
        return
    # Build only from a completed, current rendering of the current analysis.
    verification = ROOT / "artifacts/live/artifact-verification.json"
    if not verification.exists():
        raise ValueError("Run the artifact verification before packaging")
    checked = json.loads(verification.read_text())
    if (
        checked.get("status") != "passed"
        or checked.get("snapshotHash") != snapshot["contentHash"]
    ):
        raise ValueError("The current snapshot needs completed artifact verification")
    subprocess.run([sys.executable, "scripts/check-artifacts.py"], cwd=ROOT, check=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "artifacts/packages" / f"equity-local-{stamp}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = dict(
        createdAt=datetime.now(timezone.utc).isoformat(),
        snapshotHash=snapshot["contentHash"],
        private=True,
        published=False,
        files={},
        scope="Code, public filing/price originals, private model responses, evaluations, ledgers and reports. Model weights, Ollama binaries, credentials, original external projects and public deployment checkout are excluded.",
    )
    with zipfile.ZipFile(
        out, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=3
    ) as archive:
        for p in selected:
            relative = str(p.relative_to(ROOT))
            blob = p.read_bytes()
            manifest["files"][relative] = dict(
                size=len(blob), sha256=hashlib.sha256(blob).hexdigest()
            )
            archive.writestr(relative, blob)
        archive.writestr(
            "LOCAL-BUNDLE-MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    with zipfile.ZipFile(out) as archive, tempfile.TemporaryDirectory(
        prefix="equity-package-", dir=ROOT / "data/cache/tmp"
    ) as temp:
        if archive.testzip() is not None:
            raise ValueError("Private archive CRC failure")
        archive.extractall(temp)
        for relative, evidence in manifest["files"].items():
            path = Path(temp) / relative
            with path.open("rb") as handle:
                if (
                    hashlib.file_digest(handle, "sha256").hexdigest()
                    != evidence["sha256"]
                ):
                    raise ValueError("Extracted file hash mismatch: " + relative)
        subprocess.run([sys.executable, "start.py", "status"], cwd=temp, check=True)
        subprocess.run(
            [sys.executable, "scripts/check-replay.py"], cwd=temp, check=True
        )
    with out.open("rb") as handle:
        archive_hash = hashlib.file_digest(handle, "sha256").hexdigest()
    result = dict(
        file=str(out.relative_to(ROOT)),
        sha256=archive_hash,
        snapshotHash=snapshot["contentHash"],
        size=out.stat().st_size,
        files=len(manifest["files"]),
        status="verified_private_archive",
        verification="ZIP CRC, all extracted SHA256 hashes, relocated start.py status, isolated offline source replay",
    )
    out.with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
