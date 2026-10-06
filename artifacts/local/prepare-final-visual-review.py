"""Render hash-bound page contact sheets; this does not approve their appearance."""

import hashlib
import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/live"
verified = json.loads((OUT / "artifact-verification.json").read_text())
version = verified["snapshotHash"]
pages = []
pdf_hashes = {}
for report in verified["reports"]:
    relative = report["file"]
    path = ROOT / relative
    pdf_hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    with fitz.open(path) as doc:
        for index, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(.65, .65), alpha=False)
            thumb = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            pages.append((path.stem, index + 1, thumb))

sheets = []
for offset in range(0, len(pages), 16):
    sheet = Image.new("RGB", (1640, 2380), "#d8dde2")
    draw = ImageDraw.Draw(sheet)
    for local, (name, number, thumb) in enumerate(pages[offset:offset + 16]):
        x, y = (local % 4) * 410 + 10, (local // 4) * 595 + 10
        draw.text((x, y), f"{name}  p{number}  [{version[:12]}]", fill="black")
        sheet.paste(thumb, (x, y + 24))
    path = OUT / f"{version[:12]}-contact-{offset // 16 + 1}.png"
    sheet.save(path)
    sheets.append(str(path.relative_to(ROOT)))

record = dict(
    status="pending_visual_inspection",
    snapshotHash=version,
    pdfHashes=pdf_hashes,
    pdfPages=len(pages),
    contactSheets=sheets,
    pageMap=[dict(sheet=i // 16 + 1, slot=i % 16 + 1, report=n, page=p)
             for i, (n, p, _) in enumerate(pages)],
)
path = OUT / f"{version[:12]}-visual-pages.json"
path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(dict(file=str(path.relative_to(ROOT)), pages=len(pages), sheets=sheets)))
