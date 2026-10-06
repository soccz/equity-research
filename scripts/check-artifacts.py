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
payload_bytes = (ROOT / "app/snapshot.js").read_bytes()
payload_hash = hashlib.sha256(payload_bytes).hexdigest()
payload = json.loads(
    payload_bytes.decode().removeprefix("window.EQUITY_SNAPSHOT = ").rstrip(";\n")
)
review_hashes = {
    k: r.get("recordHash", r["status"])
    for k, r in payload.get("localReviews", {}).items()
}
coverage_hashes = {
    k: r.get("recordHash", r["status"])
    for k, r in payload.get("coverageReviews", {}).items()
}
question_hashes = {
    k: r.get("recordHash", r["status"])
    for k, r in payload.get("questionSelections", {}).items()
}

for name in ["browser-verification.json", "replay-verification.json"]:
    evidence = json.loads((OUT / name).read_text())
    if evidence["status"] != "passed" or evidence["snapshotHash"] != version:
        raise ValueError(f"Stale or failed verification: {name}")
    if name == "browser-verification.json" and (
        evidence.get("renderedPayloadHash") != payload_hash
        or evidence.get("localReviewHashes") != review_hashes
        or evidence.get("coverageReviewHashes") != coverage_hashes
        or evidence.get("questionSelectionHashes") != question_hashes
    ):
        raise ValueError("Rendered local reviews changed after PDF generation")

for relative, expected in {
    **snapshot["engineFiles"],
    **snapshot["renderFiles"],
}.items():
    if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
        raise ValueError(f"Code changed after the snapshot: {relative}")

for company in snapshot["companies"]:
    corpus = company.get("narrative", {})
    if corpus.get("status") == "ready" and (
        hashlib.sha256((ROOT / corpus["file"]).read_bytes()).hexdigest()
        != corpus["sha256"]
    ):
        raise ValueError("Local filing corpus changed: " + company["id"])

