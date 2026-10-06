"""Kia's single-business cash path with a separately reconciled warranty ledger."""

from datetime import date, timedelta

from .data import ROOT, canonical, digest, read_verified
from .narrative import load
from .xbrl import company_filing, instance_rows, select

CONSOLIDATED = [
    ("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")
]
INDIRECT = CONSOLIDATED + [
    (
        "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis",
        "ReportedAmountMember",
    )
]
WARRANTY = CONSOLIDATED + [("ClassesOfProvisionsAxis", "WarrantyProvisionMember")]
LEASE = CONSOLIDATED + [
    ("LiabilitiesArisingFromFinancingActivitiesAxis", "LeaseLiabilitiesMember")
]
TAGS = {
    "revenue": ("Revenue", CONSOLIDATED),
    "operatingIncome": ("OperatingIncomeLoss", CONSOLIDATED),
    "pretax": ("ProfitLossBeforeTax", CONSOLIDATED),
    "tax": ("IncomeTaxExpenseContinuingOperations", CONSOLIDATED),
    "netIncome": ("ProfitLoss", CONSOLIDATED),
    "cfo": ("CashFlowsFromUsedInOperatingActivities", CONSOLIDATED),
    "adjustments": ("AdjustmentsForReconcileProfitLoss", INDIRECT),
    "workingCash": ("AdjustmentsForAssetsLiabilitiesOfOperatingActivities", INDIRECT),
    "depreciation": ("AdjustmentsForDepreciationExpense", INDIRECT),
    "amortization": ("AdjustmentsForAmortisationExpense", INDIRECT),
    "warrantyAccrual": ("AdjustmentsForProductWarrantyExpenses", INDIRECT),
    "warrantyUse": ("ProvisionUsedOtherProvisions", WARRANTY),
    "warrantyCfUse": (
        "AdjustmentsForIncreaseDecreaseInProvisionsForProductWarranties",
        INDIRECT,
    ),
    "warrantyAdded": ("AdditionalProvisionsOtherProvisions", WARRANTY),
    "warrantyOther": (
        "IncreaseDecreaseThroughTransfersAndOtherChangesOtherProvisions",
        WARRANTY,
    ),
    "warrantySelling": (
        "ProductWarrantyExpensesRecoverySellingGeneralAdministrativeExpenses",
        INDIRECT,
    ),
    "leaseCash": (
        "IncreaseDecreaseThroughFinancingCashFlowsLiabilitiesArisingFromFinancingActivities",
        LEASE,
    ),
    "capex": (
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        CONSOLIDATED,
    ),
    "intangibles": (
        "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
        CONSOLIDATED,
    ),
    "interestIncome": ("InterestReceivedClassifiedAsOperatingActivities", CONSOLIDATED),
    "interestExpense": ("InterestPaidClassifiedAsOperatingActivities", CONSOLIDATED),
    "dividends": ("DividendsReceivedClassifiedAsOperatingActivities", CONSOLIDATED),
    "cashTaxes": ("IncomeTaxesPaidRefundClassifiedAsOperatingActivities", CONSOLIDATED),
    "minority": ("ProfitLossAttributableToNoncontrollingInterests", CONSOLIDATED),
}
TRADE = [
    "AdjustmentsForDecreaseIncreaseInTradeAccountReceivable",
    "AdjustmentsForDecreaseincreaseInOtherReceivables",
    "AdjustmentsForDecreaseIncreaseInInventories",
    "AdjustmentsForIncreaseDecreaseInTradeAccountPayable",
    "AdjustmentsForIncreasedecreaseInAdvancesCustomers",
    "AdjustmentsForIncreasedecreaseInOtherPayables",
    "AdjustmentsForIncreasedecreaseInAccruedExpenses",
]
PASSAGES = [
    "4e114e264abff90f2888",  # Management's sales/margin explanation.
    "1b3defb04d690ebee348",  # One operating business, not product profit segments.
    "adcda2cdcd9f94f7191e",  # Product table is not consolidated realized ASP.
    "0773d8851d5a7bae67c6",  # Warranty recognition at sale.
    "ded4d625625f794cb73f",
    "07a2e3b607b357520333",
    "700dc4078ebc9a270ee6",
    "8b0430ef562bcf3b4a40",
    "81dee76cbb965cb96c89",
    "ba33eb2ba6131e928753",  # Indirect cash-flow reconciliation context.
    "6b9e019d395da8336e0f",  # Lease financing cash movement.
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if (
        meta.get("accession") != "20260916000427"
        or meta.get("evidenceHash")
        != "3024eea2a4e4db17b0a25408fe8261074b2764bbba52450633174aa85b2f518a"
    ):
        return dict(
            status="source_review_required",
            reason="기아의 새 공시에서 판매보증·현금·사업 범위를 다시 대사해야 합니다.",
        )
    f = c["financials"]
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if (
        core["accession"] != "20260312001224"
        or core["sourceHash"]
        != "1b8872810068810fdbaafef41c375df505755bbd479fe9893d4d8889f5ac30c3"
    ):
        return dict(
            status="source_review_required",
            reason="기아의 연간 기준 공시가 변경돼 기간 연결 검토가 필요합니다.",
        )
    source, rows = company_filing(c, as_of)
    if (
        source["sha256"]
        != "39e3a3539751d38b85123c98cc565ec00b9c488299101bf949ebc99ccf7b2fcd"
    ):
        return dict(
            status="source_review_required",
            reason="기아 XBRL 원문이 변경돼 수치 대사 검토가 필요합니다.",
        )
    annual_source = next(s for s in c["sources"] if s["file"] == core["sourceFile"])
    annual = instance_rows(
        read_verified(ROOT / annual_source["file"], core["sourceHash"]),
        c,
        annual_source,
        core["accession"],
        core["filedAt"],
    )
    periods = [
        (1, annual, core["start"], core["end"]),
        (1, rows, f["start"], f["end"]),
        (-1, rows, f["priorStart"], f["priorEnd"]),
    ]

    def exact(rs, tag, dims, start, end):
        result = select(rs, tag, start, end, dims, "KRW")
        if result is None:
            raise ValueError("Kia cash source missing: " + tag)
        return result

    def combine(tag, dims):
        components = [
            dict(coefficient=k, fact=exact(rs, tag, dims, start, end))
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in components),
            components=components,
            derived=True,
            tag=tag,
            unit="KRW",
            sourceUrl=source["url"],
        )

    facts = {key: combine(*spec) for key, spec in TAGS.items()}
    trade = [combine(tag, INDIRECT) for tag in TRADE]
    v = lambda key: facts[key]["value"]
    checks, warranty_periods = [], []
    for i, (_, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        if val("pretax") - val("tax") != val("netIncome"):
            raise ValueError("Kia earnings do not reconcile")
        summed = (
            val("netIncome")
            + val("adjustments")
            + val("workingCash")
            + val("interestIncome")
            - val("interestExpense")
            + val("dividends")
            - val("cashTaxes")
        )
        if val("cfo") != summed or val("warrantyUse") != -val("warrantyCfUse"):
            raise ValueError("Kia cash or warranty utilization does not reconcile")
        opening = exact(
            rs,
            "OtherProvisions",
            WARRANTY,
            None,
            (date.fromisoformat(start) - timedelta(days=1)).isoformat(),
        )
        closing = exact(rs, "OtherProvisions", WARRANTY, None, end)
        residual = closing["value"] - (
            opening["value"]
            + val("warrantyAdded")
            - val("warrantyUse")
            + val("warrantyOther")
        )
        if residual:
            raise ValueError("Kia warranty roll-forward does not reconcile")
        warranty_periods.append(
            dict(
                start=start,
                end=end,
                opening=opening,
                closing=closing,
                added=val("warrantyAdded"),
                used=val("warrantyUse"),
                other=val("warrantyOther"),
                cashAdjustment=val("warrantyAccrual"),
                sellingExpense=val("warrantySelling"),
                residual=residual,
            )
        )
        checks.append(dict(start=start, end=end, reportedCfo=val("cfo"), residual=0))

    def part(label, value, *keys):
        components = [
            dict(coefficient=p["coefficient"] * sign, fact=p["fact"])
            for key, sign in keys
            for p in facts[key]["components"]
        ]
        return dict(
            label=label,
            value=value,
            fact=dict(sourceUrl=source["url"], components=components),
        )

    parts = [
        part("연결 영업이익", v("operatingIncome"), ("operatingIncome", 1)),
        part(
            "세전이익과 영업이익 차이",
            v("pretax") - v("operatingIncome"),
            ("pretax", 1),
            ("operatingIncome", -1),
        ),
        part("손익 법인세", -v("tax"), ("tax", -1)),
        part(
            "현금표 감가상각·상각 조정",
            v("depreciation") + v("amortization"),
            ("depreciation", 1),
            ("amortization", 1),
        ),
        part("현금표 판매보증비 조정", v("warrantyAccrual"), ("warrantyAccrual", 1)),
        part("현금표 법인세 비용 되돌림", v("tax"), ("tax", 1)),
        part(
            "그 밖의 순이익 조정 잔액",
            v("adjustments")
            - v("depreciation")
            - v("amortization")
            - v("warrantyAccrual")
            - v("tax"),
            ("adjustments", 1),
            ("depreciation", -1),
            ("amortization", -1),
            ("warrantyAccrual", -1),
            ("tax", -1),
        ),
        part("판매보증충당부채 사용", -v("warrantyUse"), ("warrantyUse", -1)),
        part(
            "보증 사용 외 영업자산·부채 변동",
            v("workingCash") + v("warrantyUse"),
            ("workingCash", 1),
            ("warrantyUse", 1),
        ),
        part("이자 유입", v("interestIncome"), ("interestIncome", 1)),
        part("이자 지급", -v("interestExpense"), ("interestExpense", -1)),
        part("배당 유입", v("dividends"), ("dividends", 1)),
        part("법인세 지급", -v("cashTaxes"), ("cashTaxes", -1)),
    ]

    revenue = v("revenue")
    if revenue != c["trailingYear"]["values"]["revenue"]["value"] or sum(
        p["value"] for p in parts
    ) != v("cfo"):
        raise ValueError("Kia trailing revenue/cash scope differs")
    # Exclude provisions and retirement payments from the sales-linked proxy.
    working_effect = sum(p["components"][1]["fact"]["value"] for p in trade)
    revenue_increase = (
        f["current"]["revenue"]["value"] - f["previous"]["revenue"]["value"]
    )
    if revenue_increase <= 0 or any(
        facts["leaseCash"]["components"][i]["fact"]["value"] > 0 for i in range(3)
    ):
        raise ValueError("Review Kia growth proxy or lease cash direction")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=v("operatingIncome") / revenue)
        ],
        tax=v("tax") / v("pretax"),
        netInterest=(v("interestIncome") - v("interestExpense")) / revenue,
        depreciation=(v("depreciation") + v("amortization")) / revenue,
        workingCapital=-working_effect / revenue_increase,
        capexStart=(v("capex") + v("intangibles")) / revenue,
        capexEnd=(v("capex") + v("intangibles")) / revenue,
        leaseStart=-v("leaseCash") / revenue,
        leaseEnd=-v("leaseCash") / revenue,
        warrantyAccrual=v("warrantyAccrual") / revenue,
        warrantyUseStart=v("warrantyUse") / revenue,
        warrantyUseEnd=v("warrantyUse") / revenue,
        discount=0.12,
        terminal=0.02,
    )
    corpus = load(c)
    index = {p["id"]: p for p in corpus["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("Kia business source passages changed")
    observed = (
        v("cfo") - v("capex") - v("intangibles") + v("leaseCash") - v("dividends")
    )
    m = dict(
        status="research_workspace",
        version="kia-operating-cash-path-v1",
        reservePath=True,
        sourcePeriod=["2025-07-01", "2026-06-30"],
        accession=meta["accession"],
        corpusHash=meta["evidenceHash"],
        basisLabel="최근 1년 공시 연결에서 출발",
        growthLabel="최근 반기 전년 대비",
        currency="KRW",
        displayScale=1e12,
        displayUnit="조 원",
        intro="연결 단일 사업의 매출·마진에서 세금·상각·영업자산·유형 및 무형 투자·리스와 판매보증의 현금 부담을 계산합니다.",
        businessCaption="승용·RV·상용별 이익은 공시되지 않습니다. 제품 표의 단순 평균 가격과 별도 범위 매출을 연결 판매량×단가로 사용하지 않습니다. 관세·인센티브·차종 구성·환율은 마진 가정 안에서 조정해야 합니다.",
        capexLabel="유형·무형 현금 취득",
        leaseLabel="리스 원금",
        observedResidualLabel="영업현금 − 유형·무형 취득 − 리스 원금 − 배당 유입",
        anchorSummary="현금표의 판매보증비 조정, 판관비의 판매보증비, 충당부채 증가액은 서로 다릅니다. 차액을 환율이나 일회성 비용으로 임의 배분하지 않습니다. 영업자금 계수는 같은 반기 매출 증가와 7개 매출채권·재고·채무 항목에서 계산하며 보증·퇴직 급여를 제외합니다.",
        passages=[index[i] for i in PASSAGES],
        segments=[
            dict(
                id="vehicles",
                label="완성차·부품 및 관련 용역",
                revenue=revenue,
                margin=v("operatingIncome") / revenue,
                observedGrowth=f["current"]["revenue"]["value"]
                / f["previous"]["revenue"]["value"]
                - 1,
                evidence=[p["fact"] for p in facts["revenue"]["components"]],
            )
        ],
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        warranty=dict(
            periods=warranty_periods,
            trailingAdded=v("warrantyAdded"),
            trailingAdjustment=v("warrantyAccrual"),
            trailingSellingExpense=v("warrantySelling"),
            trailingUse=v("warrantyUse"),
            additionsLessCashAdjustment=v("warrantyAdded") - v("warrantyAccrual"),
        ),
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=observed,
        ),
        anchors=dict(
            workingCashEffect=working_effect,
            revenueIncrease=revenue_increase,
            tradeFacts=trade,
            minorityProfit=v("minority"),
        ),
        rules=[
            "기초 실적은 연간+당기 반기−전년 반기입니다. 반기 수치를 두 배 하거나 연결 단일 사업을 가상의 제품별 이익으로 나누지 않습니다.",
            "미래 영업이익률에는 보고 판매보증비가 포함됩니다. 별도 보증비 조정은 현금표의 되돌림 비율을 유지하는 가정이며 손익 비용 전액과 같지 않습니다. 충당부채 사용 가정은 다시 별도 차감합니다.",
            "충당부채 사용액은 세 기간 모두 현금표 보증 조정의 반대 부호와 일치합니다. 고객에게 그 기간 직접 지급한 현금이나 해당 연도 판매분의 결함률과 동일하다고 단정하지 않습니다.",
            "미래 보증비 조정과 충당부채 사용을 매출 비율로 가정합니다. 보증 잔액·판매 연식·청구 빈도에 기반한 지급 모형은 아니며, 사용 비율을 높인 별도 스트레스가 필요합니다.",
            "미래 상각은 현금표 감가상각·무형 상각 비율입니다. 유형과 무형의 현금 취득을 모두 차감합니다. 개발비 자산화·사용권 상각·비현금 취득 차이는 별도 정상화가 필요합니다.",
            "리스 원금은 리스부채 변동 주석의 재무현금 감소액입니다. 신규 리스 비현금 증가를 다시 차감하지 않습니다. 이자 지급은 순이자 가정에 포함합니다.",
            "순이자는 수취·지급 현금 비율을 유지합니다. 관계기업 손익·수취 배당·평가 및 환산 손익은 미래에 별도로 더하지 않으며 금융자산 가치를 배분하지 않습니다.",
            "최근 반기의 매입채무·미지급비용 증가로 매출 증가에 대한 영업자금 소요 계수가 음수입니다. 미래 성장 때 자동 현금이 생기는 정상 구조로 승인하지 않으며 영 또는 양수의 자금 소요와 함께 비교해야 합니다.",
            "세율은 보고 법인세 비용/세전이익에서 출발합니다. 실제 현금 납세율 예측은 아닙니다. 손실에 대한 즉시 세금 환급은 가정하지 않습니다.",
            "퇴직·기타 충당금 등 별도 비현금 조정을 미래에 되돌리지 않습니다. 보고 비용을 현금 비용 대용으로 유지하는 가정이며 공시 영업현금과 미래 현금은 다릅니다.",
            "비지배지분의 최근 1년 손실을 보통주 현금에 더하지 않습니다. 미래 비지배 현금 유출은 영, 비리스 순차입은 영/차환의 연구자 가정입니다. 주당 값은 이 추가 범위를 충족할 때의 조건부 값입니다.",
            "기초 성장 0%·현재 마진 유지, 요구수익률 12%·영구성장 2%는 전망이나 투자 의견이 아닙니다. 말기에도 매출·보증·세금·자금·투자를 다시 계산합니다.",
        ],
        remaining=[
            "보증비·충당부채 증가·현금표 조정 차액의 상세 대사와 판매 연식별 청구",
            "관세·인센티브·차종 구성·환율의 마진 영향 금액",
            "개발비 자산화와 전동화 투자·대체 투자",
            "관계기업 출자 약정·금융자산·비지배지분 배분과 차환",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
