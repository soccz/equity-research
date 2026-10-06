"""Salesforce: subscription economics, contractual funding and lease cash."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "0001108524-26-000190"
CORPUS = "5165779ddd9370b3330a490f9a8a187eef41562cd917fdd39d8a4d76c7440e58"
SOURCE = "c9a819d93fa9ffe1d05c4d6dcff1372a8cf2995da8bd61ac161b1ba1d98147b2"
ANNUAL = "0001108524-26-000060"
ANNUAL_SHA = "ad3ca1752bb082f9d6f8f4bad260a0c377b66bf1c13edafc08070933524e3d24"
ANNUAL_HTML = "b64ff7f91a9cdbe0adb9530b00a9f3235bd688e979a15d5be443cbf482c1c4c8"
TAGS = dict(
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    cost="CostOfGoodsAndServicesSold",
    operatingIncome="OperatingIncomeLoss",
    netIncome="NetIncomeLoss",
    research="ResearchAndDevelopmentExpense",
    selling="SellingAndMarketingExpense",
    administrative="GeneralAndAdministrativeExpense",
    restructuring="RestructuringCharges",
    da="DepreciationAndAmortization",
    commissionAmortization="CapitalizedContractCostAmortization",
    sbc="ShareBasedCompensation",
    investmentProfit="GainLossOnInvestments",
    receivables="IncreaseDecreaseInAccountsReceivable",
    commissions="IncreaseDecreaseInCapitalizedContractCosts",
    otherAssets="IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",
    payables="IncreaseDecreaseInAccountsPayableAndAccruedLiabilities",
    operatingLeaseChange="IncreaseDecreaseInOperatingLeaseLiability",
    deferredRevenue="IncreaseDecreaseInContractWithCustomerLiability",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    ppe="PaymentsToAcquirePropertyPlantAndEquipment",
    acquisitions="PaymentsToAcquireBusinessesNetOfCashAcquired",
    investments="PaymentsToAcquireLongtermInvestments",
)
CASH = [
    ("netIncome", "순이익", 1),
    ("da", "설비·무형·사용권 상각·손상", 1),
    ("commissionAmortization", "계약 취득비 상각", 1),
    ("sbc", "주식보상 되돌림", 1),
    ("investmentProfit", "전략 투자 손익 제거", -1),
    ("receivables", "매출채권 현금 효과", -1),
    ("commissions", "계약 취득비 현금", -1),
    ("otherAssets", "선급·기타 영업자산", -1),
    ("payables", "매입·미지급·기타 부채", 1),
    ("operatingLeaseChange", "운영리스 부채 현금표 조정", 1),
    ("deferredRevenue", "계약부채 현금 효과", 1),
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="Salesforce의 제품 구분·인수·현재 차입금과 리스 현금 범위를 새 공시에서 다시 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    manifest = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}-xbrl.manifest.json").read_text()
    )
    html = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}.manifest.json").read_text()
    )
    if (
        source["sha256"] != SOURCE
        or manifest["sha256"] != ANNUAL_SHA
        or html["sha256"] != ANNUAL_HTML
        or any(
            x["cik"] != c["cik"] or x["accession"] != ANNUAL for x in [manifest, html]
        )
    ):
        raise ValueError("Salesforce source identity changed")
    annual = instance_rows(
        read_verified(DOCUMENT_ROOT / manifest["file"], ANNUAL_SHA),
        c,
        manifest,
        ANNUAL,
        "2026-03-02",
    )
    aps = extract(read_verified(DOCUMENT_ROOT / html["file"], ANNUAL_HTML))
    annual_index = {p["id"]: p for p in aps}
    if (
        "584" not in annual_index["61f260e4b2396746dadf"]["text"]
        or "367" not in annual_index["bd5cdd1a0d31cb9602d3"]["text"]
    ):
        raise ValueError("Salesforce annual financing/lease source captions changed")
    periods = [
        (1, annual, "2025-02-01", "2026-01-31"),
        (1, rows, "2026-02-01", "2026-07-31"),
        (-1, rows, "2025-02-01", "2025-07-31"),
    ]
    if (c["financials"]["start"], c["financials"]["end"]) != periods[1][2:]:
        raise ValueError("Salesforce period changed")

    def exact(rs, tag, start, end, dims=()):
        r = select(
            [x for x in rs if x["decimals"] == "-6"], tag, start, end, dims, "USD"
        )
        if r is None:
            raise ValueError(f"Salesforce fact missing: {tag} {start} {end}")
        return r

    def combine(parts):
        return dict(
            value=sum(x["coefficient"] * x["fact"]["value"] for x in parts),
            components=parts,
            sourceUrl=source["primaryUrl"],
            unit="USD",
        )

    def combined(tag, dims=()):
        return combine(
            [
                dict(coefficient=k, fact=exact(rs, tag, start, end, dims))
                for k, rs, start, end in periods
            ]
        )

    facts = {key: combined(tag) for key, tag in TAGS.items()}
    facts["financingPrincipal"] = combine(
        [
            dict(
                coefficient=k,
                fact=exact(rs, "FinanceLeasePrincipalPayments", start, end),
            )
            for i, (k, rs, start, end) in enumerate(periods)
        ]
    )
    v = lambda key: facts[key]["value"]
    segments = []
    for member, label in [
        ("SubscriptionandSupportMember", "구독·지원"),
        ("ProfessionalServicesandOtherMember", "전문서비스·기타"),
    ]:
        dims = [("ProductOrServiceAxis", member)]
        sales = combined(TAGS["revenue"], dims)
        cost = combined(TAGS["cost"], dims)
        gross = combine(
            sales["components"]
            + [
                dict(coefficient=-p["coefficient"], fact=p["fact"])
                for p in cost["components"]
            ]
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
        gross = val("revenue") - val("cost")
        op = (
            gross
            - val("research")
            - val("selling")
            - val("administrative")
            - val("restructuring")
        )
        if (
            sum(x["value"] for x in parts) != val("cfo")
            or op != val("operatingIncome")
            or sum(s["evidence"][0]["components"][i]["fact"]["value"] for s in segments)
            != val("revenue")
            or sum(
                s["costEvidence"]["components"][i]["fact"]["value"] for s in segments
            )
            != val("cost")
        ):
            raise ValueError("Salesforce cash/product/income reconciliation failed")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=val("cfo"),
                netIncome=val("netIncome"),
                operatingIncome=op,
                investmentProfit=val("investmentProfit"),
                da=val("da"),
                commissionAmortization=val("commissionAmortization"),
                commissionCash=val("commissions"),
                financingPrincipal=val("financingPrincipal"),
                operatingLeaseChange=val("operatingLeaseChange"),
                components=parts,
                residual=0,
                revenueResidual=0,
                incomeResidual=0,
            )
        )
    ps = load(c)["passages"]
    index = {p["id"]: p for p in ps}
    header = next(i for i, p in enumerate(ps) if p["id"] == "ce04673bdf468962fc6d")
    debt = []
    for p in ps[header + 1 : header + 17]:
        cells = [t.strip().replace("$", "").strip() for t in p["text"].split("|")]
        cells = [x for x in cells if x]
        if len(cells) != 5:
            raise ValueError("Salesforce debt table shape changed")
        label, maturity, principal, kind, rate = cells
        principal = float(principal.replace(",", "")) * 1e6
        if rate == "N/A":
            if principal != 0:
                raise ValueError("Salesforce actual borrowing lacks rate")
            rate = None
        else:
            rate = float(rate.rstrip("%")) / 100
        debt.append(
            dict(
                label=label,
                maturity=maturity,
                principal=principal,
                rate=rate,
                type=kind,
                annualInterest=None if rate is None else principal * rate,
                source=p,
            )
        )
    debt_principal = sum(d["principal"] for d in debt)
    debt_interest = sum(d["annualInterest"] or 0 for d in debt)
    if debt_principal != 39500000000 or abs(debt_interest - 1824275000) > 1:
        raise ValueError("Salesforce reviewed debt contract changed")
    lease_interest = exact(
        annual, "FinanceLeaseInterestExpense", periods[0][2], periods[0][3]
    )
    total_interest = debt_interest + lease_interest["value"]
    if "right-of-use assets" not in index["d23dc3e2c9f3f15e7832"]["text"]:
        raise ValueError("Salesforce cash D&A scope changed")
    stock = [
        dict(coefficient=sign, label=label, fact=exact(rows, tag, None, "2026-07-31"))
        for sign, label, tag in [
            (1, "순매출채권", "AccountsReceivableNetCurrent"),
            (1, "계약자산", "ContractWithCustomerAssetNet"),
            (-1, "유동 계약부채", "ContractWithCustomerLiabilityCurrent"),
        ]
    ]
    working = sum(p["coefficient"] * p["fact"]["value"] for p in stock)
    # Operating lease cash-flow adjustment accompanies the ROU addback. It is
    # not the disclosed total operating lease payment or a separate finance debt.
    operating_lease_proxy = -v("operatingLeaseChange")
    if operating_lease_proxy < 0:
        raise ValueError("Review lease funding inflow before using a payment proxy")
    annual_lease_principal = exact(
        annual,
        "PrincipalPaymentsFinanceLeasesAndFinanceObligations",
        periods[0][2],
        periods[0][3],
    )
    annual_financing_gap = (
        facts["financingPrincipal"]["components"][0]["fact"]["value"]
        - annual_lease_principal["value"]
    )
    lease_total = operating_lease_proxy + v("financingPrincipal")
    investment = v("ppe") + v("acquisitions") + v("commissions")
    revenue = v("revenue")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.25,
        netInterest=-total_interest / revenue,
        depreciation=(v("da") + v("commissionAmortization")) / revenue,
        workingCapital=working / revenue,
        capexStart=investment / revenue,
        capexEnd=investment / revenue,
        leaseStart=lease_total / revenue,
        leaseEnd=lease_total / revenue,
        discount=0.12,
        terminal=0.02,
        researchStart=v("research") / revenue,
        researchEnd=v("research") / revenue,
        sellingStart=v("selling") / revenue,
        sellingEnd=v("selling") / revenue,
        otherOperatingStart=(v("administrative") + v("restructuring")) / revenue,
        otherOperatingEnd=(v("administrative") + v("restructuring")) / revenue,
        minority=0,
    )
    bridge_parts = [
        dict(
            label=label,
            value=sign * v(key),
            fact=combine(
                [
                    dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                    for p in facts[key]["components"]
                ]
            ),
        )
        for key, label, sign in CASH
    ]
    if sum(p["value"] for p in bridge_parts) != v("cfo"):
        raise ValueError("Salesforce trailing cash bridge failed")
    for item in [manifest, manifest.get("indexSource"), html]:
        if item:
            s = dict(item)
            s.setdefault("provider", "SEC")
            s.setdefault("retrievedAt", manifest["retrievedAt"])
            read_verified(DOCUMENT_ROOT / s["file"], s["sha256"])
            if s["file"] not in {x["file"] for x in c["sources"]}:
                c["sources"].append(s)
    price_hold = "금융의무 원금의 연간 현금표와 금융리스 주석 사이 2.17억 달러 차이 및 관련 이자 범위가 아직 대사되지 않았습니다. 전체 현금표 지급은 보존하되 이 현금 모델의 주당 가치·역산은 보류합니다."
    security = dict(
        c["valuation"]["security"],
        status="unresolved",
        marketCapProxy=None,
        issues=list(c["valuation"]["security"].get("issues", [])) + [price_hold],
    )
    m = dict(
        status="research_workspace",
        version="salesforce-contract-debt-lease-v1",
        sourcePeriod=["2025-08-01", "2026-07-31"],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        basisLabel="세 기간 매출총이익·현금 대사 / 현재 채무 계약",
        growthLabel="반기 동기 대비 / 인수 포함",
        groupLabel="단일 부문 내 두 매출 구분",
        marginLabel="매출총이익률",
        grossProfitPath=True,
        sellingLabel="판매마케팅",
        otherOperatingLabel="일반관리·구조조정",
        netInterestLabel="현재 차입금 연이자·연간 리스이자 대용",
        capexLabel="설비·인수·판매수수료 현금",
        leaseLabel="운영리스 조정·금융의무 원금 가정",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=security,
        priceHoldReason=price_hold,
        intro="구독·지원과 전문서비스의 매출총이익에서 공통 비용을 차감합니다. 인수·영업권 및 고객 관계 상각, 계약 취득비, 리스와 최근 차입금의 자금 비용을 각각 현금 가정에 연결합니다.",
        businessCaption="하나의 영업부문 안에서 공시한 두 매출 구분입니다. 2026년 새 제품군 구분을 과거 독립 사업부 마진으로 만들지 않습니다. AI·인수 매출 설명과 보고 손익을 구분합니다.",
        anchorSummary="미래 자금 소요는 기말 순채권+계약자산−유동 고객선수를 최근1년 매출로 나눈 좁은 대용입니다. 미분리 매입·미지급·리스 부채는 합치지 않습니다. 계약 취득비 취득과 리스 현금표 조정은 각각 따로 차감합니다. 채무 원금·현재 금리가 유지되고 만기에는 차환한다는 가정이며 정상 이자·현금의 승인이 아닙니다.",
        bridge=dict(
            parts=bridge_parts,
            periods=checks,
            reportedCfo=v("cfo"),
            residual=0,
            cashAfterInvestmentLeaseSbc=None,
        ),
        observedResidualLabel="보고 현금·인수·계약 취득비·리스와 미래 부담 가정을 분리",
        anchors=dict(
            workingStockTerms=stock,
            workingStockNet=working,
            actualFinanceLeasePrincipal=None,
            financingObligationPrincipal=v("financingPrincipal"),
            operatingLeaseCashAdjustment=operating_lease_proxy,
            shareCompensationReplacement=v("sbc"),
        ),
        salesforceEvidence=dict(
            periods=checks,
            debt=debt,
            debtPrincipal=debt_principal,
            debtAnnualInterest=debt_interest,
            annualFinanceLeaseInterest=lease_interest,
            annualInterestProxy=total_interest,
            floatingPrincipal=sum(
                d["principal"] for d in debt if d["type"] == "Floating"
            ),
            workingStockTerms=stock,
            workingStockNet=working,
            operatingLeaseCashAdjustment=operating_lease_proxy,
            financeLeasePrincipal=None,
            financingObligationPrincipal=v("financingPrincipal"),
            annualFinanceLeasePrincipal=annual_lease_principal,
            annualFinancingDifference=annual_financing_gap,
            leaseTotalProxy=lease_total,
            commissionCash=facts["commissions"],
            commissionAmortization=facts["commissionAmortization"],
            acquisitions=facts["acquisitions"],
            strategicInvestments=facts["investments"],
            reinvestmentExcludingAcquisitionRatio=(v("ppe") + v("commissions"))
            / revenue,
        ),
        cashAnchors=[
            dict(
                label=label,
                period=period,
                value=value,
                scope=scope,
                sourceUrl=(
                    lease_interest["sourceUrl"]
                    if label == "연간 금융리스 발생이자"
                    else source["primaryUrl"]
                ),
            )
            for label, period, value, scope in [
                ("설비 취득", "최근1년", v("ppe"), "인수·판매수수료와 별도"),
                ("인수 순현금", "최근1년", v("acquisitions"), "총 취득대가와 구분"),
                (
                    "계약 취득비 현금",
                    "최근1년",
                    v("commissions"),
                    "상각 가산 후 미래 재투자에서 한 번 차감",
                ),
                (
                    "운영리스 현금표 부채 조정 대용",
                    "최근1년",
                    operating_lease_proxy,
                    "리스 총 현금 지급액이 아님. 사용권 상각 가산에 대응하는 초기 가정",
                ),
                (
                    "금융의무 원금",
                    "최근1년",
                    v("financingPrincipal"),
                    "원문 현금표의 넓은 범위. 연간 금융리스 주석과의 차이를 보존",
                ),
                (
                    "현재 차입금 계약 연이자",
                    "2026-07-31",
                    debt_interest,
                    "현재 원금·현재 고정/변동금리, 차환·수수료 제외",
                ),
                (
                    "연간 금융리스 발생이자",
                    "2025-02-01–2026-01-31",
                    lease_interest["value"],
                    "최근1년 금액 미확인. 미래 별도 대용에 사용",
                ),
            ]
        ],
        passages=[
            index[pid]
            for pid in [
                "40f027a30ef97f3ff368",
                "d23dc3e2c9f3f15e7832",
                "2635dd6a9a6c88c3a5e6",
                "a8e34d7b84738731e770",
                "8017f3e76fadfb1f13ff",
                "52de58072c70afef9963",
                "f59da423c943cc317adb",
                "62a160e224ee2dd4fc38",
                "5ab8a0f7fb6d2d8decb1",
                "2a8a9fc14350bbb4ed6f",
                "287ff3ce2d63ecb41f26",
            ]
        ],
        historicalPassages=[
            dict(annual_index[pid], sourceUrl=html["url"], sourceHash=ANNUAL_HTML)
            for pid in [
                "61f260e4b2396746dadf",
                "bd5cdd1a0d31cb9602d3",
                "68d539875f410d2e5310",
            ]
        ],
        rules=[
            "세 기간의 구독·지원/전문서비스 매출·원가와 공통 비용, 순이익에서 영업현금까지를 대사한다.",
            "전략 투자 이익은 순이익과 영업현금 대사에서 제거하고 미래 영업이익에 넣지 않는다. 별도 전략 투자자산 가치는 미평가다.",
            "사용권 상각·손상이 현금표 감가·상각에 들어 있으므로 대응 운영리스 부채 현금 조정을 누락하지 않는다. 이 부채 조정은 전체 리스 지급이나 실제 원금으로 명명하지 않는다.",
            "판매수수료 자산 상각을 되돌리면 취득 현금을 별도로 차감한다. 기말 계약 취득비 잔액을 운전자본에 다시 합치지 않는다.",
            "최근1년 과거 이자만 반복하지 않고 현재 채무 원금·표시금리의 연이자를 사용한다. 금융리스는 마지막 연간 이자만 확인됐으며 현재 범위 재검토가 필요하다.",
            "인수 매출 기여에서 별도 인수 비용을 추정해 유기 성장 마진을 만들지 않는다. 회사의 고객 이탈 지표에서 제외한 인수·서비스 범위를 보존한다.",
            "운영 자산 상각·손상을 되돌린 초기 경로가 미래 유지·확장 투자의 충분성을 입증하지 않는다. 큰 인수와 차환 없는 성장 경로는 별도 근거를 요구한다.",
        ],
        remaining=[
            "인수 제외 고객군 성장·추론 원가·갱신의 실제 분해",
            "연간 금융의무 원금584m과 금융리스 주석367m 차이217m 및 관련 이자 범위 확인",
            "현재 금융리스 이자·운영리스 총지급 및 사용권 손상 구분",
            "현재 채무 만기별 상환·차환과 변동금리·수수료",
            "전략 투자·초과현금 가치와 공통 미지급 자금 범위",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
