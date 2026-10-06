"""Netflix: content amortization, content cash and nonrecurring fee scope."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "0001065280-26-000212"
CORPUS = "d0e01702c68bcb8ce28ea992e932de5bbe97469f0ef4a8e2094bdb51f0a6cd6c"
SOURCE = "6a36c7c65635c73c06f364ccd7116320d2d0f59b6f33900dbce1be8f7ea56cc7"
ANNUAL = "0001065280-26-000034"
ANNUAL_SHA = "12a94204addacb8b613254fa3dcfe16bed2bcae72f035d572118bd8061016b7b"
ANNUAL_HTML = "c23339f06271398fad84cec33dae16fd5e2187bbfa34b7d0566a2c5d9b9b6a4a"
ROLES = [
    ("NetIncomeLoss", "연결 순이익", 1),
    ("AdditionstoStreamingContentAssets", "콘텐츠 자산 증가", -1),
    ("ChangeInStreamingContentLiabilities", "콘텐츠 부채의 현금 조정", 1),
    ("CostofServicesAmortizationofStreamingContentAssets", "콘텐츠 상각", 1),
    ("DepreciationDepletionAndAmortization", "설비·기타 무형 상각", 1),
    ("ShareBasedCompensation", "주식보상 되돌림", 1),
    ("ForeignCurrencyTransactionGainLossBeforeTax", "외화부채 환산손익 제거", -1),
    ("OtherNoncashIncomeExpense", "기타 비현금 조정", -1),
    ("DeferredIncomeTaxExpenseBenefitIncludingReclassifications", "이연법인세", 1),
    ("IncreaseDecreaseInOtherCurrentAssets", "기타 유동자산 현금 효과", -1),
    ("IncreaseDecreaseInAccountsPayable", "매입채무", 1),
    ("IncreaseDecreaseInAccruedLiabilities", "미지급·기타 부채", 1),
    ("IncreaseDecreaseInContractWithCustomerLiability", "선수 수익", 1),
    (
        "IncreaseDecreaseInOtherNoncurrentAssetsAndLiabilitiesNet",
        "기타 비유동 자산·부채",
        -1,
    ),
]
PASSAGES = [
    "835070e28d90aa330249",
    "3c2fa2325149e131908d",
    "8bb5ec2dfbcdb4e36b1d",
    "9d163884066084fe82ae",
    "e9d5ad3043a7a9b1d6b6",
    "13a4ef31b81cd857bbec",
    "61fd7080fc81370f29d2",
    "d700c047a25b6d8f0510",
    "800cff948922e7773e35",
    "2225d8fd8a84c012d96b",
    "98b8b298f9567180addc",
    "3a0f8db388ab890d3671",
    "21d0be83a84f722009c1",
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="Netflix의 콘텐츠 현금·상각과 계약 해지 수입·약정을 새 공시에서 다시 대사해야 합니다.",
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
        or a["cik"] != c["cik"]
        or as_of < "2026-07-17"
    ):
        raise ValueError("Netflix source identity or timing changed")
    annual = instance_rows(
        read_verified(DOCUMENT_ROOT / a["file"], ANNUAL_SHA), c, a, ANNUAL, "2026-01-23"
    )
    f = c["financials"]
    periods = [
        (1, annual, "2025-01-01", "2025-12-31"),
        (1, rows, f["start"], f["end"]),
        (-1, rows, f["priorStart"], f["priorEnd"]),
    ]
    if [(s, e) for _, _, s, e in periods][1:] != [
        ("2026-01-01", "2026-06-30"),
        ("2025-01-01", "2025-06-30"),
    ]:
        raise ValueError("Netflix fiscal periods changed")

    def exact(rs, tag, start, end):
        r = select([x for x in rs if x["decimals"] == "-3"], tag, start, end, (), "USD")
        if r is None:
            raise ValueError("Netflix fact missing " + tag + " " + end)
        return r

    def combined(tag):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, s, e)) for k, rs, s, e in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            sourceUrl=source["primaryUrl"],
            unit="USD",
        )

    facts = {
        key: combined(tag)
        for key, tag in dict(
            revenue="Revenues",
            operatingIncome="OperatingIncomeLoss",
            netIncome="NetIncomeLoss",
            tax="IncomeTaxExpenseBenefit",
            nonoperating="NonoperatingIncomeExpense",
            interest="InterestExpenseNonoperating",
            cfo="NetCashProvidedByUsedInOperatingActivities",
            contentAdditions="AdditionstoStreamingContentAssets",
            contentLiabilityChange="ChangeInStreamingContentLiabilities",
            contentAmortization="CostofServicesAmortizationofStreamingContentAssets",
            depreciation="DepreciationDepletionAndAmortization",
            sbc="ShareBasedCompensation",
            ppe="PaymentsToAcquirePropertyPlantAndEquipment",
            acquisitions="PaymentsToAcquireBusinessesNetOfCashAcquired",
        ).items()
    }
    v = lambda key: facts[key]["value"]
    checks = []
    for i, (_, rs, start, end) in enumerate(periods):
        parts = [
            dict(
                label=label,
                value=sign * (fct := exact(rs, tag, start, end))["value"],
                fact=fct,
            )
            for tag, label, sign in ROLES
        ]
        value = lambda k: facts[k]["components"][i]["fact"]["value"]
        cash = sum(p["value"] for p in parts)
        if cash != value("cfo") or value("operatingIncome") - value("interest") + value(
            "nonoperating"
        ) - value("tax") != value("netIncome"):
            raise ValueError("Netflix income-to-cash mismatch " + end)
        checks.append(
            dict(
                start=start,
                end=end,
                parts=parts,
                reportedCfo=cash,
                residual=0,
                contentAdditions=value("contentAdditions"),
                contentLiabilityChange=value("contentLiabilityChange"),
                contentCash=value("contentAdditions") - value("contentLiabilityChange"),
                contentAmortization=value("contentAmortization"),
            )
        )
    parts = []
    for j, (_, label, sign) in enumerate(ROLES):
        xs = [
            dict(coefficient=k * sign, fact=checks[i]["parts"][j]["fact"])
            for i, (k, _, _, _) in enumerate(periods)
        ]
        parts.append(
            dict(
                label=label,
                value=sum(x["coefficient"] * x["fact"]["value"] for x in xs),
                fact=dict(components=xs, sourceUrl=source["primaryUrl"]),
            )
        )
    if sum(x["value"] for x in parts) != v("cfo"):
        raise ValueError("Netflix TTM cash mismatch")
    content_cash = v("contentAdditions") - v("contentLiabilityChange")
    reinvestment = v("ppe") + v("acquisitions")
    revenue = v("revenue")
    index = {p["id"]: p for p in load(c)["passages"]}
    ps = [index[x] for x in PASSAGES]
    fee = index["3c2fa2325149e131908d"]
    cash_fee = index["9d163884066084fe82ae"]
    trade = index["61fd7080fc81370f29d2"]
    if (
        "$2.8 billion termination fee" not in fee["text"]
        or "cash provided by operations" not in cash_fee["text"]
        or "2,003,958" not in trade["text"]
    ):
        raise ValueError("Netflix fee/receivable source changed")
    stocks = [
        dict(coefficient=k, label=label, fact=exact(rows, tag, None, f["end"]))
        for k, label, tag in [
            (
                1,
                "원표 Trade receivables · 매출채권",
                "TradeReceivablesHeldForSaleAmount",
            ),
            (-1, "매입채무", "AccountsPayableCurrent"),
            (-1, "선수 수익", "ContractWithCustomerLiabilityCurrent"),
        ]
    ]
    working = sum(x["coefficient"] * x["fact"]["value"] for x in stocks)
    obligations = []
    for pid, label, value in [
        ("bc1939564891929e33bd", "1년 이내", 11939734000),
        ("adca6fd829b8a51ff69a", "1년 초과 3년 이내", 9546875000),
        ("a4cebec48a51cd963e43", "3년 초과 5년 이내", 2996885000),
        ("add109d416d5f301d319", "5년 초과", 623211000),
    ]:
        p = index[pid]
        if f"{value/1000:,.0f}" not in p["text"]:
            raise ValueError("Netflix commitment table changed")
        obligations.append(dict(label=label, value=value, source=p))
    total = sum(o["value"] for o in obligations)
    current_liab = exact(rows, "ContentLiabilitiesCurrent", None, f["end"])
    noncurrent_liab = exact(rows, "ContentLiabilitiesNoncurrent", None, f["end"])
    if (
        total != 25106705000
        or "25,106,705" not in index["20a97b0b938dd2cc2dc4"]["text"]
    ):
        raise ValueError("Netflix content obligations total mismatch")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=v("operatingIncome") / revenue)
        ],
        tax=0.25,
        netInterest=-v("interest") / revenue,
        depreciation=(v("contentAmortization") + v("depreciation")) / revenue,
        workingCapital=working / revenue,
        contentStart=content_cash / revenue,
        contentEnd=content_cash / revenue,
        capexStart=reinvestment / revenue,
        capexEnd=reinvestment / revenue,
        leaseStart=0,
        leaseEnd=0,
        discount=0.12,
        terminal=0.02,
    )
    for s in [
        a,
        h,
        dict(a["indexSource"], provider="SEC", retrievedAt=a["retrievedAt"]),
    ]:
        read_verified(DOCUMENT_ROOT / s["file"], s["sha256"])
        if s["file"] not in {x["file"] for x in c["sources"]}:
            c["sources"].append(s)
    aps = extract(read_verified(DOCUMENT_ROOT / h["file"], ANNUAL_HTML))
    hist = [
        dict(p, sourceUrl=h["url"], sourceHash=ANNUAL_HTML)
        for p in aps
        if any(
            k in p["text"]
            for k in [
                "Amortization of content assets",
                "Additions to content assets",
                "Change in content liabilities",
                "one operating segment",
            ]
        )
    ]
    m = dict(
        status="research_workspace",
        version="netflix-content-cash-v2",
        contentPath=True,
        sourcePeriod=["2025-07-01", "2026-06-30"],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        basisLabel="단일 영업부문 / 콘텐츠 지급·상각 구분",
        groupLabel="공시 단일 영업부문",
        growthLabel="같은 반기 대비",
        segments=[
            dict(
                id="streaming",
                label="Netflix 연결 단일 사업",
                revenue=revenue,
                margin=v("operatingIncome") / revenue,
                observedGrowth=facts["revenue"]["components"][1]["fact"]["value"]
                / facts["revenue"]["components"][2]["fact"]["value"]
                - 1,
                evidence=[facts["revenue"], facts["operatingIncome"]],
            )
        ],
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        capexLabel="설비·인수 현금",
        netInterestLabel="이자비용 차감 · 투자수익·해지금 제외",
        leaseLabel="금융리스 원금 가정",
        intro="공시 단일 사업의 영업이익에서 출발해 콘텐츠 상각을 되돌리고 실제 콘텐츠 현금 지급을 미래 재투자로 연결합니다. 인수계약 해지 수입은 영업이익 밖에 있으며 미래 반복 현금에 더하지 않습니다. 국가별 매출을 별도의 이익 사업부로 만들지 않습니다.",
        businessCaption="광고·구독·라이선스와 지역별 이익이 독립 보고부문으로 공시된 것은 아닙니다. 연결 영업마진과 콘텐츠 지급·상각의 차이를 조절하며 회원 수나 가격 효과를 연결 성장 하나로 확정하지 않습니다.",
        anchorSummary="기말 원문 매출채권−매입채무−선수수익을 최근1년 매출로 나눈 좁은 자금 소요 대용입니다. XBRL 태그의 HeldForSale라는 이름과 달리 원문 표제는 Trade receivables이며 원문 금액을 대조했습니다. 기타 유동자산 전체와 콘텐츠 자산·부채를 더하지 않습니다. 과거 브라질 비정기 세금 지급을 미래 영업자금 계수에 반복하지 않습니다. 세율25%·금융리스0은 명시적 연구 가정입니다.",
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=None,
        ),
        anchors=dict(
            workingStockTerms=stocks,
            workingStockNet=working,
            actualFinanceLeasePayment=None,
            shareCompensationReplacement=v("sbc"),
        ),
        contentEvidence=dict(
            periods=checks,
            contentCash=content_cash,
            contentAmortization=facts["contentAmortization"],
            contentLiabilityChange=facts["contentLiabilityChange"],
            feeAmount=2800000000,
            feeSource=fee,
            feeCashSource=cash_fee,
            currentCashBeforeFeeOnly=checks[1]["reportedCfo"] - 2800000000,
            priorCfo=checks[2]["reportedCfo"],
            nonRoutineBrazilPayment=729000000,
            brazilSource=index["e9d5ad3043a7a9b1d6b6"],
            obligations=obligations,
            obligationTotal=total,
            recognizedContentLiabilities=[current_liab, noncurrent_liab],
            unrecognizedDerived=total
            - current_liab["value"]
            - noncurrent_liab["value"],
            obligationScope=index["98b8b298f9567180addc"],
            workingStockTerms=stocks,
            workingStockNet=working,
            tradeSource=trade,
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
                    "콘텐츠 상각",
                    v("contentAmortization"),
                    "미래 영업이익에서 차감된 상각을 되돌림",
                ),
                (
                    "콘텐츠 지급 대사",
                    content_cash,
                    "콘텐츠 자산 증가−콘텐츠 부채 현금조정; 과거 CFO에 이미 포함",
                ),
                ("설비·기타 무형상각", v("depreciation"), "콘텐츠 상각과 별도"),
                ("설비 취득", v("ppe"), "콘텐츠와 별도 투자활동"),
                (
                    "기업 인수",
                    v("acquisitions"),
                    "초기 미래 재투자에 유지. 해지된 WBD 계약 금액이 아님",
                ),
                (
                    "이자비용",
                    v("interest"),
                    "부채 만기·차환은 별도. 해지 수입·투자수익은 미래 제외",
                ),
                ("전체 금융리스 원금", None, "미확인. 영업리스 현금은 영업비용에 유지"),
            ]
        ],
        passages=ps,
        historicalPassages=hist,
        observedResidualLabel="콘텐츠 지급은 CFO에 포함 / 금융리스·주식보상 범위 추가 검토",
        rules=[
            "연간+현재반기−전년반기로 손익·현금을 연결하고 세 기간 현금 조정 전체를 대사합니다. 천달러 정밀 원 표와 백만달러 반올림 주석을 섞지 않습니다.",
            "콘텐츠 지급은 자산 증가에서 콘텐츠 부채 현금 조정을 차감한 금액입니다. 기초·기말 부채의 단순 잔액 차이를 사용하지 않습니다. 보고 CFO에서 지급을 다시 빼지 않습니다.",
            "미래에는 콘텐츠·기타 상각을 되돌리고 콘텐츠 지급을 설비·인수와 별도 가정으로 한 번씩 차감합니다. 주식보상은 비용에 남깁니다.",
            "WBD 해지금은 영업이익 밖의 수입이므로 영업마진에서 다시 차감하지 않습니다. 투자수익·환산손익·해지금의 미래 반복을 제외하고 이자비용만 별도 차감합니다.",
            "보고 반기 CFO에서 해지금 총액만 제외하는 비교는 관련 세금 등을 고정한 단순 민감도이며 정상 영업현금 추정이 아닙니다. 브라질 비정기 지급을 자동 가산하지 않습니다.",
            "콘텐츠 계약 약정은 미래 시점별 지급 범위이며 보고 부채와 일부 겹칩니다. 전체 약정을 당기 콘텐츠 현금이나 추가 부채로 중복 차감하지 않습니다. 금액 미확정 미래 작품은 공시 약정에 포함되지 않을 수 있습니다.",
            "현재 기타 유동자산의 매출채권 표만 자금 소요에 채택합니다. 선급·세금·기타 자산을 매출채권으로 합산하지 않습니다.",
            "회사 전체 현금·투자자산을 더하지 않았습니다. 미래 차입 원금·차환·리스와 인수·콘텐츠 투자의 반복 수준은 추가 검토 대상입니다.",
        ],
        remaining=[
            "콘텐츠 상각과 신규 지급의 지속성·회원 유지",
            "광고·구독·라이선스의 단가·원가·계약 차이",
            "해지금 세금과 비정기 세금 지급의 실제 시점",
            "만기별 콘텐츠 약정·신규 미확정 작품·부채 차환",
            "초과현금·금융자산·금융리스와 인수 반복",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
