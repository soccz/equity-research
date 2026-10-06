"""Texas Instruments: analog/embedded economics and distinct CHIPS cash channels."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "0000097476-26-000152"
CORPUS = "cac8a26cec564ef4cc3d730f2cd6916eca1d437ed6f403b575f4a0160a80d4e4"
SOURCE = "8e07b7379b7229422cc8bad65c57b26a622f1f9b9c753178df1e8321eff69901"
ANNUAL = "0000097476-26-000059"
ANNUAL_SHA = "349f62459b9963bf0bbcb59049bf76a22c483bb700a6d447ec5cc9b07cc62d49"
ANNUAL_HTML = "e0655b2c74f484f71eca67981a29510f5826acabd1f7fdcac5ce4dd00e27dd1b"
TAGS = dict(
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    operatingIncome="OperatingIncomeLoss",
    netIncome="NetIncomeLoss",
    tax="IncomeTaxExpenseBenefit",
    interest="InterestAndDebtExpense",
    depreciation="Depreciation",
    sbc="ShareBasedCompensation",
    assetGain="GainLossOnDispositionOfAssets1",
    deferredTax="DeferredIncomeTaxExpenseBenefit",
    receivables="IncreaseDecreaseInAccountsReceivable",
    inventory="IncreaseDecreaseInInventories",
    prepaid="IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",
    payables="IncreaseDecreaseInAccountsPayableAndAccruedLiabilities",
    salaries="IncreaseDecreaseInAccruedSalaries",
    taxPayable="IncreaseDecreaseInAccruedIncomeTaxesPayable",
    pension="IncreaseDecreaseInPensionAndPostretirementObligations",
    other="IncreaseDecreaseInOtherOperatingCapitalNet",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    ppe="PaymentsToAcquirePropertyPlantAndEquipment",
    otherInvesting="PaymentsForProceedsFromOtherInvestingActivities",
    incentives="ProceedsFromU.S.CHIPSAndScienceActCHIPSActIncentives",
    taxCredit="InvestmentTaxCreditUsedToReduceIncomeTaxesPayable",
)
CASH = [
    ("netIncome", "순이익", 1),
    ("depreciation", "설비 감가상각", 1),
    ("softwareAmortization", "자본화 소프트웨어 상각", 1),
    ("sbc", "주식보상 되돌림", 1),
    ("assetGain", "자산 매각손익 제거", -1),
    ("deferredTax", "이연법인세", 1),
    ("receivables", "매출채권 현금 효과", -1),
    ("inventory", "재고 현금 효과", -1),
    ("prepaid", "선급·기타 유동자산", -1),
    ("payables", "매입·미지급 채무", 1),
    ("salaries", "미지급 보수", 1),
    ("taxPayable", "미지급 법인세", 1),
    ("pension", "퇴직급여 적립 상태", 1),
    ("other", "기타 영업현금 조정", -1),
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="TI의 사업부·소프트웨어 상각·CHIPS 세금/투자 현금 분류를 새 원문에서 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    a = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}-xbrl.manifest.json").read_text()
    )
    h = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}.manifest.json").read_text()
    )
    if (
        source["sha256"] != SOURCE
        or a["sha256"] != ANNUAL_SHA
        or h["sha256"] != ANNUAL_HTML
        or any(x["cik"] != 97476 or x["accession"] != ANNUAL for x in [a, h])
        or as_of < "2026-07-24"
    ):
        raise ValueError("TI source identity or date changed")
    annual = instance_rows(
        read_verified(DOCUMENT_ROOT / a["file"], ANNUAL_SHA), c, a, ANNUAL, "2026-02-06"
    )
    periods = [
        (1, annual, "2025-01-01", "2025-12-31"),
        (1, rows, "2026-01-01", "2026-06-30"),
        (-1, rows, "2025-01-01", "2025-06-30"),
    ]
    if [c["financials"]["start"], c["financials"]["end"]] != [
        "2026-01-01",
        "2026-06-30",
    ]:
        raise ValueError("TI reporting period changed")

    def exact(rs, tag, start, end, dims=()):
        r = select(rs, tag, start, end, dims, "USD")
        if r is None:
            raise ValueError(f"TI missing fact: {tag} {start} {end} {dims}")
        return r

    def combine(tags, dims=None):
        tags = [tags] * 3 if isinstance(tags, str) else tags
        parts = [
            dict(coefficient=k, fact=exact(rs, tags[i], s, e, dims[i] if dims else ()))
            for i, (k, rs, s, e) in enumerate(periods)
        ]
        return dict(
            value=sum(x["coefficient"] * x["fact"]["value"] for x in parts),
            components=parts,
            unit="USD",
            sourceUrl=source["primaryUrl"],
        )

    facts = {k: combine(tag) for k, tag in TAGS.items()}
    # The interim uses a broad tag, but the source caption remains software amortization.
    facts["softwareAmortization"] = combine(
        [
            "CapitalizedComputerSoftwareAmortization1",
            "AmortizationOfIntangibleAssets",
            "AmortizationOfIntangibleAssets",
        ]
    )
    v = lambda k: facts[k]["value"]
    segments = []
    for annual_member, current_member, label in [
        ("AnalogMember", "AnalogSegmentMember", "아날로그"),
        (
            "EmbeddedProcessingMember",
            "EmbeddedProcessingSegmentMember",
            "임베디드 처리",
        ),
        ("AllOtherSegmentsMember", "AllOtherSegmentsMember", "기타 사업·본사 항목"),
    ]:
        dims = [
            [("StatementBusinessSegmentsAxis", x)]
            for x in [annual_member, current_member, current_member]
        ]
        revenue = combine(TAGS["revenue"], dims)
        op = combine(TAGS["operatingIncome"], dims)
        segments.append(
            dict(
                id=current_member,
                label=label,
                revenue=revenue["value"],
                margin=op["value"] / revenue["value"],
                observedGrowth=revenue["components"][1]["fact"]["value"]
                / revenue["components"][2]["fact"]["value"]
                - 1,
                evidence=[revenue, op],
            )
        )
    checks = []
    for i, (_, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        parts = [
            dict(
                label=label,
                value=sign * val(key),
                fact=facts[key]["components"][i]["fact"],
            )
            for key, label, sign in CASH
        ]
        residual = sum(x["value"] for x in parts) - val("cfo")
        revenue_residual = sum(
            s["evidence"][0]["components"][i]["fact"]["value"] for s in segments
        ) - val("revenue")
        income_residual = sum(
            s["evidence"][1]["components"][i]["fact"]["value"] for s in segments
        ) - val("operatingIncome")
        if residual or revenue_residual or income_residual:
            raise ValueError("TI source-period cash/business mismatch " + end)
        checks.append(
            dict(
                start=start,
                end=end,
                parts=parts,
                reportedCfo=val("cfo"),
                residual=residual,
                revenueResidual=revenue_residual,
                incomeResidual=income_residual,
                netIncome=val("netIncome"),
                taxCredit=val("taxCredit"),
                incentives=val("incentives"),
                ppe=val("ppe"),
                issuerFreeCash=val("cfo") - val("ppe") + val("incentives"),
                withoutChips=val("cfo") - val("taxCredit") - val("ppe"),
            )
        )
    bridge_parts = []
    for key, label, sign in CASH:
        combined = facts[key]
        bridge_parts.append(
            dict(
                label=label,
                value=sign * combined["value"],
                fact=dict(
                    combined,
                    components=[
                        dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                        for p in combined["components"]
                    ],
                ),
            )
        )
    if sum(p["value"] for p in bridge_parts) != v("cfo"):
        raise ValueError("TI TTM cash mismatch")
    stock = [
        dict(label=label, coefficient=k, fact=exact(rows, tag, None, "2026-06-30"))
        for label, k, tag in [
            ("매출채권 순액", 1, "AccountsReceivableNetCurrent"),
            ("재고", 1, "InventoryNet"),
            ("매입채무", -1, "AccountsPayableCurrent"),
        ]
    ]
    stock_net = sum(x["coefficient"] * x["fact"]["value"] for x in stock)
    revenue = v("revenue")
    reinvestment = v("ppe") + v("otherInvesting")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.25,
        netInterest=-v("interest") / revenue,
        depreciation=(v("depreciation") + v("softwareAmortization")) / revenue,
        workingCapital=stock_net / revenue,
        capexStart=reinvestment / revenue,
        capexEnd=reinvestment / revenue,
        leaseStart=0,
        leaseEnd=0,
        discount=0.12,
        terminal=0.02,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    annual_ps = extract(read_verified(DOCUMENT_ROOT / h["file"], ANNUAL_HTML))
    annual_index = {p["id"]: p for p in annual_ps}
    required = {
        "1e3d1680399b74d24a2c": "Amortization of capitalized software",
        "30f9e8e4f14fda920f5b": "corporate-level",
        "89dcf81f1470c20000c3": "per-unit",
        "107be56513fff2ffbd06": "301 million",
        "81b3e9e3a4f616fa73cd": "plus proceeds",
        "dbf461f9a059862c8a3a": "433 million",
    }
    if (
        any(text not in index[pid]["text"] for pid, text in required.items())
        or "353 million" not in annual_index["59b646ecd936577e789f"]["text"]
    ):
        raise ValueError("TI source-caption or incentives interpretation changed")
    for item in [
        a,
        h,
        dict(a["indexSource"], provider="SEC", retrievedAt=a["retrievedAt"]),
    ]:
        read_verified(DOCUMENT_ROOT / item["file"], item["sha256"])
        if item["file"] not in {x["file"] for x in c["sources"]}:
            c["sources"].append(item)
    m = dict(
        status="research_workspace",
        version="ti-analog-incentive-cash-v1",
        sourcePeriod=["2025-07-01", "2026-06-30"],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        basisLabel="연간+현재반기−전년반기 · 사업 이익·현금·CHIPS 분류 대사",
        groupLabel="공시 보고부문과 기타",
        growthLabel="반기 동기 대비",
        marginLabel="영업이익률",
        capexLabel="설비·기타 투자 지출 가정",
        leaseLabel="추가 금융리스 원금 가정",
        netInterestLabel="이자 효과 (비용−)",
        intro="아날로그·임베디드와 기타 사업·본사 항목의 영업이익을 연결합니다. 공장·지원 비용과 감가상각은 제품 단위로 사업부에 배부돼 부문별 감가상각을 독립 추정하지 않습니다.",
        businessCaption="기타에는 DLP·계산기와 본사·구조조정·자산 처분 항목이 섞여 있습니다. 이를 하나의 순수 제품 마진이나 미래 정상 이익으로 확정하지 않습니다. 연간/반기 태그 이름 변경도 원문 사업 설명과 대사했습니다.",
        anchorSummary="기말 순매출채권+재고−매입채무를 최근1년 매출로 나눈 좁은 운전자본 대용입니다. CHIPS 수취채권이 포함된 선급·기타자산을 반복 운전자본에 합산하지 않습니다. 세율25%와 신규 인센티브 수취0·금융리스0은 미래 가정이며 실제 미지급·미수령0 확인이 아닙니다.",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        bridge=dict(
            parts=bridge_parts,
            periods=checks,
            reportedCfo=v("cfo"),
            residual=0,
            cashAfterInvestmentLeaseSbc=None,
        ),
        anchors=dict(
            workingStockTerms=stock,
            workingStockNet=stock_net,
            actualFinanceLeasePrincipal=None,
            shareCompensationReplacement=v("sbc"),
        ),
        incentiveEvidence=dict(
            periods=checks,
            reportedCfo=v("cfo"),
            ppe=v("ppe"),
            taxCredit=v("taxCredit"),
            incentives=v("incentives"),
            issuerFreeCash=v("cfo") - v("ppe") + v("incentives"),
            withoutChips=v("cfo") - v("taxCredit") - v("ppe"),
            annualDepreciationBenefit=353000000,
            annualBenefitPassage=dict(
                annual_index["59b646ecd936577e789f"],
                sourceUrl=h["url"],
                sourceHash=ANNUAL_HTML,
            ),
            otherInvesting=facts["otherInvesting"],
            workingStockTerms=stock,
            workingStockNet=stock_net,
        ),
        cashAnchors=[
            dict(
                label=label,
                period="최근1년",
                value=value,
                sourceUrl=source["primaryUrl"],
                scope=scope,
            )
            for label, value, scope in [
                (
                    "설비 현금 지출",
                    v("ppe"),
                    "투자활동 CHIPS 수취를 차감하지 않은 총지출",
                ),
                (
                    "기타 투자활동 순지출",
                    v("otherInvesting"),
                    "기업 인수·소프트웨어만으로 단정하지 않음. 전체를 미래 임시 지출에 포함",
                ),
                (
                    "감가·소프트웨어 상각",
                    v("depreciation") + v("softwareAmortization"),
                    "공시 비용 순액. CHIPS 감가 절감액을 다시 가산하지 않음",
                ),
                ("주식보상 현금표 조정", v("sbc"), "미래 비용에 유지, 가산하지 않음"),
                ("실제 금융리스 원금", None, "자료 미확인. 미래 추가0은 별도 가정"),
            ]
        ],
        passages=[
            index[pid]
            for pid in list(required)
            + [
                "43f42a3ef3c788067aaf",
                "94e12b3cffe7725ed468",
                "631afbb2f3c27c32dc2c",
                "20e572529ffe41399b6e",
                "b8e43ac4e11648c961ae",
                "c7045a7939a6a6bdbb3c",
            ]
        ],
        historicalPassages=[
            dict(annual_index[pid], sourceUrl=h["url"], sourceHash=ANNUAL_HTML)
            for pid in [
                "59b646ecd936577e789f",
                "4a8adeb915a678d975b3",
                "72847c3bc85e3b7f620f",
                "4f7b30926bc2735d9d5b",
                "d6a30115200eb58d5f12",
            ]
        ],
        observedResidualLabel="회사 비GAAP FCF와 CHIPS 제외 민감도는 아래 별도 표시",
        rules=[
            "CHIPS 세액공제의 납부 감소는 이미 CFO에 포함됩니다. 투자활동 수취와 합산한 총혜택을 CFO에 다시 더하지 않습니다.",
            "CHIPS 제외 값은 현재 분류의 지급·수취 민감도입니다. 세율·투자·생산능력을 함께 재설계한 정책 부재의 인과 추정이나 정상 FCFE가 아닙니다.",
            "초기 미래 경로는 신규 인센티브 현금 수취0, 명시세율25%, 공시 순감가상각과 기타 사업 비용의 유지 가정입니다. 마지막 연간 감가 절감액을 이익과 현금 양쪽에 다시 가산하지 않습니다.",
            "2026년 설비 지출20–30억 달러는 회사 전망입니다. 최근1년 설비 지출과 연도 범위가 달라 자동으로 미래 정상 재투자에 대입하지 않습니다.",
            "미래 주식보상 비용을 유지합니다. 금융리스·차환·초과현금 배분과 유지 투자 수준은 추가 검토가 필요합니다.",
        ],
        remaining=[
            "아날로그 가격·출하·제품 구성 및 공장 가동률별 고정비",
            "기타 사업과 본사·구조조정의 미래 비용 구분",
            "CHIPS 종류별 지급 시점·자산별 감가 감소와 세금 효과",
            "유지/증설 설비·기타 투자 지출·리스·차환·순초과현금",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
