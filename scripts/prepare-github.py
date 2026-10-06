"""Stage only reviewed project files for a new repository; no network or Git mutation."""

from pathlib import Path
import hashlib
import json
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab.publication import verify_site

site_manifest = verify_site(ROOT / "site")
output = ROOT / "deploy/repository"
if (output / ".git").exists():
    raise ValueError(
        "Do not rebuild over an initialized repository; use a separate checkout"
    )
if output.exists():
    if not (output / "PUBLICATION.json").is_file():
        raise ValueError("Refusing to replace an unrelated directory")
    shutil.rmtree(output)
output.mkdir(parents=True)

files = [
    ".gitignore",
    ".github/workflows/research-pages.yml",
    "requirements.txt",
    "requirements-verification.txt",
    "index.html",
    "prototype/styles.css",
    "data/universe.json",
    "data/ledger/conditions.jsonl",
]
for pattern in ["equitylab/*.py", "app/*.html", "app/*.css", "tests/test_*.py"]:
    files.extend(str(p.relative_to(ROOT)) for p in ROOT.glob(pattern))
files += ["app/app.js"]
files += [
    f"scripts/{name}"
    for name in [
        "cloud-refresh.py",
        "check-live.mjs",
        "check-replay.py",
        "check-artifacts.py",
        "check-site.py",
    ]
]
files += [str(p.relative_to(ROOT)) for p in (ROOT / "site").rglob("*") if p.is_file()]
for relative in files:
    dest = output / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / relative, dest)
shutil.copyfile(ROOT / "deploy/README.github.md", output / "README.md")
(output / "AGENTS.md").write_text(
    """# Equity Research

- This project runs on GitHub-hosted Actions and publishes the static `site/` folder to Pages. Do not add a required local server or self-hosted runner.
- `README.md` describes the current eight-company exploratory scope. Preserve filing dates, accounting periods, units, source hashes, missing intervals, baselines and failed hypotheses.
- Do not equate research candidates with validated investment recommendations. Keep variance loss, excess return and condition fulfillment separate.
- Do not place credentials, raw workspace dumps or private paths in `site/`. Run `python scripts/check-site.py` before publishing.
- For analysis changes run the engine tests, isolated replay, Chrome file-based checks and PDF audit before `python -m equitylab build-site`.
- Preserve `data/ledger/conditions.jsonl` as an append-only record. A local hash chain is not external timestamp certification.
- Do not use subagents unless the user explicitly requests them.
"""
)
record = {
    "targetRepository": "soccz/equity-research",
    "targetPage": site_manifest["target"],
    "status": "prepared_not_published",
    "analysisHash": site_manifest["analysisHash"],
    "files": {
        str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*"))
        if p.is_file()
    },
}
(output / "PUBLICATION.json").write_text(json.dumps(record, indent=2) + "\n")
archive = ROOT / "deploy/equity-research-ready.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
    for p in sorted(output.rglob("*")):
        if p.is_file():
            handle.write(p, p.relative_to(output))
print(
    f"Prepared {len(record['files'])} files, {archive.stat().st_size:,} bytes; no repository created or pushed"
)
