"""Evidence-bound exception for an attachment correction, never a generic fallback."""

from html.parser import HTMLParser
import json
from .data import ROOT, read_verified


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def notes(company, as_of):
    path = ROOT / "data/dart-corrections.json"
    if not path.exists():
        return []
    result = []
    for row in json.loads(path.read_text()):
        if row["company"] != company["id"] or row["filedAt"] > as_of:
            continue
        # The supplied evidence supports this exact attachment, not every amendment.
        if (row["company"], row["receipt"], row["originalReceipt"]) != (
            "012450",
            "20260319000633",
            "20260316001112",
        ):
            raise ValueError("Unreviewed DART correction scope")
        index, scope = [
            read_verified(ROOT / s["file"], s["sha256"]).decode()
            for s in row["sources"]
        ]
        parser = Text()
        parser.feed(scope)
        text = "".join("".join(parser.parts).split())
        if not all(
            anchor in text
            for anchor in [
                "정정대상공시서류:영업보고서",
                "영업보고서수정에따른정정신고",
                "4.기업결합사항",
                "이사회결의서",
            ]
        ):
            raise ValueError("DART correction scope anchors changed")
        if (
            "rcpNo=" + row["originalReceipt"] not in index
            or row["receipt"] not in index
        ):
            raise ValueError("DART original/correction link is missing")
        result.append(row)
    return result
