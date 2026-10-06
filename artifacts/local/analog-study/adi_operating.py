"""Analog Devices: consolidated economics, end markets and acquisition cash."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "0000006281-26-000073"
CORPUS = "de3533d62e37e0d0159d7db078962f3fecbf749d2fbc54ceefe03df40ec073e1"
SOURCE = "5b8acb9ec71b9b2c715081ce7d77f7af1c12fe45263ee0f952652f40f283b948"
ANNUAL = "0000006281-25-000153"
ANNUAL_SHA = "9b78ae042375b44e4cfeb10a7639aca0f683c02d2454f3af0eb6c630b752f0b4"
ANNUAL_HTML = "36785e2cb56436cc6b15db9b3099e570a6486115675e23fa92405ff717f80596"
TAGS = dict(
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    cost="CostOfGoodsAndServicesSold",
    operatingIncome="OperatingIncomeLoss",
    research="ResearchAndDevelopmentExpense",
    selling="SellingGeneralAndAdministrativeExpense",
    operatingAmortization="OperatingExpensesAmortizationOfIntangibles",
    special="RestructuringSettlementAndImpairmentProvisions",
    netIncome="NetIncomeLoss",
    interest="InterestExpenseNonoperating",
    depreciation="Depreciation",
    amortization="AmortizationOfIntangibleAssets",
    sbc="ShareBasedCompensation",
    deferredTax="DeferredIncomeTaxExpenseBenefit",
    other="OtherNoncashIncomeExpense",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    ppe="PaymentsToAcquirePropertyPlantAndEquipment",
    acquisitions="PaymentsToAcquireBusinessesNetOfCashAcquired",
    otherInvesting="PaymentsForProceedsFromOtherInvestingActivities",
)
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("depreciation", "설비 감가상각", 1),
    ("amortization", "원가·영업비용 무형상각", 1),
    ("sbc", "주식보상 되돌림", 1),
    ("deferredTax", "이연법인세", 1),
    ("other", "기타 비현금 조정", -1),
]
ANNUAL_WC = [
    ("IncreaseDecreaseInAccountsReceivable", "매출채권", -1),
    ("IncreaseDecreaseInInventories", "재고", -1),
    (
        "IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",
        "선급·기타 유동자산",
        -1,
    ),
    ("IncreaseDecreaseInAccountsPayableAndAccruedLiabilities", "매입·미지급 채무", 1),
    ("IncreaseDecreaseInAccruedIncomeTaxesPayable", "미지급 법인세", 1),
    ("IncreaseDecreaseInOtherNoncurrentAssets", "기타 장기자산", -1),
    ("IncreaseDecreaseInOtherNoncurrentLiabilities", "기타 장기부채", 1),
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="ADI의 연결 단일부문·시장별 매출·인수/매각·상각 범위를 새 원문에서 대사해야 합니다.",
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
        or any(s["cik"] != 6281 or s["accession"] != ANNUAL for s in [a, h])
        or as_of < "2026-08-19"
    ):
        raise ValueError("ADI source identity/date changed")
    annual = instance_rows(
        read_verified(DOCUMENT_ROOT / a["file"], ANNUAL_SHA), c, a, ANNUAL, "2025-11-25"
    )
    periods = [
        (1, annual, "2024-11-03", "2025-11-01"),
        (1, rows, "2025-11-02", "2026-08-01"),
        (-1, rows, "2024-11-03", "2025-08-02"),
    ]
    if [c["financials"]["start"], c["financials"]["end"]] != [
        "2025-11-02",
        "2026-08-01",
    ]:
        raise ValueError("ADI period changed")

    def exact(rs, tag, start, end, dims=()):
        f = select(
            [r for r in rs if r["decimals"] == "-3"], tag, start, end, dims, "USD"
        )
        if f is None:
            raise ValueError(f"ADI missing exact fact: {tag} {start} {end}")
        return f

    def combined(tag):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, s, e)) for k, rs, s, e in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            unit="USD",
            sourceUrl=source["primaryUrl"],
        )

    facts = {k: combined(tag) for k, tag in TAGS.items()}
    v = lambda k: facts[k]["value"]
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
        if i == 0:
            wc = [
                dict(
                    label=label,
                    value=sign * (f := exact(rs, tag, start, end))["value"],
                    coefficient=sign,
                    fact=f,
                )
                for tag, label, sign in ANNUAL_WC
            ]
        else:
            f = exact(rs, "IncreaseDecreaseInOperatingCapital", start, end)
            wc = [
                dict(
                    label="영업자산·부채 합계 · 상세 미공시",
                    value=-f["value"],
                    coefficient=-1,
                    fact=f,
                )
            ]
        working = sum(x["value"] for x in wc)
        cash = sum(x["value"] for x in parts) + working
        gp = val("revenue") - val("cost")
        income = (
            gp
            - val("research")
            - val("selling")
            - val("operatingAmortization")
            - val("special")
        )
        if cash != val("cfo") or income != val("operatingIncome"):
            raise ValueError("ADI cash/profit reconciliation failed " + end)
        checks.append(
            dict(
                start=start,
                end=end,
                parts=parts,
                workingParts=wc,
                workingCash=working,
                reportedCfo=cash,
                residual=0,
                incomeResidual=0,
                revenue=val("revenue"),
                grossProfit=gp,
                operatingIncome=income,
                research=val("research"),
                selling=val("selling"),
                special=val("special"),
                ppe=val("ppe"),
                acquisitions=val("acquisitions"),
                otherInvesting=val("otherInvesting"),
            )
        )
    bridge_parts = [
        dict(
            label=label,
            value=sign * v(key),
            fact=dict(
                facts[key],
                components=[
                    dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                    for p in facts[key]["components"]
                ],
            ),
        )
        for key, label, sign in CASH
    ]
    wcparts = [
        dict(coefficient=k * p["coefficient"], fact=p["fact"])
        for i, (k, _, _, _) in enumerate(periods)
        for p in checks[i]["workingParts"]
    ]
    bridge_parts.append(
        dict(
            label="영업자산·부채 · 연간 상세와 누적 합계 연결",
            value=sum(p["coefficient"] * p["fact"]["value"] for p in wcparts),
            fact=dict(components=wcparts, sourceUrl=source["primaryUrl"]),
        )
    )
    if sum(p["value"] for p in bridge_parts) != v("cfo"):
        raise ValueError("ADI TTM cash mismatch")
    revenue = v("revenue")
    gross = revenue - v("cost")
    segments = [
        dict(
            id="consolidated",
            label="연결 단일 영업부문",
            revenue=revenue,
            margin=gross / revenue,
            observedGrowth=checks[1]["revenue"] / checks[2]["revenue"] - 1,
            evidence=[facts["revenue"], facts["cost"]],
        )
    ]
    markets = []
    for member, label in [
        ("IndustrialMember", "산업"),
        ("AutomotiveMember", "자동차"),
        ("CommunicationsMember", "통신"),
        ("ConsumerMember", "소비자"),
    ]:
        dims = [("RevenueFromContractWithCustomerEndMarketAxis", member)]
        current = exact(rows, TAGS["revenue"], "2025-11-02", "2026-08-01", dims)
        prior = exact(rows, TAGS["revenue"], "2024-11-03", "2025-08-02", dims)
        markets.append(
            dict(
                id=member,
                label=label,
                current=current,
                previous=prior,
                change=current["value"] - prior["value"],
                operatingMargin=None,
            )
        )
    if (
        sum(x["current"]["value"] for x in markets) != checks[1]["revenue"]
        or sum(x["previous"]["value"] for x in markets) != checks[2]["revenue"]
    ):
        raise ValueError("ADI end-market revenues fail consolidation")
    stock = [
        dict(label=label, coefficient=k, fact=exact(rows, tag, None, "2026-08-01"))
        for label, k, tag in [
            ("순매출채권", 1, "AccountsReceivableNetCurrent"),
            ("재고", 1, "InventoryNet"),
            ("매입채무", -1, "AccountsPayableCurrent"),
        ]
    ]
    stock_net = sum(x["coefficient"] * x["fact"]["value"] for x in stock)
    reinvestment = v("ppe") + v("acquisitions") + v("otherInvesting")
    defaults = dict(
        segments=[dict(growthStart=0, growthEnd=0, marginEnd=gross / revenue)],
        tax=0.25,
        netInterest=-v("interest") / revenue,
        depreciation=(v("depreciation") + v("amortization")) / revenue,
        workingCapital=stock_net / revenue,
        capexStart=reinvestment / revenue,
        capexEnd=reinvestment / revenue,
        leaseStart=0,
        leaseEnd=0,
        discount=0.12,
        terminal=0.02,
        researchStart=v("research") / revenue,
        researchEnd=v("research") / revenue,
        sellingStart=v("selling") / revenue,
        sellingEnd=v("selling") / revenue,
        otherOperatingStart=(v("operatingAmortization") + v("special")) / revenue,
        otherOperatingEnd=(v("operatingAmortization") + v("special")) / revenue,
        minority=0,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    aps = extract(read_verified(DOCUMENT_ROOT / h["file"], ANNUAL_HTML))
    ai = {p["id"]: p for p in aps}
    required = {
        "33137871febd3e1f1625": "assignment of products to end markets may change",
        "745a45a28f2897c358ba": "23.4 million",
        "5538e8b8e5610ffbc80a": "24.2 million",
        "e469a4c44bc4618832c0": "24.4 million",
        "2b031a03c28385e94c60": "940,740",
        "f83d3454179e4732a756": "(19,377)",
    }
    if (
        any(text not in index[pid]["text"] for pid, text in required.items())
        or "one operating segment and one reportable segment"
        not in ai["f553b5ae0e771bbc993f"]["text"]
    ):
        raise ValueError("ADI source scope changed")
    for s in [
        a,
        h,
        dict(a["indexSource"], provider="SEC", retrievedAt=a["retrievedAt"]),
    ]:
        read_verified(DOCUMENT_ROOT / s["file"], s["sha256"])
        if s["file"] not in {x["file"] for x in c["sources"]}:
            c["sources"].append(s)
    m = dict(
        status="research_workspace",
        version="adi-consolidated-acquisition-cash-v1",
        sourcePeriod=["2025-08-03", "2026-08-01"],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        basisLabel="연간+현재9개월−전년9개월 · 연결 이익과 인수 현금",
        groupLabel="공시 단일 영업부문",
        growthLabel="9개월 동기 대비",
        marginLabel="연결 매출총이익률",
        grossProfitPath=True,
        grossProfitLabel="단일부문 연결 매출총이익",
        sellingLabel="판매관리비",
        otherOperatingLabel="영업비용 무형상각·순특별비용",
        capexLabel="설비·인수·기타 투자 가정",
        leaseLabel="추가 금융리스 원금 가정",
        netInterestLabel="이자 효과 (비용−)",
        intro="공시된 한 영업부문의 매출총이익에서 연구개발·판매관리·영업비용 무형상각·순특별비용을 차감합니다. 산업·자동차·통신·소비자는 매출 분류이며 독립 부문 이익이 아닙니다.",
        businessCaption="최종시장 매출은 현재 공시에 맞춰 재분류한 같은9개월을 비교합니다. 시장별 이익률과 설비 지출은 미공시이므로 연결 마진을 각 시장의 독립 마진으로 배분하지 않습니다.",
        anchorSummary="순매출채권+재고−매입채무의 기말 잔액 비율은 미래 증가 매출의 좁은 자금 소요 가정입니다. 당기 영업자산·부채 현금 합계에는 다른 항목도 포함되므로 이 잔액만으로 변화 원인을 확정하지 않습니다.",
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
            shareCompensationReplacement=v("sbc"),
            actualFinanceLeasePrincipal=None,
        ),
        analogEvidence=dict(
            markets=markets,
            periods=checks,
            workingCash=bridge_parts[-1]["value"],
            acquisitions=facts["acquisitions"],
            otherInvesting=facts["otherInvesting"],
            reinvestmentExcludingAcquisitionRatio=(v("ppe") + v("otherInvesting"))
            / revenue,
            annualAmortization=facts["amortization"]["components"][0]["fact"],
            saleGainNote=24200000,
            saleGainMda=24400000,
            saleGainDifference=200000,
            scope="주석과 MD&A 매각이익은 24.2/24.4백만 달러로 다릅니다. 차이의 원인을 추정하거나 임의 금액으로 순특별비용을 정상화하지 않습니다.",
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
                    "설비 취득 순지출",
                    v("ppe"),
                    "별도 처분 수취·자회사 매각 수취와 상계하지 않음",
                ),
                (
                    "인수 순현금",
                    v("acquisitions"),
                    "총취득대가·인수 후 매출과 범위가 다름",
                ),
                (
                    "기타 투자 순지출",
                    v("otherInvesting"),
                    "순수 기업 인수·설비로 명명하지 않음",
                ),
                (
                    "감가·총무형상각",
                    v("depreciation") + v("amortization"),
                    "원가와 영업비용에 포함된 상각 합계. 영업비용 상각을 또 가산하지 않음",
                ),
                (
                    "주식보상 현금표 되돌림",
                    v("sbc"),
                    "미래 비용에 유지하며 가산하지 않음",
                ),
                ("실제 금융리스 원금", None, "자료 미확인. 추가0은 미래 가정"),
            ]
        ],
        passages=[
            index[pid]
            for pid in list(required)
            + [
                "bd8ffc94ae013da6ffe0",
                "22646ff441d2df472d5d",
                "544abe08b53223afe140",
                "221eb03d4a2f0ea6caf8",
            ]
        ],
        historicalPassages=[
            dict(ai["f553b5ae0e771bbc993f"], sourceUrl=h["url"], sourceHash=ANNUAL_HTML)
        ],
        observedResidualLabel="인수·매각·상각 범위와 좁은 운전자본 가정은 별도 검토",
        rules=[
            "연간 운전자본 상세와 현재·전년9개월의 공시 합계를 연결합니다. 누적 합계를 특정 채권·재고의 현금 변동으로 배분하지 않습니다.",
            "원가와 영업비용 안 무형상각을 총상각으로 한 번 되돌립니다. 영업비용 상각을 별도로 다시 더하지 않습니다.",
            "순특별비용에는 구조조정·시설 손상·자회사 매각이익이 섞여 있습니다. 원문 주석/MD&A 금액 차이를 보존하며 임의 정상화하지 않습니다.",
            "인수 거래비용은 판매관리비에 남기고 인수 순현금은 재투자에 포함합니다. 인수 제외 민감도는 같은 성장이나 기술 경쟁력을 보장하지 않습니다.",
            "시장별 이익·지원금 전체·금융리스·순초과현금 배분은 미확인입니다. TI의 지원 구조를 ADI에 상속하지 않습니다.",
        ],
        remaining=[
            "최종시장별 물량·가격·가동률 기여와 이익",
            "Empower 인수의 추가 매출·비용·기술 회수",
            "매각이익 주석/MD&A 차이 및 순특별비용 정상화",
            "재투자·리스·만기 차환·운전자본 세부 현금·지원금",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
