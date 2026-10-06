"""Preserve a DART document package for correction-scope inspection."""

import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab.data import canonical, digest
from equitylab.dart import load_key_file, request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--receipt", required=True)
    p.add_argument("--dart-env")
    args = p.parse_args()
    if not re.fullmatch(r"\d{14}", args.receipt):
        p.error("Invalid DART receipt")
    if args.dart_env:
        load_key_file(args.dart_env)
    body = request("document.xml", {"rcept_no": args.receipt})
    if not body.startswith(b"PK"):
        raise ValueError("DART document is unavailable")
    sha = digest(body)
    root = ROOT / "data/sources"
    package = root / f"dart-document-{args.receipt}-{sha[:16]}.zip"
    package.write_bytes(body)
    files = []
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        if sum(e.file_size for e in archive.infolist()) > 80_000_000:
            raise ValueError("Document unpacked size limit")
        for i, entry in enumerate(archive.infolist()):
            if not entry.filename.lower().endswith((".xml", ".html", ".htm")):
                continue
            raw = archive.read(entry)
            hash_ = digest(raw)
            path = root / f"dart-document-{args.receipt}-{i}-{hash_[:16]}.xml"
            path.write_bytes(raw)
            files.append(
                dict(
                    file=str(path.relative_to(ROOT)),
                    sha256=hash_,
                    originalName=entry.filename,
                )
            )
    manifest = dict(
        receipt=args.receipt,
        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={args.receipt}",
        retrievedAt=datetime.now(timezone.utc).isoformat(),
        package=dict(file=str(package.relative_to(ROOT)), sha256=sha),
        files=files,
    )
    (root / f"dart-document-{args.receipt}.manifest.json").write_bytes(
        canonical(manifest)
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
