"""ServiceNow: GAAP revenue groups, contract costs and acquisition cash."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "0001373715-26-000076"
CORPUS = "40c028d63c93ca937aef33b671c0b8178402b9edff0fb702014fc9d074d7dcd4"
CURRENT_SHA = "53af9102209b6fc4f23df16c5bb7982370457a911f8dd32d5afccf34a212387b"
ANNUAL = "0001373715-26-000007"
ANNUAL_SHA = "b67e8c17103e380fd12c4de581597b952c5dd186d03e22d6333b154a8d21e923"
ANNUAL_HTML = "e4ee34aa2fb94e472fc2f8ca08521d5fcf94edf1368c1ee71d89a3463bb7dcc9"
TAGS = dict(
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    operatingIncome="OperatingIncomeLoss",
    netIncome="NetIncomeLoss",
    grossProfit="GrossProfit",
    cost="CostOfRevenue",
    selling="SellingAndMarketingExpense",
    research="ResearchAndDevelopmentExpense",
    administrative="GeneralAndAdministrativeExpense",
    da="DepreciationDepletionAndAmortization",
    commissionAmortization="AmortizationOfDeferredSalesCommissions",
    sbc="ShareBasedCompensation",
    deferredTax="IncreaseDecreaseInDeferredIncomeTaxes",
    other="OtherOperatingActivitiesCashFlowStatement",
    receivables="IncreaseDecreaseInReceivables",
    commissions="IncreaseDecreaseInDeferredCharges",
    otherAssets="IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",
    payables="IncreaseDecreaseInAccountsPayable",
    deferredRevenue="IncreaseDecreaseInContractWithCustomerLiability",
    otherLiabilities="IncreaseDecreaseInAccruedLiabilitiesAndOtherOperatingLiabilities",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    ppe="PaymentsToAcquirePropertyPlantAndEquipment",
    intangible="PaymentsToAcquireIntangibleAssets",
    acquisitions="PaymentsToAcquireBusinessesNetOfCashAcquired",
    interestIncome="InterestIncomeNonOperating",
    interestPaid="InterestPaidNet",
)
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("da", "감가·무형·소프트웨어 상각", 1),
    ("commissionAmortization", "판매수수료 자산 상각", 1),
    ("sbc", "주식보상 되돌림", 1),
    ("deferredTax", "이연법인세 현금 조정", -1),
    ("other", "기타 비현금 조정", 1),
    ("receivables", "매출채권 현금 효과", -1),
    ("commissions", "판매수수료 자산 취득 현금", -1),
    ("otherAssets", "선급·기타 영업자산", -1),
    ("payables", "매입채무", 1),
    ("deferredRevenue", "계약부채·선수 수익", 1),
    ("otherLiabilities", "미지급·기타 영업부채", 1),
]
PASSAGES = [
    "8d28b0681fc0d3d4de4b",
    "65fc66205b718e424858",
    "cce3c20cd2bb97e3d34b",
    "8db5ccd2994373e3dc48",
    "f896d07a32ac9a69a5a1",
    "e62cc502d9170dacea2c",
    "8260770ddef71a41d792",
    "03134b55c5054738e437",
    "40de474493fc616fc192",
    "bcdf2cb4793bb603ef36",
    "aeb2106f134370602ac8",
    "8a4975d009cbb83ef67e",
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="ServiceNow의 인수·판매수수료·구독 원가와 신규 부채 범위를 새 공시에서 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    manifest = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}-xbrl.manifest.json").read_text()
    )
    html = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}.manifest.json").read_text()
    )
    if (
        source["sha256"] != CURRENT_SHA
        or manifest["sha256"] != ANNUAL_SHA
        or html["sha256"] != ANNUAL_HTML
        or manifest["cik"] != c["cik"]
        or html["cik"] != c["cik"]
    ):
        raise ValueError("ServiceNow source identity changed")
    annual = instance_rows(
        read_verified(DOCUMENT_ROOT / manifest["file"], ANNUAL_SHA),
        c,
        manifest,
        ANNUAL,
        "2026-01-29",
    )
    f = c["financials"]
    periods = [
        (1, annual, "2025-01-01", "2025-12-31"),
        (1, rows, f["start"], f["end"]),
        (-1, rows, f["priorStart"], f["priorEnd"]),
    ]

    def exact(rs, tag, start, end, dims=()):
        r = select(rs, tag, start, end, dims, "USD")
        if r is None:
            raise ValueError(
                "ServiceNow fact missing: " + tag + " " + str(start) + " " + end
            )
        return r

    def combined(tag, dims=()):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, start, end, dims))
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            sourceUrl=source["primaryUrl"],
            unit="USD",
        )

    facts = {key: combined(tag) for key, tag in TAGS.items()}
    v = lambda key: facts[key]["value"]
    segments = []
    for member, label in [
        ("LicenseAndServiceMember", "Subscription · 구독·자체 호스팅"),
        ("TechnologyServiceMember", "전문 서비스·기타"),
    ]:
        dims = [("ProductOrServiceAxis", member)]
        sales = combined(TAGS["revenue"], dims)
        cost = combined("CostOfRevenue", dims)
        gross = dict(
            value=sales["value"] - cost["value"],
            components=sales["components"]
            + [
                dict(coefficient=-p["coefficient"], fact=p["fact"])
                for p in cost["components"]
            ],
            sourceUrl=source["primaryUrl"],
            unit="USD",
        )
        segments.append(
            dict(
                id=member,
                label=label,
                revenue=sales["value"],
                margin=gross["value"] / sales["value"],
                observedGrowth=sales["components"][1]["fact"]["value"]
                / sales["components"][2]["fact"]["value"]
                - 1,
                evidence=[sales, gross],
                costEvidence=cost,
            )
        )
    checks = []
    gain_parts = []
    for i, (_, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        components = [
            dict(
                label=label,
                value=sign * val(key),
                fact=facts[key]["components"][i]["fact"],
            )
            for key, label, sign in CASH
        ]
        if i:
            gain = exact(rs, "EquitySecuritiesFvNiUnrealizedGainLoss", start, end)
            components.append(
                dict(label="전략 투자 미실현이익 제거", value=-gain["value"], fact=gain)
            )
            gain_parts.append(dict(coefficient=-periods[i][0], fact=gain))
        cash = sum(x["value"] for x in components)
        sales = sum(
            s["evidence"][0]["components"][i]["fact"]["value"] for s in segments
        )
        costs = sum(
            s["costEvidence"]["components"][i]["fact"]["value"] for s in segments
        )
        gross = sales - costs
        op = gross - val("selling") - val("research") - val("administrative")
        if (
            cash != val("cfo")
            or sales != val("revenue")
            or costs != val("cost")
            or gross != val("grossProfit")
            or op != val("operatingIncome")
        ):
            raise ValueError("ServiceNow period cash and profit reconciliation failed")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=cash,
                residual=0,
                revenueResidual=0,
                incomeResidual=0,
                components=components,
                operatingIncome=op,
            )
        )
    index = {p["id"]: p for p in load(c)["passages"]}
    if any(pid not in index for pid in PASSAGES):
        raise ValueError("ServiceNow passages missing")
    coupons = []
    for pid, principal, coupon, effective, due in [
        ("31b2472ef09550a8252c", 1500000000, 0.014, 0.0153, "2030-09"),
        ("68fcfcf255bccbd1f47e", 750000000, 0.0425, 0.0468, "2028-05"),
        ("086e0c43b509ae72427c", 600000000, 0.047, 0.05, "2031-08"),
        ("25603972d8499f61b300", 650000000, 0.0505, 0.0536, "2033-05"),
        ("c099c5e17e50c83c1ac9", 1250000000, 0.054, 0.0568, "2036-05"),
        ("75af9019a72c34b69ef5", 750000000, 0.063, 0.0657, "2056-05"),
    ]:
        p = index[pid]
        if (
            f"{principal/1e6:,.0f}" not in p["text"]
            or f"{coupon*100:.2f}%" not in p["text"]
        ):
            raise ValueError("ServiceNow coupon table changed")
        coupons.append(
            dict(
                principal=principal,
                coupon=coupon,
                effectiveRate=effective,
                maturity=due,
                annualCoupon=principal * coupon,
                source=p,
            )
        )
    cp = index["bcdf2cb4793bb603ef36"]
    if not all(t in cp["text"] for t in ["$2.1 billion", "3.98%", "81 days"]):
        raise ValueError("ServiceNow commercial paper terms changed")
    bond_coupon = sum(x["annualCoupon"] for x in coupons)
    cp_proxy = 2100000000 * 0.0398
    annual_interest = bond_coupon + cp_proxy
    revenue = v("revenue")
    stock_terms = [
        (1, "순매출채권", "AccountsReceivableNetCurrent"),
        (-1, "매입채무", "AccountsPayableCurrent"),
        (-1, "유동 계약부채", "ContractWithCustomerLiabilityCurrent"),
        (-1, "비유동 계약부채", "ContractWithCustomerLiabilityNoncurrent"),
    ]
    working_stock = [
        dict(coefficient=k, label=label, fact=exact(rows, tag, None, f["end"]))
        for k, label, tag in stock_terms
    ]
    working_net = sum(t["coefficient"] * t["fact"]["value"] for t in working_stock)
    reinvestment = v("ppe") + v("intangible") + v("acquisitions") + v("commissions")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.25,
        netInterest=-annual_interest / revenue,
        depreciation=(v("da") + v("commissionAmortization")) / revenue,
        workingCapital=working_net / revenue,
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
        otherOperatingStart=v("administrative") / revenue,
        otherOperatingEnd=v("administrative") / revenue,
        minority=0,
    )
    annual_ps = extract(read_verified(DOCUMENT_ROOT / html["file"], ANNUAL_HTML))
    historical = [
        p
        for p in annual_ps
        if p["ordinal"]
        in [453, 718, 719, 720, 721, 723, 724, 725, 726, 727, 728, 729, 785]
    ]
    if len(historical) != 13 or not any("five years" in p["text"] for p in historical):
        raise ValueError("ServiceNow contract cost policy missing")
    for s in [
        manifest,
        html,
        dict(
            manifest["indexSource"], provider="SEC", retrievedAt=manifest["retrievedAt"]
        ),
    ]:
        read_verified(DOCUMENT_ROOT / s["file"], s["sha256"])
        if s["file"] not in {x["file"] for x in c["sources"]}:
            c["sources"].append(s)
    parts = [
        dict(
            label=label,
            value=sign * v(key),
            fact=dict(
                sourceUrl=source["primaryUrl"],
                components=[
                    dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                    for p in facts[key]["components"]
                ],
            ),
        )
        for key, label, sign in CASH
    ]
    parts.append(
        dict(
            label="현재·전년 반기의 별도 투자 미실현이익 제거",
            value=sum(p["coefficient"] * p["fact"]["value"] for p in gain_parts),
            fact=dict(sourceUrl=source["primaryUrl"], components=gain_parts),
        )
    )
    if sum(p["value"] for p in parts) != v("cfo"):
        raise ValueError("ServiceNow TTM cash bridge failed")
    m = dict(
        status="research_workspace",
        version="servicenow-contract-acquisition-cash-v1",
        sourcePeriod=["2025-07-01", f["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        basisLabel="세 기간 총이익·현금 대사 / 현재 부채 가정",
        growthLabel="같은 반기 대비 / 인수 포함",
        groupLabel="두 공시 매출 구분",
        grossProfitPath=True,
        marginLabel="매출총이익률",
        sellingLabel="판매·마케팅비",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        otherOperatingLabel="일반관리비",
        netInterestLabel="현재 부채 연이자 대용 · 투자수익 제외",
        capexLabel="설비·무형·인수·판매수수료 현금",
        leaseLabel="금융리스 원금 가정",
        intro="단일 영업부문 안의 구독·자체 호스팅과 전문서비스의 매출총이익에서 공통 비용을 차감합니다. 회사 non-GAAP 이익의 주식보상 제외를 그대로 주주 현금으로 사용하지 않습니다. 인수 이후 비용과 판매수수료 자산·선수 수익을 분리합니다.",
        businessCaption="두 매출 구분은 독립 보고부문이 아닙니다. 구독 원가에는 호스팅·고객 지원·인수 무형상각과 주식보상이 포함됩니다. 전문서비스 총손실을 구독 본업 전체 손실로 바꾸거나 인수 매출을 유기 성장으로 확정하지 않습니다.",
        anchorSummary="기말 순매출채권−매입채무−유동·비유동 계약부채를 최근1년 매출로 나눈 비율을 미래 증가 매출의 자금 소요로 가정합니다. 음수 비율은 고객 선급의 구조를 반영하는 가정이며 영구 무상 자금이나 실제 회수일수가 아닙니다. 판매수수료 취득은 별도 재투자에 포함하여 이 계수와 중복 차감하지 않습니다. 세율25%와 금융리스0은 명시적 연구 가정입니다.",
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=None,
        ),
        observedResidualLabel="금융리스 전체 지급 미확인 / 대규모 인수와 반복 투자 분리 필요",
        anchors=dict(
            workingStockTerms=working_stock,
            workingStockNet=working_net,
            actualFinanceLeasePayment=None,
            shareCompensationReplacement=v("sbc"),
        ),
        softwareEvidence=dict(
            coupons=coupons,
            bondAnnualCoupon=bond_coupon,
            commercialPaperPrincipal=2100000000,
            commercialPaperRate=0.0398,
            commercialPaperRemainingDays=81,
            commercialPaperAnnualProxy=cp_proxy,
            annualInterestProxy=annual_interest,
            commercialPaperSource=cp,
            workingStockTerms=working_stock,
            workingStockNet=working_net,
            commissionAmortization=facts["commissionAmortization"],
            commissionCash=facts["commissions"],
            acquisitionCash=facts["acquisitions"],
            reinvestmentExcludingAcquisition=reinvestment - v("acquisitions"),
            reinvestmentExcludingAcquisitionRatio=(reinvestment - v("acquisitions"))
            / revenue,
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
                    "판매수수료 자산 상각",
                    v("commissionAmortization"),
                    "미래에는 총이익·영업비용에서 이미 차감된 상각을 되돌림",
                ),
                (
                    "판매수수료 자산 취득 현금",
                    v("commissions"),
                    "영업활동 현금 분류. 미래 재투자 묶음에서 한 번 차감",
                ),
                (
                    "기업 인수 순현금",
                    v("acquisitions"),
                    "반복 투자 수준과 인수 후 추가 성장을 승인하지 않음",
                ),
                (
                    "설비·무형 취득",
                    v("ppe") + v("intangible"),
                    "기업 인수·판매수수료와 별도 공시 금액",
                ),
                (
                    "주식보상 현금표 되돌림",
                    v("sbc"),
                    "미래 GAAP 원가·영업비용에는 비용으로 남기고 더하지 않음",
                ),
                (
                    "보고 이자 지급",
                    v("interestPaid"),
                    "신규 부채 발행 전 기간을 포함; 미래 연이자 대용과 구분",
                ),
                (
                    "보고 이자 수익",
                    v("interestIncome"),
                    "금융자산 배분 미완료로 미래 사업 현금에서 제외",
                ),
                (
                    "전체 금융리스 원금",
                    None,
                    "자료 미확인. 기본값0은 실제 지급0의 확인이 아님",
                ),
            ]
        ],
        passages=[index[x] for x in PASSAGES],
        historicalPassages=[
            dict(p, sourceUrl=html["url"], sourceHash=ANNUAL_HTML) for p in historical
        ],
        rules=[
            "원 연간+현재 반기−전년 반기로 연결하며 각 기간의 매출·매출원가·영업이익·영업현금을 대사합니다. 연간 기타 조정과 반기 별도 투자 평가이익 제거를 같은 공시 항목으로 만들지 않습니다.",
            "주식보상은 미래 비용에 남깁니다. 보고 CFO의 주식보상 되돌림을 미래 현금에 더하거나 실제 자기주식 매입을 동시에 차감하지 않습니다.",
            "판매수수료 자산 상각을 되돌리고 자산 취득 현금을 별도 재투자에 포함합니다. 보고 CFO에서 관측 잔여 현금을 계산할 때 취득을 다시 차감하면 중복입니다.",
            "대규모 인수 순현금을 처음부터 영으로 정상화하지 않습니다. 연구자가 미래 재투자 비율을 낮출 때 기존 제품 유지·신규 성장·인수 무형자산 소진을 함께 검토해야 합니다.",
            "미래 이자는 기말 채권 원금×표면이율과 기말 CP 잔액×공시 가중금리의 연간 대용을 사용합니다. 실효이율은 할인·발행비용 상각을 포함하므로 쿠폰과 구분합니다. CP81일 만기를 매년 같은 조건으로 차환한다는 것은 확인되지 않은 가정입니다.",
            "기말 부채를 전 기간 유지하는 초기 이자 가정은 개별 만기·상환·차환 일정을 완성한 것이 아닙니다. 원금 상환과 후속 자금 조달은 별도이며 현금·투자자산 가치를 더하지 않습니다.",
            "영업리스·클라우드 사용료는 영업비용 안에 유지합니다. 계약 잔여 지급액을 당기 현금 취득으로 차감하거나 전액을 추가 부채로 반복 차감하지 않습니다.",
        ],
        remaining=[
            "인수 후 매출·원가 구성과 유기 성장 분리",
            "대규모 인수 이후 반복 재투자와 수수료 상각기간",
            "고객 선급 구조와 판매 계약 갱신 조건",
            "신규 부채 만기·차환·현금 및 금융자산 배분",
            "금융리스 실제 현금과 데이터센터 약정",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
