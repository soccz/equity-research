"""Build a reviewed, static Pages artifact from an analysis; never publish raw workspaces."""

import copy
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import tempfile
from urllib.parse import unquote, urlsplit
from .data import ROOT, canonical, digest

PDF_NAMES = [
    "universe",
    "micron",
    "sk-hynix",
    "research-us",
    "research-kr",
    "conditions",
]


def public_payload(payload):
    obj = copy.deepcopy(payload)
    # Private model notes are never included in the public publication projection.
    obj.pop("localReviews", None)
    obj.pop("coverageReviews", None)
    obj.pop("questionSelections", None)
    obj.pop("forwardStudy", None)
    for key in ["engineFiles", "renderFiles", "inputFiles"]:
        obj["snapshot"].pop(key, None)
    for company in obj["snapshot"]["companies"]:
        company["prices"] = company.get("prices", [])[-253:]
        company.pop("narrative", None)

    def clean(value):
        if isinstance(value, dict):
            return {
                k: clean(v)
                for k, v in value.items()
                if k not in {"file", "sourceFile", "originalPath"}
            }
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    obj = clean(obj)
    obj["publication"] = {
        "mode": "github-pages",
        "analysisHash": obj["snapshot"]["contentHash"],
        "scope": "Published analysis projection; raw originals and execution inputs are separate research archives.",
    }
    return obj


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        self.links.extend(v for k, v in attrs if k in {"href", "src"} and v)


def verify_site(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "site-manifest.json").read_text())
    actual = {str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {"site-manifest.json"}:
        raise ValueError("Unlisted or missing publication files")
    for relative, expected in manifest["files"].items():
        path = folder / relative
        if not path.resolve().is_relative_to(folder) or path.is_symlink():
            raise ValueError("Publication must not reference external workspace files")
        if digest(path.read_bytes()) != expected:
            raise ValueError(f"Publication hash mismatch: {relative}")
        if path.suffix in {".html", ".js", ".json", ".css", ".svg"}:
            body = path.read_text()
            if any(
                x in body
                for x in [
                    '"/api/',
                    "'/api/",
                    "`/api/",
                    "127.0.0.1",
                    "localhost:",
                    "/home/soccz",
                    "/mnt/20t",
                    "crtfc_key=",
                    "DART_API_KEY",
                ]
            ):
                raise ValueError(
                    f"Backend, local path or credential reference in publication: {relative}"
                )
        if path.suffix == ".html":
            parser = References()
            parser.feed(path.read_text())
            for link in parser.links:
                parsed = urlsplit(link)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                if parsed.path.startswith("/"):
                    raise ValueError(
                        f"Root-relative asset is incompatible with project Pages: {link}"
                    )
                target = (path.parent / unquote(parsed.path)).resolve()
                if not target.is_relative_to(folder) or not target.is_file():
                    raise ValueError(f"Broken publication link: {relative} → {link}")
    return manifest


def build_site():
    from .pipeline import load_latest

    snapshot = load_latest()
    from .local_ai import read_reviews
    from . import coverage_reasoning
    from .questions import read as read_questions

    if (
        any(
            c.get("narrative", {}).get("status") == "ready"
            for c in snapshot["companies"]
        )
        or read_reviews(snapshot)
        or read_reviews(
            snapshot, protocol=coverage_reasoning, archive_name="coverage-reviews"
        )
        or read_questions(snapshot)
    ):
        raise ValueError(
            "Private local analysis is present; public site export is disabled to protect model notes and rendered PDFs"
        )
    version = snapshot["contentHash"]
    proofs = {}
    for name in ["browser", "replay", "artifact"]:
        record = json.loads(
            (ROOT / f"artifacts/live/{name}-verification.json").read_text()
        )
        if record.get("status") != "passed" or record.get("snapshotHash") != version:
            raise ValueError(f"Current {name} verification required before publication")
        proofs[name] = dict(status="passed", checkedAt=record["checkedAt"])
    for relative, expected in {
        **snapshot["engineFiles"],
        **snapshot["renderFiles"],
    }.items():
        if digest((ROOT / relative).read_bytes()) != expected:
            raise ValueError(f"Code changed after verification: {relative}")
    js = (ROOT / "app/snapshot.js").read_text()
    payload = json.loads(
        js.removeprefix("window.EQUITY_SNAPSHOT = ").strip().removesuffix(";")
    )
    if payload["snapshot"]["contentHash"] != version:
        raise ValueError("Screen and analysis version mismatch")
    for company in payload["snapshot"]["companies"]:
        for source in company["sources"]:
            if digest((ROOT / source["file"]).read_bytes()) != source["sha256"]:
                raise ValueError("Source changed after verification")
    cache = ROOT / "data/cache"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pages-build-", dir=cache) as tmp:
        staging = Path(tmp) / "site"
        staging.mkdir()
        assets = [
            "index.html",
            "app/index.html",
            "app/about.html",
            "app/app.js",
            "app/dossier.js",
            "app/styles.css",
            "prototype/styles.css",
        ]
        assets.extend(f"artifacts/live/{name}.pdf" for name in PDF_NAMES)
        assets.extend(
            str(p.relative_to(ROOT))
            for p in (ROOT / "artifacts/live").glob(version[:12] + "-*.svg")
        )
        for relative in assets:
            dest = staging / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, dest)
        public = public_payload(payload)
        (staging / "app/snapshot.js").write_text(
            "window.EQUITY_SNAPSHOT = "
            + json.dumps(public, ensure_ascii=False, allow_nan=False).replace(
                "</", "<\\/"
            )
            + ";\n"
        )
        (staging / ".nojekyll").write_text("")
        (staging / ".generated-site").write_text("equitylab-publication-v1\n")
        manifest = dict(
            schemaVersion=1,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            analysisHash=version,
            asOf=snapshot["asOf"],
            target="https://soccz.github.io/equity-research/",
            verification=proofs,
            files={
                str(p.relative_to(staging)): digest(p.read_bytes())
                for p in sorted(staging.rglob("*"))
                if p.is_file()
            },
        )
        (staging / "site-manifest.json").write_bytes(canonical(manifest))
        verify_site(staging)
        output, previous = ROOT / "site", ROOT / "data/cache/previous-site"
        if output.exists() and not (output / ".generated-site").is_file():
            raise ValueError("Refusing to replace a site not generated by this builder")
        if previous.exists():
            raise ValueError("Previous publication recovery directory exists")
        if output.exists():
            output.rename(previous)
        try:
            staging.rename(output)
        except Exception:
            if previous.exists():
                previous.rename(output)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    return manifest
