"""Alphabet source-bound segment, corporate-cost and cash-path workspace."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

CURRENT = "0001652044-26-000071"
ANNUAL = "0001652044-26-000018"
CURRENT_SHA = "1376c154c799dd52e1c2be723bfaf269fc204191d2205eaab7a54122a23b8f4b"
ANNUAL_SHA = "03df38b77f4e4045efb3a100ddbadcc752494d916beb523897439c1484f87df2"
CORPUS = "e2a10e7bad8176d88c02d7cefc16085de2441bca39326d74084e0f2db254a625"
ROLES = [
    ("OperatingIncomeLoss", "연결 영업이익", 1),
    ("NonoperatingIncomeExpense", "영업외 손익", 1),
    ("IncomeTaxExpenseBenefit", "법인세 비용", -1),
    ("Depreciation", "설비 감가상각", 1),
    ("ShareBasedCompensation", "주식보상 되돌림", 1),
    ("DeferredIncomeTaxesAndTaxCredits", "이연법인세 조정", 1),
    ("DebtAndEquitySecuritiesGainLoss", "채무·지분 증권 이익 되돌림", -1),
    ("OtherNoncashIncomeExpense", "기타 비현금 조정", -1),
    ("IncreaseDecreaseInAccountsReceivable", "매출채권 변동", -1),
    ("IncreaseDecreaseInIncomeTaxes", "법인세 자산·부채 변동", 1),
    ("IncreaseDecreaseInOtherOperatingAssets", "기타 영업자산 변동", -1),
    ("IncreaseDecreaseInAccountsPayable", "매입채무 변동", 1),
    ("IncreaseDecreaseInAccruedLiabilities", "미지급·기타 부채 변동", 1),
    ("IncreaseDecreaseInContractWithCustomerLiability", "선수 수익 변동", 1),
]
TAGS = {
    "cfo": "NetCashProvidedByUsedInOperatingActivities",
    "hedgeRevenue": "RevenueNotFromContractWithCustomer",
    "reportedRevenue": "Revenues",
    "operatingIncome": "OperatingIncomeLoss",
    "pretax": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "tax": "IncomeTaxExpenseBenefit",
    "netIncome": "NetIncomeLoss",
    "nonoperating": "NonoperatingIncomeExpense",
    "depreciation": "Depreciation",
    "sbc": "ShareBasedCompensation",
    "interestIncome": "InterestIncomeOther",
    "interestExpense": "InterestExpenseNonoperating",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
    "leaseReported": "FinanceLeasePrincipalPayments",
}


def build(c, as_of):
    h = c.get("segmentHistory") or {}
    meta = c.get("narrative") or {}
    if (
        meta.get("accession") != CURRENT
        or meta.get("evidenceHash") != CORPUS
        or h.get("status") != "ready"
    ):
        return dict(
            status="source_review_required",
            reason="Alphabet의 사업·공통비·현금·리스 범위를 새 공시에서 다시 확인해야 합니다.",
        )
    source, current = company_filing(c, as_of)
    annual_source = h["review"]["annualSource"]
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if (
        source["sha256"] != CURRENT_SHA
        or annual_source["sha256"] != ANNUAL_SHA
        or core["accession"] != ANNUAL
        or core["filedAt"] > as_of
    ):
        raise ValueError("Alphabet reviewed source identity changed")
    annual = instance_rows(
        read_verified(ROOT / annual_source["file"], annual_source["sha256"]),
        c,
        annual_source,
        ANNUAL,
        core["filedAt"],
    )
    f = c["financials"]
    periods = [
        (1, annual, core["start"], core["end"]),
        (1, current, f["start"], f["end"]),
        (-1, current, f["priorStart"], f["priorEnd"]),
    ]
    if [(p[2], p[3]) for p in periods] != [
        ("2025-01-01", "2025-12-31"),
        ("2026-01-01", "2026-06-30"),
        ("2025-01-01", "2025-06-30"),
    ]:
        raise ValueError("Alphabet reviewed cash periods changed")

    def exact(rows, tag, start, end):
        fact = select(
            [r for r in rows if r["decimals"] == "-6"], tag, start, end, (), "USD"
        )
        if fact is None:
            raise ValueError("Alphabet missing exact cash fact: " + tag)
        return fact

    def combine(tag):
        components = [
            dict(coefficient=sign, fact=exact(rows, tag, start, end))
            for sign, rows, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in components),
            components=components,
            sourceUrl=source["primaryUrl"],
            start=h["start"],
            end=h["end"],
            unit="USD",
            derived=True,
        )

    facts = {key: combine(tag) for key, tag in TAGS.items()}
    facts["revenue"] = dict(
        value=facts["reportedRevenue"]["value"] - facts["hedgeRevenue"]["value"],
        sourceUrl=source["primaryUrl"],
        components=facts["reportedRevenue"]["components"]
        + [
            dict(coefficient=-p["coefficient"], fact=p["fact"])
            for p in facts["hedgeRevenue"]["components"]
        ],
        scope="연결 매출에서 별도 매출 헤지 조정을 차감한 사업부 매출 합계",
    )
    v = lambda key: facts[key]["value"]
    period_checks = []
    # The annual cash statement does not separately present inventory, while
    # current/prior half-years do. Never fill the missing annual row with zero.
    per_period = []
    for i, (coefficient, rows, start, end) in enumerate(periods):
        roles = ROLES + (
            [("IncreaseDecreaseInAccruedRevenueShare", "수익배분 미지급금 변동", 1)]
            if i == 0
            else [("IncreaseDecreaseInInventories", "재고 변동", -1)]
        )
        parts = [
            dict(
                label=label,
                value=sign * exact(rows, tag, start, end)["value"],
                fact=exact(rows, tag, start, end),
                tag=tag,
                coefficient=sign,
            )
            for tag, label, sign in roles
        ]
        cfo = exact(rows, TAGS["cfo"], start, end)["value"]
        residual = cfo - sum(p["value"] for p in parts)
        ni = exact(rows, TAGS["netIncome"], start, end)["value"]
        income_gap = (
            exact(rows, TAGS["operatingIncome"], start, end)["value"]
            + exact(rows, TAGS["nonoperating"], start, end)["value"]
            - exact(rows, TAGS["tax"], start, end)["value"]
            - ni
        )
        if residual or income_gap:
            raise ValueError("Alphabet period cash or income reconciliation failed")
        per_period.append(parts)
        period_checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=cfo,
                residual=residual,
                incomeResidual=income_gap,
                parts=parts,
            )
        )
    parts = []
    for tag, label, sign in ROLES:
        fact = combine(tag)
        parts.append(dict(label=label, value=sign * fact["value"], fact=fact))
    changes = []
    for i, (coefficient, _, _, _) in enumerate(periods):
        p = per_period[i][-1]
        changes.append(dict(coefficient=coefficient * p["coefficient"], fact=p["fact"]))
    parts.append(
        dict(
            label="기간별 별도 표시된 재고·수익배분 미지급금",
            value=sum(p["coefficient"] * p["fact"]["value"] for p in changes),
            fact=dict(sourceUrl=source["primaryUrl"], components=changes),
            scope="연간에는 수익배분 미지급금, 반기에는 재고가 별도 표시됨. 같은 계정의 최근1년 변화가 아니라 현금표 표시 차이를 보존한 합계.",
        )
    )
    if sum(p["value"] for p in parts) != v("cfo"):
        raise ValueError("Alphabet trailing cash bridge failed")

    # Annual total already includes pre-commencement payments; current H1
    # explicitly excludes its separate payment. Preserve the reviewed labels.
    prepay = exact(
        current, "PaymentsRelatedToFinanceLeasesNotYetCommenced", f["start"], f["end"]
    )
    lease_components = facts["leaseReported"]["components"] + [
        dict(coefficient=1, fact=prepay)
    ]
    lease = sum(p["coefficient"] * p["fact"]["value"] for p in lease_components)
    facts["leaseCash"] = dict(
        value=lease,
        components=lease_components,
        sourceUrl=source["primaryUrl"],
        scope="연간 총 금융리스 현금은 미개시 선급금을 포함. 당기반기의 추가 선급금만 별도 더하며 전년반기 보고 총액은 차감.",
    )
    # Each historical lease caption is bound to the archived official document.
    reviewed_documents = [
        (
            ANNUAL,
            "8247275d30a8f9f0cf6c36a6c9bd76fb50d656dd51d77ad777b160c6bf95476f",
            "includes $1.1 billion of prepayments",
        ),
        (
            "0001652044-25-000062",
            "c91c5ed0a09f03223a8535acca6aac1bdee1d54fe1fe8825eaf20ba367becd32",
            "Financing cash flows used for finance leases(1)",
        ),
    ]
    for accession, sha, caption in reviewed_documents:
        manifest = json.loads(
            (ROOT / f"data/sources/filing-{accession}.manifest.json").read_text()
        )
        if (
            manifest["sha256"] != sha
            or manifest["accession"] != accession
            or manifest["filedAt"] > as_of
        ):
            raise ValueError("Alphabet reviewed lease source identity changed")
        blob = read_verified(ROOT / manifest["file"], sha)
        if caption not in " ".join(p["text"] for p in extract(blob)):
            raise ValueError("Reviewed lease caption changed")
        if manifest["file"] not in {s["file"] for s in c["sources"]}:
            c["sources"].append(manifest)
    if lease != 3_361_000_000:
        raise ValueError("Alphabet lease cash scope changed")

    revenue = sum(s["revenue"]["value"] for s in h["segments"])
    if (
        revenue != v("revenue")
        or v("reportedRevenue") != c["trailingYear"]["values"]["revenue"]["value"]
    ):
        raise ValueError(
            "Alphabet contract and reported revenue differ from reconciliations"
        )
    recon = h["reconciliations"]["operatingIncome"]
    unallocated = -recon["adjustment"]
    if unallocated < 0 or recon["subtotal"] - unallocated != v("operatingIncome"):
        raise ValueError("Alphabet corporate net cost does not reconcile")
    segments = []
    business = {s["id"]: s for s in c["business"]["segments"]}
    for s in h["segments"]:
        b = business[s["id"]]
        segments.append(
            dict(
                id=s["id"],
                label=s["label"],
                revenue=s["revenue"]["value"],
                margin=s["margin"],
                minMargin=-10 if s["id"] == "AllOtherSegmentsMember" else -0.5,
                observedGrowth=b["current"]["revenue"]["value"]
                / b["previous"]["revenue"]["value"]
                - 1,
                evidence=[
                    p["fact"]
                    for p in s["revenue"]["components"]
                    + s["operatingIncome"]["components"]
                ],
            )
        )
    wc_tags = {
        "IncreaseDecreaseInAccountsReceivable",
        "IncreaseDecreaseInInventories",
        "IncreaseDecreaseInOtherOperatingAssets",
        "IncreaseDecreaseInAccountsPayable",
        "IncreaseDecreaseInAccruedLiabilities",
        "IncreaseDecreaseInContractWithCustomerLiability",
    }
    working = sum(p["value"] for p in per_period[1] if p["tag"] in wc_tags)
    growth = sum(
        b["current"]["revenue"]["value"] - b["previous"]["revenue"]["value"]
        for b in business.values()
    )
    if growth <= 0:
        raise ValueError("Review Alphabet capital driver when sales contract")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=v("tax") / v("pretax"),
        netInterest=(v("interestIncome") - v("interestExpense")) / revenue,
        depreciation=v("depreciation") / revenue,
        workingCapital=-working / growth,
        capexStart=v("capex") / revenue,
        capexEnd=v("capex") / revenue,
        leaseStart=lease / revenue,
        leaseEnd=lease / revenue,
        discount=0.11,
        terminal=0.02,
        corporateStart=unallocated / revenue,
        corporateEnd=unallocated / revenue,
    )
    corpus = load(c)
    selected = {
        p["id"]
        for p in corpus["passages"]
        if p["ordinal"]
        in [
            463,
            490,
            494,
            760,
            761,
            762,
            763,
            764,
            765,
            790,
            909,
            930,
            931,
            932,
            935,
            936,
        ]
    }
    m = dict(
        status="research_workspace",
        version="alphabet-segment-cash-path-v1",
        unallocatedPath=True,
        sourcePeriod=[h["start"], h["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        basisLabel="최근1년 사업부·본사 조정·현금 연결",
        growthLabel="최근 반기 전년 대비",
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        intro="Google Services·Cloud·Other Bets의 영업이익에서 본사 공통비·매출 헤지 순조정을 반영합니다. 보고 현금 대사와 미래 유지 가정을 구분합니다.",
        businessCaption="사업부 매출 합계는 매출 헤지 전 계약 매출입니다. 연결 보고 매출과의 차이를 원문 대사에 보존합니다. Other Bets의 큰 손실률을 영이나 −50%로 잘라내지 않습니다.",
        corporateLabel="본사 공통비·매출 헤지 순조정",
        capexLabel="설비 현금 취득",
        leaseLabel="금융리스·미개시 선급 현금",
        passages=[p for p in corpus["passages"] if p["id"] in selected],
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=period_checks,
            cashAfterInvestmentLeaseSbc=v("cfo") - v("capex") - lease - v("sbc"),
        ),
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=growth,
            unallocatedCost=unallocated,
            reportedRevenue=v("reportedRevenue"),
            contractRevenue=revenue,
            revenueAdjustment=v("reportedRevenue") - revenue,
            leaseCurrentPrepayment=prepay,
        ),
        anchorSummary="가정의 매출 분모는 매출 헤지 전 사업부 합계입니다. 본사 공통비와 매출 헤지는 부문 이익에서 별도로 조정하며, 보고 연결 매출을 바꾸지 않습니다. 영업자금 계수는 최근 반기의 세금 제외 현금 변동과 같은 범위 매출 증가에서 계산합니다.",
        rules=[
            "성장 0%·현재 부문 마진·공통비 순조정 비율 유지가 시작 가정입니다. 전망·목표가가 아닙니다.",
            "사업부 이익 밖의 AI 연구·본사·법률비와 매출 헤지 순조정을 따로 반영합니다. 이를 모두 AI 비용이나 일회성 비용으로 이름 바꾸지 않습니다.",
            "주식보상은 미래에 되돌리지 않고 대체 보상 비용으로 유지합니다. 큰 증권 평가이익과 이연세 조정은 보고 현금 대사에만 남기고 미래 순이자만 반복하는 가정입니다.",
            "감가상각은 설비 현금표 금액입니다. 영업리스·무형자산 비용은 비용을 대체 지출의 대용으로 남기는 가정이며, 실제 정상 투자 회수 검증이 아닙니다.",
            "연간 금융리스 현금에는 미개시 선급1.1bn이 이미 포함됩니다. 당기반기 원금840m 외 선급835m만 더하고 전년반기 보고302m을 차감합니다. 선급금을 자산 취득과 중복 차감하지 않습니다.",
            "보고 세율에는 투자 평가손익과 이연세 효과가 섞여 있습니다. 정상세율은 별도 가정으로 편집하며 기본값을 장기 세율로 승인하지 않습니다.",
            "세 종류 보통주와 우선주, 자회사 비지배 권리의 배분이 미해결이므로 주당 가격은 보류합니다. 모델 현금은 증권별 배분 전 연구 경로입니다.",
        ],
        remaining=[
            "현재 투자 수준의 유지·확장 구분과 데이터센터·전력 사용 계약 회수",
            "본사 AI 연구·일회성 법률비와 매출 헤지의 미래 경로",
            "Wiz 등 인수·투자자산과 우선주·비지배 권리 및 초과자산 배분",
            "보고세율에서 정상 현금세율과 영업자금의 반복성 확인",
        ],
    )
    from .operating_model import calculate

    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
