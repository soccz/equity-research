"""Verify a reported table caption against the exact inline XBRL fact."""

from html.parser import HTMLParser
import json
from .data import ROOT, read_verified


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.stack, self.contexts, self.units = [], [], {}, {}
        self.context = self.unit = self.field = self.number = None

    def handle_starttag(self, tag, attributes):
        a = dict(attributes)
        local = tag.split(":")[-1]
        if local == "context":
            self.context = dict(id=a["id"], start=None, end=None)
        elif local == "unit":
            self.unit = a["id"]
        elif local in ("startdate", "enddate", "instant", "measure"):
            self.field = [local, []]
        if tag == "tr":
            self.stack.append(dict(parts=[], facts=[]))
        if (
            tag == "ix:nonfraction"
            and a.get("name")
            == "us-gaap:PaymentsToAcquireOtherPropertyPlantAndEquipment"
        ):
            self.number = dict(attributes=a, parts=[])

    def handle_data(self, text):
        if self.field:
            self.field[1].append(text)
        for row in self.stack:
            row["parts"].append(text)
        if self.number is not None:
            self.number["parts"].append(text)

    def handle_endtag(self, tag):
        local = tag.split(":")[-1]
        if self.field and local == self.field[0]:
            text = "".join(self.field[1]).strip()
            if local == "measure" and self.unit:
                self.units[self.unit] = text.split(":")[-1]
            elif self.context:
                self.context["start" if local == "startdate" else "end"] = text
            self.field = None
        if local == "context" and self.context:
            self.contexts[self.context["id"]] = self.context
            self.context = None
        elif local == "unit":
            self.unit = None
        if tag == "ix:nonfraction" and self.number is not None:
            a = self.number["attributes"]
            v = float("".join(self.number["parts"]).replace(",", "")) * 10 ** int(
                a.get("scale", 0)
            )
            if a.get("sign") == "-":
                v = -v
            for row in self.stack:
                row["facts"].append(
                    dict(
                        value=v,
                        context=a["contextref"],
                        unit=a["unitref"],
                        tag=a["name"],
                    )
                )
            self.number = None
        if tag == "tr" and self.stack:
            row = self.stack.pop()
            row["text"] = " ".join(" ".join(row.pop("parts")).split())
            self.rows.append(row)


def verify_caption(html, fact, caption):
    parser = Tables()
    parser.feed(html)
    for row in sorted(parser.rows, key=lambda r: len(r["text"])):
        if not row["text"].startswith(caption):
            continue
        for found in row["facts"]:
            period = parser.contexts.get(found["context"], {})
            if (
                found["tag"] == fact["tag"]
                and found["value"] == fact["value"]
                and (period.get("start"), period.get("end"))
                == (fact["start"], fact["end"])
                and parser.units.get(found["unit"]) == fact["unit"]
            ):
                return dict(
                    caption=caption,
                    context=found["context"],
                    tag=found["tag"],
                    start=fact["start"],
                    end=fact["end"],
                    value=fact["value"],
                    unit=fact["unit"],
                )
    raise ValueError(
        "Reported caption does not match the selected XBRL amount and period"
    )


def investment_definition(company):
    if company["id"] != "LLY":
        return None
    fact = company["financials"]["current"]["capex"]
    path = ROOT / f"data/sources/filing-{fact['accession']}.manifest.json"
    if not path.exists():
        return None
    source = json.loads(path.read_text())
    if source["cik"] != company["cik"] or source["accession"] != fact["accession"]:
        raise ValueError("Investment caption issuer mismatch")
    evidence = verify_caption(
        read_verified(ROOT / source["file"], source["sha256"]).decode(),
        fact,
        "Purchases of property and equipment",
    )
    if source["file"] not in {s["file"] for s in company["sources"]}:
        company["sources"].append(source)
    return dict(
        status="reported_caption_verified",
        source=source,
        evidence=evidence,
        explanation="원 보고서 현금흐름표의 ‘유형자산 취득’ 표제와 선택한 금액·기간·USD 단위를 대조했다. Other 분류의 표준 태그를 사용하지만 일부 투자라는 판단은 태그명만으로 내리지 않는다. 인수·연구개발 취득 등 별도 투자지출은 이 항목에 포함되지 않는다.",
    )