model_table_labels = {
    "".join((c["operatingModel"].get("groupLabel") or "공시 사업부").split())
    for c in snapshot["companies"]
    if (c.get("operatingModel") or {}).get("status") == "research_workspace"
}
reports = []
for name in [
    "universe",
    "micron",
    "sk-hynix",
    "microsoft",
    "amazon",
    "kia",
    "tesla",
    "apple",
    "nvidia",
    "amd",
    "samsung-electronics",
    "broadcom",
    "mobis",
    "naver",
    "celltrion",
    "jnj",
    "samsung-sds",
    "servicenow",
    "comparison-biosimilar",
    "comparison-platforms",
    "comparison-auto-supply",
    "lam",
    "applied",
    "comparison-ai-financing",
    "alphabet",
    "meta",
    "comparison-advertising",
    "comparison-memory",
    "comparison-accelerators",
    "comparison-electronics",
    "comparison-auto",
    "comparison-cloud",
    "comparison-equipment",
    "intel",
    "qualcomm",
    "oracle",
    "costco",
    "orion",
    "analog-devices",
    "comparison-analog",
    "texas-instruments",
    "adobe",
    "salesforce",
    "comparison-software",
    "lg-innotek",
    "kt",
    "netflix",
    "comparison-enterprise",
    "comparison-infrastructure",
    "hyundai",
    "samsung-biologics",
    "samsung-electromechanics",
    "research-us",
    "research-kr",
    "conditions",
]:
    path = OUT / f"{name}.pdf"
    doc = fitz.open(path)
    pages, urls = [], []
    for index, page in enumerate(doc):
        text = page.get_text()
        compact_text = "".join(text.split())
        if (
            name in {"intel", "qualcomm"}
            and any(
                title in compact_text
                for title in [
                    "자동차·IoT증가에도QCT전체매출은감소",
                    "자동차증가분을가격·구성과출하로분해",
                    "파운드리적자축소중제품수익의기여는음수",
                ]
            )
            and "백만달러" not in compact_text
        ):
            raise ValueError(f"Business driver chart unit missing: {name} {index+1}")
        if (
            "LOCALCOMPANYRESEARCH" in compact_text
            and "공시에서출발한기업연구질문" not in compact_text
        ):
            raise ValueError(
                f"Local review label separated from heading: {name} {index+1}"
            )
        if (
            "미국·한국메모리기업을같은질문으로보기" in compact_text
            and "누적기간" not in compact_text
        ):
            raise ValueError(
                f"Comparison heading separated from its table: {name} {index+1}"
            )
        for label, heading in [
            ("CASHASSUMPTIONS/EQUITYSCENARIOS", "어떤현금·재투자조건"),
            ("BUSINESSDRIVERS/CASHPATH", "사업의성장과마진"),
        ]:
            if label in compact_text and heading not in compact_text:
                raise ValueError(
                    f"Valuation eyebrow separated from heading: {name} {index+1}"
                )
        if (
            "LOCALMODEL/RESEARCHPRIORITIES" in compact_text
            and "정해진연구설계중두가지" in compact_text
            and "조사순서1" not in compact_text
        ):
            raise ValueError(
                f"Research-priority heading separated from first question: {name} {index+1}"
            )
        if "BUSINESSDRIVERS/CASHPATH" in compact_text and not any(
            label in compact_text for label in model_table_labels
        ):
            raise ValueError(
                f"Operating model heading separated from first table: {name} {index+1}"
            )
        if (
            "BUSINESS/TRAILINGYEAR" in compact_text
            and "최근1년영업이익" not in compact_text
        ):
            raise ValueError(
                f"Segment period heading separated from first table: {name} {index+1}"
            )
        if version[:12] not in text or len(text.split()) < 50:
            raise ValueError(f"Missing version or sparse PDF page: {name} {index+1}")
        if abs(page.rect.width - 595.28) > 1 or abs(page.rect.height - 841.89) > 1:
            raise ValueError(f"Non-A4 page: {name} {index+1}")
        text_blocks = page.get_text("dict")["blocks"]
        lines = [line for block in text_blocks for line in block.get("lines", [])]
        footer_lines = [
            line
            for line in lines
            if "주식 연구실 · 자료" in "".join(s["text"] for s in line["spans"])
        ]
        if len(footer_lines) != 1:
            raise ValueError(f"Missing or repeated version footer: {name} {index+1}")
        footer_top = footer_lines[0]["bbox"][1]
        for line in lines:
            if line is not footer_lines[0] and line["bbox"][3] > footer_top - 1:
                raise ValueError(f"Body overlaps version footer: {name} {index+1}")
        for block in text_blocks:
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
    if name in {
        "micron",
        "microsoft",
        "amazon",
        "tesla",
        "apple",
        "nvidia",
        "amd",
        "alphabet",
        "meta",
        "broadcom",
        "lam",
        "applied",
        "comparison-ai-financing",
        "comparison-platforms",
        "comparison-advertising",
        "comparison-memory",
        "comparison-accelerators",
        "comparison-electronics",
        "oracle",
        "costco",
        "analog-devices",
        "comparison-analog",
        "texas-instruments",
        "adobe",
        "salesforce",
        "comparison-software",
        "jnj",
        "comparison-biosimilar",
        "netflix",
        "comparison-enterprise",
        "comparison-auto",
        "comparison-cloud",
        "comparison-equipment",
        "intel",
        "qualcomm",
    } and not any("sec.gov/Archives/" in u for u in urls):
        raise ValueError(f"{name} PDF lacks its primary SEC filing link")
    if name in {
        "sk-hynix",
        "orion",
        "lg-innotek",
        "celltrion",
        "comparison-biosimilar",
        "naver",
        "comparison-platforms",
        "mobis",
        "comparison-auto-supply",
        "samsung-electronics",
        "comparison-electronics",
        "kt",
        "comparison-enterprise",
        "hyundai",
        "kia",
        "samsung-biologics",
        "comparison-auto",
        "comparison-memory",
    } and not any("dart.fss.or.kr" in u for u in urls):
        raise ValueError(f"{name} PDF lacks its primary DART filing link")
    if name in {
        "comparison-auto",
        "comparison-cloud",
        "comparison-memory",
        "comparison-accelerators",
        "comparison-electronics",
        "comparison-equipment",
        "comparison-ai-financing",
        "comparison-platforms",
        "comparison-auto-supply",
    }:
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        required = ["요구수익률", "영구매출성장률", "나의비교의견", "가장강한반론"]
        if name == "comparison-auto":
            required += ["5년차보증사용", "1년차연구개발", "매출총이익률"]
        if any(term not in all_text for term in required):
            raise ValueError(
                f"Selected business assumptions or comparison notes missing: {name}"
            )
    if name == "jnj":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        if any(
            term not in all_text
            for term in [
                "부문세전이익률",
                "미배분비용차감후세전이익",
                "기업인수순현금",
                "취득진행중연구개발",
                "이자가이미",
                "자료미확인",
                "세율25%",
            ]
        ):
            raise ValueError("JNJ PDF lost pretax, investment or missing-payment scope")
    if name == "celltrion":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        required = [
            "이자지급은재무활동",
            "공급자금융",
            "현금순변동",
            "-796원",
            "60일",
            "180일",
            "손상누계",
            "순장부",
            "내부거래조정전",
            "임상단계",
        ]
        if any(term not in all_text for term in required):
            raise ValueError(
                "Celltrion PDF lost cash classification or development evidence"
            )
    if name == "samsung-electromechanics":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "원문안의부호불일치",
            "선택보류",
            "-2,881,532",
            "+2,881,532",
            "-475,808",
            "+475,808",
            "-556,263",
            "+556,263",
            "577,306",
            "548,806",
            "28,826",
            "천원",
            "20260310003071",
            "20260814003805",
        ]:
            if term not in all_text:
                raise ValueError(
                    "Electromechanics conflicting source evidence missing: " + term
                )
    if name == "oracle":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "고객의선급금융과설비자금소요",
            "11.363",
            "11.74",
            "75.66",
            "0.552",
            "0.357",
            "0.195",
            "288",
            "200%",
            "원금대용",
            "미배분비용",
        ]:
            if term not in all_text:
                raise ValueError("Oracle financing evidence missing: " + term)
    if name == "costco":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["회원비는이미사업손익에포함된기간수익", "7~18개월", "-2.352", "3.157", "금융리스", "자료미확인", "재보험", "0.102"]:
            if term not in all_text:
                raise ValueError("Costco membership/lease scope missing: " + term)
    if name == "orion":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "같은반기의지역매출과연결이익을구분",
            "134원",
            "272원",
            "-174,000",
            "인수현금174,000원",
            "2026-07-24",
            "전환우선주",
            "전환사채",
            "주당·역산은보류",
            "0.685",
        ]:
            if term not in all_text:
                raise ValueError("Orion business/capital scope missing: " + term)
    if name == "analog-devices":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "최종시장매출과공시단일부문이익을구별",
            "산업",
            "통신",
            "-0.941",
            "24.2",
            "24.4",
            "1,592.044",
            "시장별이익률은미공시",
            "3.639",
        ]:
            if term not in all_text:
                raise ValueError("ADI market/cash scope missing: " + term)
    if name == "comparison-analog":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["CHIPS", "Empower", "2026-06-30", "2026-08-01", "재투자", "8%"]:
            if term not in all_text:
                raise ValueError("Analog comparison assumption/source missing: " + term)
    if name == "texas-instruments":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "세금혜택과투자지원금을한번씩만연결",
            "8.667",
            "6.534",
            "4.922",
            "0.433",
            "1.179",
            "0.353",
            "6.445",
            "2025-12-31",
            "이미포함된세금혜택",
            "이중계산",
        ]:
            if term not in all_text:
                raise ValueError("TI incentive cash evidence missing: " + term)
    if name == "salesforce":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "투자손익과구독사업의현금을분리",
            "3.171",
            "584",
            "367",
            "217",
            "612",
            "574",
            "4.24%",
            "1.824275",
            "미사용",
            "2.17억",
        ]:
            if term not in all_text:
                raise ValueError("Salesforce financing scope evidence missing: " + term)
    if name == "comparison-software":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["계약취득비", "금융의무", "2.17억", "12%", "ARR"]:
            if term not in all_text:
                raise ValueError("Software cash comparison evidence missing: " + term)
    if name == "adobe":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "보고부문통합뒤에도원가와공통비용을구분",
            "22.904",
            "9.271",
            "236",
            "282",
            "828",
            "818",
            "차이원인미배분",
            "1.8439%",
            "계약취득비순자산",
            "Semrush",
            "장기투자·무형·기타자산취득의기간연결보류",
            "134",
            "216",
            "지출로채택보류",
            "0.4045%",
        ]:
            if term not in all_text:
                raise ValueError("Adobe contract-cost evidence missing: " + term)
    if name == "lg-innotek":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "매출·이익증가와현금감소를함께대사",
            "878.81",
            "398.042",
            "812.372",
            "8,841,475",
            "8,888,208",
            "46,733",
            "27,237",
            "차이는1백만원",
            "비중선택보류",
            "모빌리티솔루션",
        ]:
            if term not in all_text:
                raise ValueError("Innotek manufacturing evidence missing: " + term)
    if name == "comparison-infrastructure":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["정부소유", "우선주", "전환사채", "150%", "재투자"]:
            if term not in all_text:
                raise ValueError("Infrastructure comparison evidence missing: " + term)
    if name == "netflix":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "콘텐츠비용인식과지급은다르다",
            "19.608",
            "17.296",
            "4.234",
            "25.107",
            "5.492",
            "19.615",
            "0.729",
            "Trade receivables".replace(" ", ""),
            "콘텐츠지급/매출",
            "설비·인수현금",
            "미확정의무",
        ]:
            if term not in all_text:
                raise ValueError("Netflix content/cash evidence missing: " + term)
    if name == "qualcomm":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "11.212",
            "9.538",
            "9.53",
            "0.008",
            "세전이익률",
            "QSI운영비",
            "-4.136",
            "-5.55",
            "0.143",
            "비보고사업",
            "기타채권",
        ]:
            if term not in all_text:
                raise ValueError("Qualcomm pretax and tax scope missing: " + term)
    if name == "servicenow":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "판매수수료",
            "0.668",
            "0.843",
            "9.784",
            "-5.213",
            "312.23",
            "81일",
            "단일영업부문",
            "매출총이익률",
            "판매·마케팅비",
            "유효금리",
            "4.25%",
            "3.98%",
        ]:
            if term not in all_text:
                raise ValueError("ServiceNow cash scope missing: " + term)
    if name == "comparison-enterprise":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "판매수수료",
            "전환사채",
            "매출총이익률",
            "내부매출제거",
            "5년차설비·무형·인수·판매수수료현금/매출10%",
        ]:
            if term not in all_text:
                raise ValueError("Enterprise cash comparison missing: " + term)
    if name == "samsung-sds":
        capital_text = "".join("".join(p.get_text().split()) for p in doc)
        for required in [
            "6,777,777",
            "180,000",
            "전환사채",
            "2032-04-30",
            "연2.5%",
            "주당가격계산을보류",
            "기한이익상실",
            "123.7",
            "계약자산은미수금의하위항목",
            "정부소유GPU",
            "현금전환주기",
        ]:
            if required not in capital_text:
                raise ValueError("SDS convertible source scope missing: " + required)
    if name == "intel" and any(
        t not in "".join("".join(p.get_text().split()) for p in doc)
        for t in ["241,000,000", "에스크로", "순현금또는순주식"]
    ):
        raise ValueError("Intel conditional capital claims missing from PDF")
    if name == "comparison-biosimilar":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        if any(
            term not in all_text
            for term in [
                "STELARA",
                "공급자금융",
                "개발비",
                "-1.882",
                "+3.078",
                "세전이익",
                "미국발수출",
                "현재1백만",
                "14.458",
                "손실상한",
            ]
        ):
            raise ValueError(
                "Biosimilar comparison lost its source-specific cash scope"
            )
    if name == "naver":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        required = [
            "단일공시영업부문",
            "사업현금밖에남은투자자산",
            "AHoldings",
            "기타증감",
            "투자자산가치미평가",
            "지배주주귀속",
            "고객자금",
            "1,392,000,000JPY",
            "9,000,000CAD",
            "반기세부조정은미확인",
            "비지배배분",
        ]
        if any(term not in all_text for term in required):
            raise ValueError(
                "NAVER PDF lost customer-fund or accounting-period evidence"
            )
    if name in {"broadcom", "lam", "applied"}:
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        terms = {
            "broadcom": ["일회성순지급", "1년차말", "3년차말", "5년차말", "42", "회수"],
            "lam": [
                "보증순발생",
                "비배분기타매출원가",
                "기존추정변경",
                "0.265",
                "0.251",
                "0.29",
            ],
            "applied": ["재작성영업이익", "20.798", "21.441", "5.742", "자료미확인"],
        }[name]
        if any(term not in all_text for term in terms):
            raise ValueError(f"Issuer-specific operating evidence missing: {name}")
        if name == "applied" and not any(
            "50913916-d1d0-4eff-bb18-67c4886343d0" in u and "page=23" in u for u in urls
        ):
            raise ValueError(
                "Applied recast PDF lacks the issuer's page 23 source link"
            )
    if name in {
        "kia",
        "microsoft",
        "broadcom",
        "lam",
        "applied",
        "samsung-electronics",
        "mobis",
    }:
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        if name in {"samsung-electronics", "mobis"}:
            required_inverse = ["역산하지않습니다", "사업현금경로"]
        else:
            required_inverse = ["가격일치마진", "탐색범위", "동시에적용하지"]
        if any(term not in all_text for term in required_inverse):
            raise ValueError(f"Business-margin inverse conditions missing: {name}")
    if name == "mobis":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        if any(
            term not in all_text
            for term in [
                "공시내부이익제거",
                "총사용−현금표부담",
                "0.322",
                "0.582",
                "제3자",
                "우선주",
            ]
        ):
            raise ValueError(
                "Mobis consolidation, warranty or entitlement evidence missing"
            )
    if name == "sk-hynix":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "730,492,365",
            "24,070,000",
            "2026-11-19",
            "1,625,769",
            "유통주식수",
            "단일사업",
            "27.5%",
            "미기표",
        ]:
            if term not in all_text:
                raise ValueError(
                    f"Hynix cash or subsequent capital event missing: {term}"
                )
    if name == "nvidia":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "컴퓨트·네트워킹",
            "그래픽스",
            "주식보상",
            "분할취득원금",
            "공급·생산능력",
            "279",
            "AI클라우드",
            "자료미확인",
        ]:
            if term not in all_text:
                raise ValueError(f"NVIDIA business/capital contract missing: {term}")
    if name == "samsung-electronics":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "내부매출",
            "미표시기타이익",
            "비지배",
            "자료미확인",
            "주식보상",
            "DS",
            "SDC",
            "Harman",
        ]:
            if term not in all_text:
                raise ValueError(f"Samsung consolidation or cash scope missing: {term}")
    if name == "amd":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "계속영업",
            "160,000,000",
            "$0.01",
            "자료미확인",
            "금융리스",
            "ZT",
            "워런트",
        ]:
            if term not in all_text:
                raise ValueError(
                    f"AMD continuing business or warrant scope missing: {term}"
                )
    if name == "micron":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        required = [
            "장기미지급세금",
            "5.203bn",
            "정부지원차감전",
            "연간금융리스원금지급",
            "자료미확인",
            "6년차",
        ]
        if any(term not in all_text for term in required):
            raise ValueError(
                "Micron cash assumptions or missing anchors absent from PDF"
            )
    if name == "alphabet":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        required = ["전환우선주", "지정수량", "$62.50", "기본전환", "cappedcall"]
        if any(term not in all_text for term in required):
            raise ValueError("Alphabet preferred contract scope absent from PDF")
    if name == "apple":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "최근9개월전년대비",
            "영업외순손익",
            "금액의기간과실제지급여부",
            "0.538",
            "0.563",
            "자료미확인",
            "관세환급",
            "6년차",
        ]:
            if term not in all_text:
                raise ValueError(f"Apple cash-period or price basis missing: {term}")
    if name == "amazon":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in [
            "최근1년전체평가손익:미확정",
            "금액미공시",
            "0.599",
            "별도제외영업이익",
        ]:
            if term not in all_text:
                raise ValueError(
                    f"Amazon partial normalization evidence missing: {term}"
                )
    if name in {"intel", "qualcomm", "comparison-equipment"}:
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        terms = {
            "intel": [
                "파운드리적자축소중제품수익의기여는음수",
                "5,488",
                "1,800",
                "-830",
                "-8",
                "4,526",
            ],
            "qualcomm": ["-1,242", "+381", "+223", "+560", "+551", "9개월누적"],
            "comparison-equipment": [
                "9개월",
                "구형공정용장비",
                "기간서비스",
                "상대선호미확정",
            ],
        }[name]
        if any(term not in all_text for term in terms):
            raise ValueError(f"Business source/driver content missing: {name}")
    reports.append(
        dict(file=str(path.relative_to(ROOT)), pages=pages, primaryLinks=urls)
    )

files = [ROOT / report["file"] for report in reports]
files += sorted(OUT.glob("desktop-*.png")) + sorted(OUT.glob("mobile-*.png"))
files += sorted(OUT.glob(version[:12] + "-*"))
record = dict(
    checkedAt=datetime.now(timezone.utc).isoformat(),
    status="passed",
    snapshotHash=version,
    renderedPayloadHash=payload_hash,
    localReviewHashes=review_hashes,
    coverageReviewHashes=coverage_hashes,
    questionSelectionHashes=question_hashes,
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
(OUT / "pdf-verification.json").write_text(
    json.dumps(
        {
            "status": record["status"],
            "snapshotHash": version,
            "canonicalReport": "artifact-verification.json",
        },
        indent=2,
    )
    + "\n"
)
print(
    f"PASS {len(reports)} PDFs / {sum(len(r['pages']) for r in reports)} pages; {len(files)} artifact hashes bound to {version[:12]}"
)
