"""Adobe: current product economics, recast segments and contract-cost scope."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "0000796343-26-000156"
CORPUS = "ca502273cd4b5f00ade8ff899cc10aad773e1af7dd4631521139e5a691c4dfeb"
SOURCE = "b700b414c14b19b943f0cf33be77be842d1cb776a08dd5f834603d0ab55b12cb"
ANNUAL = "0000796343-26-000003"
ANNUAL_SHA = "880c19c219201e31741d7750d4f5e31665b8c9b69d46688796f429989810501f"
ANNUAL_HTML = "2d595e05d02ce751abf8948f28864d3e55926669bc211d866d6536cf70bb489c"
TAGS = dict(
    revenue="Revenues",
    cost="CostOfRevenue",
    operatingIncome="OperatingIncomeLoss",
    netIncome="NetIncomeLoss",
    research="ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost",
    selling="SellingAndMarketingExpense",
    administrative="GeneralAndAdministrativeExpense",
    operatingAmortization="OperatingExpensesAmortizationOfPurchasedIntangibles",
    cashDa="DepreciationDepletionAndAmortization",
    sbc="ShareBasedCompensation",
    deferredTax="DeferredIncomeTaxesAndTaxCredits",
    other="OtherNoncashIncomeExpense",
    receivables="IncreaseDecreaseInReceivables",
    otherAssets="IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",
    payables="IncreaseDecreaseInAccountsPayable",
    accrued="IncreaseDecreaseInAccruedLiabilities",
    taxPayable="IncreaseDecreaseInAccruedIncomeTaxesPayable",
    deferredRevenue="IncreaseDecreaseInDeferredRevenue",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    ppe="PaymentsToAcquirePropertyPlantAndEquipment",
    acquisitions="PaymentsToAcquireBusinessesNetOfCashAcquired",
    investments="PaymentsToAcquireLongtermInvestments",
    interest="InterestExpenseNonoperating",
    intangibleAmortization="AmortizationOfIntangibleAssets",
)
CASH = [
    ("netIncome", "순이익", 1),
    ("cashDa", "현금표 감가·상각·증가분 조정", 1),
    ("sbc", "주식보상 되돌림", 1),
    ("deferredTax", "이연법인세 조정", 1),
    ("other", "기타 비현금 항목 · 원문 표시 부호", -1),
    ("receivables", "채권 현금 효과", -1),
    ("otherAssets", "선급·기타 자산 현금 효과", -1),
    ("payables", "매입채무", 1),
    ("accrued", "미지급 부채", 1),
    ("taxPayable", "미지급 세금", 1),
    ("deferredRevenue", "선수 수익", 1),
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="Adobe의 보고부문 변경·인수·계약 취득비와 상각 범위를 새 공시에서 다시 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    annual_source = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}-xbrl.manifest.json").read_text()
    )
    html = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}.manifest.json").read_text()
    )
    if (
        source["sha256"] != SOURCE
        or annual_source["sha256"] != ANNUAL_SHA
        or html["sha256"] != ANNUAL_HTML
        or any(
            s["cik"] != c["cik"] or s["accession"] != ANNUAL
            for s in [annual_source, html]
        )
    ):
        raise ValueError("Adobe source identity changed")
    annual = instance_rows(
        read_verified(DOCUMENT_ROOT / annual_source["file"], ANNUAL_SHA),
        c,
        annual_source,
        ANNUAL,
        "2026-01-15",
    )
    annual_passages = extract(read_verified(DOCUMENT_ROOT / html["file"], ANNUAL_HTML))
    periods = [
        (1, annual, "2024-11-30", "2025-11-28"),
        (1, rows, "2025-11-29", "2026-08-28"),
        (-1, rows, "2024-11-30", "2025-08-29"),
    ]
    if (
        c["financials"]["start"] != periods[1][2]
        or c["financials"]["end"] != periods[1][3]
    ):
        raise ValueError("Adobe current period changed")

    def exact(rs, tag, start, end, dims=()):
        r = select(
            [r for r in rs if r["decimals"] == "-6"], tag, start, end, dims, "USD"
        )
        if r is None:
            raise ValueError(f"Adobe fact missing: {tag} {start} {end}")
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

    facts = {k: combined(tag) for k, tag in TAGS.items()}
    v = lambda key: facts[key]["value"]
    segments = []
    for member, label in [
        ("SubscriptionRevenueMember", "구독"),
        ("ProductMember", "제품"),
        ("ServiceOtherMember", "서비스·기타"),
    ]:
        dims = [("ProductOrServiceAxis", member)]
        sales, cost = combined("Revenues", dims), combined("CostOfRevenue", dims)
        profit = dict(
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
                margin=profit["value"] / sales["value"],
                observedGrowth=sales["components"][1]["fact"]["value"]
                / sales["components"][2]["fact"]["value"]
                - 1,
                evidence=[sales, profit],
                cost=cost,
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
        # The interim statement has an explicit impairment row; the annual
        # statement's complete reconciliation does not include that row.
        impairment = None
        if i:
            impairment = exact(rs, "GoodwillImpairmentLoss", start, end)
            parts.append(
                dict(
                    label="영업권 손상 되돌림",
                    value=impairment["value"],
                    fact=impairment,
                )
            )
        gross = val("revenue") - val("cost")
        operating = (
            gross
            - val("research")
            - val("selling")
            - val("administrative")
            - val("operatingAmortization")
        )
        if (
            sum(p["value"] for p in parts) != val("cfo")
            or operating != val("operatingIncome")
            or sum(s["evidence"][0]["components"][i]["fact"]["value"] for s in segments)
            != val("revenue")
            or sum(s["cost"]["components"][i]["fact"]["value"] for s in segments)
            != val("cost")
        ):
            raise ValueError("Adobe product/income/cash reconciliation failed")
        checks.append(
            dict(
                start=start,
                end=end,
                revenue=val("revenue"),
                grossProfit=gross,
                operatingIncome=operating,
                research=val("research"),
                selling=val("selling"),
                administrative=val("administrative"),
                operatingAmortization=val("operatingAmortization"),
                reportedCfo=val("cfo"),
                components=parts,
                impairment=impairment,
                residual=0,
                incomeResidual=0,
                revenueResidual=0,
                costResidual=0,
            )
        )
    bridge_parts = [
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
    impairment_parts = [
        dict(coefficient=periods[i][0], fact=checks[i]["impairment"]) for i in [1, 2]
    ]
    bridge_parts.append(
        dict(
            label="중간 공시의 추가 영업권 손상 조정",
            value=sum(p["coefficient"] * p["fact"]["value"] for p in impairment_parts),
            fact=dict(sourceUrl=source["primaryUrl"], components=impairment_parts),
        )
    )
    if sum(p["value"] for p in bridge_parts) != v("cfo"):
        raise ValueError("Adobe trailing cash bridge failed")
    # Use the detailed balance sheet's million-dollar figures, not rounded notes.
    stock = [
        dict(coefficient=sign, label=label, fact=exact(rows, tag, None, "2026-08-28"))
        for sign, label, tag in [
            (1, "순매출채권", "AccountsReceivableNetCurrent"),
            (1, "계약자산", "ContractWithCustomerAssetNet"),
            (1, "계약 취득비 순자산", "CapitalizedContractCostNet"),
            (-1, "매입채무", "AccountsPayableCurrent"),
            (-1, "유동 계약부채", "ContractWithCustomerLiabilityCurrent"),
            (-1, "장기 계약부채", "ContractWithCustomerLiabilityNoncurrent"),
        ]
    ]
    stock_net = sum(p["coefficient"] * p["fact"]["value"] for p in stock)
    annual_ppe_da = exact(
        annual, "OtherDepreciationAndAmortization", periods[0][2], periods[0][3]
    )
    annual_contract_amort = exact(
        annual, "CapitalizedContractCostAmortization", periods[0][2], periods[0][3]
    )
    annual_da_components = (
        annual_ppe_da["value"]
        + annual_contract_amort["value"]
        + facts["intangibleAmortization"]["components"][0]["fact"]["value"]
    )
    revenue = v("revenue")
    # Cash-flow D&A/accretion includes a wider scope. Contract amortization stays
    # in selling expense; future net contract-cost investment is in working capital.
    future_da = (
        annual_ppe_da["value"] / facts["revenue"]["components"][0]["fact"]["value"]
        + v("intangibleAmortization") / revenue
    )
    investment = v("ppe") + v("acquisitions")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.25,
        netInterest=-v("interest") / revenue,
        depreciation=future_da,
        workingCapital=stock_net / revenue,
        capexStart=investment / revenue,
        capexEnd=investment / revenue,
        leaseStart=0,
        leaseEnd=0,
        discount=0.12,
        terminal=0.02,
        researchStart=v("research") / revenue,
        researchEnd=v("research") / revenue,
        sellingStart=(v("selling") + v("administrative")) / revenue,
        sellingEnd=(v("selling") + v("administrative")) / revenue,
        otherOperatingStart=v("operatingAmortization") / revenue,
        otherOperatingEnd=v("operatingAmortization") / revenue,
        minority=0,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    annual_index = {p["id"]: p for p in annual_passages}
    if (
        "single operating and reportable segment"
        not in index["8db6695981f504610b20"]["text"]
        or "236 million" not in annual_index["1f5532c977aff2cd0341"]["text"]
    ):
        raise ValueError("Adobe source interpretation changed")
    for item in [annual_source, annual_source.get("indexSource"), html]:
        if item:
            s = dict(item)
            s.setdefault("provider", "SEC")
            s.setdefault("retrievedAt", annual_source["retrievedAt"])
            read_verified(DOCUMENT_ROOT / s["file"], s["sha256"])
            if s["file"] not in {s["file"] for s in c["sources"]}:
                c["sources"].append(s)
    m = dict(
        status="research_workspace",
        version="adobe-product-contract-cost-v1",
        sourcePeriod=["2025-08-30", "2026-08-28"],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        basisLabel="연간+현재9개월−전년9개월 · 제품 구분 원가와 비용 대사",
        groupLabel="단일 보고부문 내 매출 유형",
        growthLabel="9개월 동기 대비",
        marginLabel="매출총이익률",
        grossProfitPath=True,
        grossProfitLabel="매출 유형별 매출총이익",
        sellingLabel="판매마케팅·일반관리비",
        otherOperatingLabel="영업비용 내 인수 무형상각",
        netInterestLabel="총이자 비용",
        capexLabel="설비·인수 순현금",
        leaseLabel="추가 금융리스 원금 가정",
        intro="하나로 통합된 현재 보고부문 안에서 구독·제품·서비스의 매출총이익을 연결하고 공통 연구개발·판매관리·인수상각을 차감합니다. 고객군 매출을 독립 보고부문 이익으로 바꾸지 않습니다.",
        businessCaption="서비스·기타의 매출총손실도 그대로 보존합니다. 통합 보고부문 전후의 연결 매출·원가·비용은 각각 대사하며 옛 사업부 마진을 현재 고객군에 적용하지 않습니다.",
        anchorSummary="미래 설비 상각은 마지막 연간 주석의 설비 상각/매출 비율, 인수 무형상각은 최근1년 비율을 사용합니다. 현금표의 더 넓은 감가·상각·증가분 조정을 그대로 가산하지 않습니다. 계약 취득비 상각은 판매비에 남기고 순자산의 추가 소요만 운전자본에 포함하는 가정입니다. 인수·환율·계약 갱신에 따른 실제 수수료 지급과는 다릅니다.",
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
        observedResidualLabel="인수·계약 취득비·상각 범위는 미래 가정에서 별도 검토",
        anchors=dict(
            workingStockTerms=stock,
            workingStockNet=stock_net,
            shareCompensationReplacement=v("sbc"),
            actualFinanceLeasePrincipal=None,
        ),
        creativeEvidence=dict(
            periods=checks,
            workingStockTerms=stock,
            workingStockNet=stock_net,
            annualPpeDepreciation=annual_ppe_da,
            annualContractAmortization=annual_contract_amort,
            annualDisclosedDaSum=annual_da_components,
            annualCashDa=facts["cashDa"]["components"][0]["fact"]["value"],
            annualDaUnallocated=facts["cashDa"]["components"][0]["fact"]["value"]
            - annual_da_components,
            selectedDepreciationRatio=future_da,
            intangibleAmortization=facts["intangibleAmortization"],
            acquisitions=facts["acquisitions"],
            strategicInvestments=facts["investments"],
            reinvestmentExcludingAcquisitionRatio=v("ppe") / revenue,
            contractCostCurrent=stock[2]["fact"],
            contractCostOpening=exact(
                rows, "CapitalizedContractCostNet", None, "2025-11-28"
            ),
        ),
        cashAnchors=[
            dict(
                label=label,
                period=period,
                value=value,
                sourceUrl=source["primaryUrl"],
                scope=scope,
            )
            for label, period, value, scope in [
                ("설비 취득", "최근1년", v("ppe"), "인수·금융투자와 별도"),
                (
                    "인수 순현금",
                    "최근1년",
                    v("acquisitions"),
                    "취득 현금 차감 후. 총대가와 동일하지 않음",
                ),
                (
                    "전략 장기투자 현금",
                    "최근1년",
                    v("investments"),
                    "사업 취득과 구분. 별도 투자자산 가치 미평가",
                ),
                (
                    "보고 주식보상 되돌림",
                    "최근1년",
                    v("sbc"),
                    "미래 원가·비용에 유지하고 현금으로 가산하지 않음",
                ),
                (
                    "금융리스 실제 원금",
                    "최근1년",
                    None,
                    "연간에는 금융리스 없음. 현재 추가 검토, 초기 미래 가정0",
                ),
            ]
        ],
        passages=[
            index[pid]
            for pid in [
                "8db6695981f504610b20",
                "9f68f65109efc87d459f",
                "0250a4ad42347da984ee",
                "8e255c106f24daef4730",
                "9a8411c4b5b71c44fc0b",
                "204b43dcb8b48ade53a0",
                "ea56d60fddc818427f77",
                "06b442d17b338d835e14",
            ]
        ],
        historicalPassages=[
            dict(annual_index[pid], sourceUrl=html["url"], sourceHash=ANNUAL_HTML)
            for pid in [
                "1f5532c977aff2cd0341",
                "a152c108d4e6fb4cc00c",
                "2a971afd02f3912aac4d",
            ]
        ],
        rules=[
            "2026년부터 단일 보고부문이다. 구독·제품·서비스는 매출 유형이며 고객군이나 옛 보고부문의 이익률이 아니다.",
            "현금표 기타 비현금 항목의 XBRL 음수와 원문 양수 표시를 부호 계수로 연결한다. 세 기간 현금을 모두 대사한다.",
            "미래 주식보상·영업권 손상 비용을 임의로 가산하지 않는다. 관련 미래 비용 제거는 별도 근거가 필요하다.",
            "계약 취득비 상각을 판매비에 남기므로 이 비용을 총상각으로 다시 가산하지 않는다. 순계약 취득비·순계약자산·상세 계약부채를 중복 없이 사용한다.",
            "연간 주석 상각 합계와 현금표 감가·상각·증가분 차이를 보존하며 원인을 임의로 특정하지 않는다. 미래 설비 상각의 관측 기간은 최근1년이 아닌 마지막 연간이다.",
            "Semrush 총 취득대가와 현금표의 전체 인수 순현금을 구분한다. 인수 없는 동일 성장과 정상 유지 투자 수준은 승인되지 않았다.",
        ],
        remaining=[
            "통합 고객군 성장 중 기존 사업·인수·가격·AI 전환의 구분",
            "현재 계약 취득비 상각·현금 지급·인수·환율 대사",
            "현재 설비 상각·금융리스와 미래 투자 강도",
            "장기 투자자산·순초과현금 배분과 차환 조건",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
