"""Check delivered PDFs and bind browser/export evidence to the analysis version."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/live"
pointer = json.loads((ROOT / "data/latest.json").read_text())
snapshot = json.loads((ROOT / pointer["snapshot"]).read_text())
version = snapshot["contentHash"]

for name in ["browser-verification.json", "replay-verification.json"]:
    evidence = json.loads((OUT / name).read_text())
    if evidence["status"] != "passed" or evidence["snapshotHash"] != version:
        raise ValueError(f"Stale or failed verification: {name}")

for relative, expected in {
    **snapshot["engineFiles"],
    **snapshot["renderFiles"],
}.items():
    if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
        raise ValueError(f"Code changed after the snapshot: {relative}")

reports = []
for name in [
    "universe",
    "micron",
    "sk-hynix",
    "research-us",
    "research-kr",
    "conditions",
]:
    path = OUT / f"{name}.pdf"
    doc = fitz.open(path)
    pages, urls = [], []
    for index, page in enumerate(doc):
        text = page.get_text()
        if version[:12] not in text or len(text.split()) < 50:
            raise ValueError(f"Missing version or sparse PDF page: {name} {index+1}")
        if abs(page.rect.width - 595.28) > 1 or abs(page.rect.height - 841.89) > 1:
            raise ValueError(f"Non-A4 page: {name} {index+1}")
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if not span["text"].strip():
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    if (
                        min(x0, y0) < -1
                        or x1 > page.rect.width + 1
                        or y1 > page.rect.height + 1
                    ):
                        raise ValueError(f"Clipped text: {name} {index+1}")
        urls.extend(link["uri"] for link in page.get_links() if "uri" in link)
        pages.append(dict(page=index + 1, words=len(text.split()), clipping=False))
    if name == "micron" and not any("sec.gov/Archives/" in u for u in urls):
        raise ValueError("Micron PDF lacks its primary filing link")
    if name == "sk-hynix" and not any("dart.fss.or.kr" in u for u in urls):
        raise ValueError("SK PDF lacks its primary filing link")
    reports.append(
        dict(file=str(path.relative_to(ROOT)), pages=pages, primaryLinks=urls)
    )

files = [
    OUT / f"{name}.pdf"
    for name in [
        "universe",
        "micron",
        "sk-hynix",
        "research-us",
        "research-kr",
        "conditions",
    ]
]
files += sorted(OUT.glob("desktop-*.png")) + sorted(OUT.glob("mobile-*.png"))
files += sorted(OUT.glob(version[:12] + "-*"))
record = dict(
    checkedAt=datetime.now(timezone.utc).isoformat(),
    status="passed",
    snapshotHash=version,
    method="PyMuPDF: A4, text bounds, version on every page, primary filing links; browser/replay/code version agreement",
    reports=reports,
    artifacts={
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
    },
)
(OUT / "artifact-verification.json").write_text(
    json.dumps(record, ensure_ascii=False, indent=2) + "\n"
)
print(
    f"PASS {len(reports)} PDFs / {sum(len(r['pages']) for r in reports)} pages; {len(files)} artifact hashes bound to {version[:12]}"
)
