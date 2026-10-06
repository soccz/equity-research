"""Filing-bound text evidence. Retrieval is not financial interpretation."""

from html.parser import HTMLParser
import json
import re
from .data import ROOT, canonical, digest, read_verified

VERSION = "filing-passages-v1"


class Passages(HTMLParser):
    """Keep paragraph and table-row boundaries without executing filed markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.parts, self.stack = [], [], []
        self.table_depth = 0
        self.heading = ""
        self.kind = "paragraph"

    def flush(self):
        text = re.sub(r"\s+", " ", "".join(self.parts)).strip(" |\t\n")
        self.parts = []
        if not text:
            return
        kind = "table" if self.table_depth else self.kind
        if kind == "heading":
            self.heading = text
        if len(text) >= 30 and not re.fullmatch(r"[\d\s.,()$%−+|—-]+", text):
            self.rows.append(dict(text=text, heading=self.heading, kind=kind))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden = tag in {"script", "style", "head", "ix:hidden", "ix:header"} or (
            "display:none" in attrs.get("style", "").replace(" ", "").lower()
        )
        if tag not in {"br", "hr", "img", "meta", "link", "input", "col", "wbr"}:
            self.stack.append((tag, hidden or bool(self.stack and self.stack[-1][1])))
        if (self.stack and self.stack[-1][1]) or hidden:
            return
        if tag == "table":
            self.flush()
            self.table_depth += 1
        if tag in {"p", "div", "tr", "title", "h1", "h2", "h3", "h4"}:
            if not self.table_depth or tag == "tr":
                self.flush()
            self.kind = (
                "heading" if tag in {"title", "h1", "h2", "h3", "h4"} else "paragraph"
            )
        if tag in {"td", "th"}:
            self.parts.append(" | ")
        if tag == "br":
            self.parts.append(" ")

    def handle_endtag(self, tag):
        hidden = bool(self.stack and self.stack[-1][1])
        if not hidden:
            if tag in {"p", "div", "tr", "title", "h1", "h2", "h3", "h4"}:
                if not self.table_depth or tag == "tr":
                    self.flush()
            if tag == "table":
                self.flush()
                self.table_depth = max(0, self.table_depth - 1)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, text):
        if not self.stack or not self.stack[-1][1]:
            self.parts.append(text)


def extract(blob):
    encoding = re.search(rb'encoding=["\']([^"\']+)', blob[:150])
    text = blob.decode(encoding[1].decode() if encoding else "utf-8")
    parser = Passages()
    parser.feed(text)
    parser.close()
    parser.flush()
    # Repeated navigation/table labels are kept only once; numerical source rows
    # remain in the original filing even when omitted by the text-only index.
    seen, rows = set(), []
    for row in parser.rows:
        if row["text"] in seen:
            continue
        seen.add(row["text"])
        row["ordinal"] = len(rows)
        row["id"] = digest(canonical(row))[:20]
        rows.append(row)
    return rows


def build(company, as_of):
    path = ROOT / "data/narratives.json"
    if not path.exists():
        return dict(status="missing", reason="현재 공시 본문 수집 전")
    record = next(
        (
            r
            for r in json.loads(path.read_text())["results"]
            if r["company"] == company["id"]
        ),
        None,
    )
    core = company["financials"]["current"]["cfo"]
    if not record or record["status"] != "archived":
        return dict(status="missing", reason="현재 공시 본문 수집 실패 또는 미수집")
    if record["accession"] != core["accession"]:
        return dict(status="stale", reason="공시 접수 변경: 새 본문 수집 필요")
    if record["filedAt"] != core["filedAt"] or record["filedAt"] > as_of:
        raise ValueError("Narrative filing date mismatch")
    passages = []
    for source in record["sources"]:
        blob = read_verified(ROOT / source["file"], source["sha256"])
        if not any(s["file"] == source["file"] for s in company["sources"]):
            company["sources"].append(source)
        passages.extend(
            dict(
                **row,
                sourceHash=source["sha256"],
                sourceFile=source["file"],
                sourceUrl=source["url"],
            )
            for row in extract(blob)
        )
    body = dict(
        version=VERSION,
        company=company["id"],
        accession=record["accession"],
        filedAt=record["filedAt"],
        period=record["period"],
        passages=passages,
    )
    sha = digest(canonical(body))
    script = b"window.EquityNotebook.receive(" + canonical(body) + b");\n"
    target = ROOT / f"app/filings/{company['id']}-{sha[:16]}.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        read_verified(target, digest(script))
    else:
        target.write_bytes(script)
    return dict(
        status="ready",
        version=VERSION,
        company=company["id"],
        accession=record["accession"],
        filedAt=record["filedAt"],
        period=record["period"],
        passageCount=len(passages),
        file=str(target.relative_to(ROOT)),
        sha256=digest(script),
        evidenceHash=sha,
        scope="현재 공시 본문의 문단·표행 색인. 경영진 설명은 검증된 원인과 구분하며 표행은 원문 머리글·단위를 함께 확인한다.",
    )


def load(company):
    meta = company.get("narrative") or {}
    if meta.get("status") != "ready":
        return None
    raw = read_verified(ROOT / meta["file"], meta["sha256"])
    body = json.loads(raw[len(b"window.EquityNotebook.receive(") : -3])
    if digest(canonical(body)) != meta["evidenceHash"]:
        raise ValueError("Narrative corpus content mismatch")
    return body
