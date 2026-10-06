"""Amazon-specific cash normalization; content/operating leases stay expensed."""

from .data import ROOT, canonical, digest, read_verified
from .narrative import load
from .xbrl import company_filing, instance_rows, select

PASSAGES = [
    "b1f8c6e34efe853dc96a",  # Broad cash-flow depreciation adjustment.
    "2db5f4c0f405a8557583",  # Operating cash and working capital.
    "6b6396a4faee669301c2",  # Cash capital expenditure vs investments.
    "0561cf17a420b9a98d9a",  # Financing and lease payments.
    "c40ca596d1f71285a65c",  # Shared asset allocation.
    "c62a08c629338b5d4db5",  # PPE depreciation, narrower than cash-flow line.
    "6b46d46d1379b9ff694a",  # Company's net-capex free cash flow definition.
    "0a7750f742615903d7dd",  # What reported free cash flow omits.
    "ef35bacbb8bd4f0df0d8",
    "bd8c671de3a8142fd7c7",  # Energy derivative gains remain in operating margins.
]
TAGS = {
    "operatingIncome": "OperatingIncomeLoss",
    "nonoperating": "NonoperatingIncomeExpense",
    "tax": "IncomeTaxExpenseBenefit",
    "equityMethod": "IncomeLossFromEquityMethodInvestments",
    "netIncome": "NetIncomeLoss",
    "daOther": "DepreciationDepletionAndAmortization",
    "depreciation": "Depreciation",
    "noncashIncome": "OtherNoncashIncomeExpense",
    "deferredTax": "DeferredIncomeTaxExpenseBenefit",
    "sbc": "ShareBasedCompensation",
    "inventory": "IncreaseDecreaseInInventories",
    "receivables": "IncreaseDecreaseInAccountsReceivableAndOtherOperatingAssets",
    "otherAssets": "IncreaseDecreaseInOtherNoncurrentAssets",
    "payables": "IncreaseDecreaseInAccountsPayable",
    "accruals": "IncreaseDecreaseInAccruedLiabilitiesAndOtherOperatingLiabilities",
    "unearned": "IncreaseDecreaseInContractWithCustomerLiability",
    "cfo": "NetCashProvidedByUsedInOperatingActivities",
    "capex": "PaymentsToAcquireProductiveAssets",
    "assetProceeds": "ProceedsFromPropertyPlantAndEquipmentSalesAndIncentives",
    "lease": "FinanceLeasePrincipalPayments",
    "financingPrincipal": "RepaymentsOfLongTermFinancingObligations",
    "interestIncome": "InvestmentIncomeInterest",
    "interestExpense": "InterestExpenseNonoperating",
}
WC = [
    ("inventory", "재고", -1),
    ("receivables", "채권·기타 영업자산", -1),
    ("payables", "매입채무", 1),
    ("accruals", "미지급·기타 영업부채", 1),
    ("unearned", "선수 수익", 1),
]


def build(c, as_of):
    from .operating_model import calculate

    h = c.get("segmentHistory") or {}
    meta = c.get("narrative") or {}
    if (
        meta.get("accession") != "0001018724-26-000026"
        or meta.get("evidenceHash")
        != "59fabb51c8361dd5403ba0bebdd99cee8d38efa85e29c0ec0bee63e86bf95f42"
        or h.get("status") != "ready"
    ):
        return dict(
            status="source_review_required",
            reason="Amazon의 새 공시·부문 기간과 현금 조정을 다시 대사해야 합니다.",
        )
    _, rows = company_filing(c, as_of)
    annual_source = h["review"]["annualSource"]
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    annual = instance_rows(
        read_verified(ROOT / annual_source["file"], annual_source["sha256"]),
        c,
        annual_source,
        core["accession"],
        core["filedAt"],
    )
    f = c["financials"]
    periods = [
        (1, annual, core["start"], core["end"]),
        (1, rows, f["start"], f["end"]),
        (-1, rows, f["priorStart"], f["priorEnd"]),
    ]

    def exact(rs, tag, start, end):
        # These statements are in millions. Narrative tax notes round to 100m;
        # that lower-precision duplicate is not a second statement measurement.
        return select(
            [r for r in rs if r["decimals"] == "-6"], tag, start, end, (), "USD"
        )

    def combine(tag):
        components = []
        for coefficient, rs, start, end in periods:
            fact = exact(rs, tag, start, end)
            if fact is None:
                raise ValueError("Amazon source cash component missing: " + tag)
            components.append(dict(coefficient=coefficient, fact=fact))
        value = sum(p["coefficient"] * p["fact"]["value"] for p in components)
        direct = exact(rows, tag, h["start"], h["end"])
        if direct and direct["value"] != value:
            raise ValueError(
                "Amazon reported twelve-month cash differs from period bridge"
            )
        return dict(
            value=value,
            components=components,
            directTrailingFact=direct,
            derived=True,
            tag=tag,
            sourceUrl=components[1]["fact"]["sourceUrl"],
            start=h["start"],
            end=h["end"],
            unit="USD",
        )

    facts = {key: combine(tag) for key, tag in TAGS.items()}
    v = lambda k: facts[k]["value"]
    roles = [
        ("operatingIncome", "연결 영업이익", 1),
        ("nonoperating", "영업외 손익", 1),
        ("tax", "법인세 비용", -1),
        ("equityMethod", "세후 지분법 손익", 1),
        ("daOther", "설비·콘텐츠·영업리스 상각 등", 1),
        ("noncashIncome", "비현금 영업외 손익 되돌림", -1),
        ("deferredTax", "이연법인세 조정", 1),
        ("sbc", "주식보상 되돌림", 1),
        *WC,
        ("otherAssets", "기타 장기자산 변동", -1),
    ]
    parts = [
        dict(label=label, value=sign * v(key), fact=facts[key])
        for key, label, sign in roles
    ]
    period_checks = []
    for i, (_, _, start, end) in enumerate(periods):
        total = facts["cfo"]["components"][i]["fact"]["value"]
        summed = sum(
            sign * facts[k]["components"][i]["fact"]["value"] for k, _, sign in roles
        )
        if total != summed:
            raise ValueError("Amazon per-period cash bridge does not reconcile")
        period_checks.append(
            dict(start=start, end=end, reportedCfo=total, residual=total - summed)
        )
    if sum(p["value"] for p in parts) != v("cfo"):
        raise ValueError("Amazon trailing operating cash does not reconcile")
    revenue = c["trailingYear"]["values"]["revenue"]["value"]
    if sum(s["revenue"]["value"] for s in h["segments"]) != revenue or sum(
        s["operatingIncome"]["value"] for s in h["segments"]
    ) != v("operatingIncome"):
        raise ValueError("Amazon cash and segment scope differ")
    prior_by_id = {s["id"]: s for s in c["business"]["segments"]}
    segments = []
    for s in h["segments"]:
        old = prior_by_id[s["id"]]
        segments.append(
            dict(
                id=s["id"],
                label=s["label"],
                revenue=s["revenue"]["value"],
                margin=s["margin"],
                observedGrowth=old["current"]["revenue"]["value"]
                / old["previous"]["revenue"]["value"]
                - 1,
                evidence=[
                    p["fact"]
                    for metric in ("revenue", "operatingIncome")
                    for p in s[metric]["components"]
                ],
            )
        )
    # Use matched current/prior half-year changes for this proxy, not the
    # difference between trailing-year sales and a six-month sales figure.
    revenue_increase = (
        f["current"]["revenue"]["value"] - f["previous"]["revenue"]["value"]
    )
    working_effect = sum(
        sign * facts[k]["components"][1]["fact"]["value"] for k, _, sign in WC
    )
    if revenue_increase <= 0:
        raise ValueError("Review Amazon cash-demand proxy when sales contract")
    net_capex = v("capex") - v("assetProceeds")
    principal = v("lease") + v("financingPrincipal")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=v("tax") / (v("operatingIncome") + v("nonoperating")),
        netInterest=(v("interestIncome") - v("interestExpense")) / revenue,
        depreciation=v("depreciation") / revenue,
        workingCapital=-working_effect / revenue_increase,
        capexStart=net_capex / revenue,
        capexEnd=net_capex / revenue,
        leaseStart=principal / revenue,
        leaseEnd=principal / revenue,
        discount=0.11,
        terminal=0.02,
    )
    corpus = load(c)
    index = {p["id"]: p for p in corpus["passages"]}
    if any(i not in index for i in PASSAGES):
        raise ValueError("Amazon operating cash source passages changed")
    m = dict(
        status="research_workspace",
        version="amazon-operating-cash-path-v1",
        sourcePeriod=[h["start"], h["end"]],
        accession=meta["accession"],
        corpusHash=meta["evidenceHash"],
        basisLabel="최근 1년 공시 연결에서 출발",
        growthLabel="최근 반기 전년 대비",
        businessCaption="기초 매출·마진은 최근 1년 합성값이고 관측 성장률은 최근 반기 전년 대비입니다. AWS와 북미·해외 소매를 별도로 가정하며 공동 설비의 사용량 배분을 완전한 사업별 현금으로 해석하지 않습니다.",
        capexLabel="설비 순현금 취득",
        leaseLabel="리스·시설금융 원금",
        anchorSummary=f"운전자본 대용 계수는 {f['start']}–{f['end']} 반기 현금 효과와 같은 반기 전년 대비 매출 증가로 산출합니다. 기타 장기자산 변동은 이 계수에서 제외합니다. 현금흐름표의 설비·콘텐츠·영업리스 상각 등과 설비 상각만의 차이는 {(v('daOther')-v('depreciation'))/1e9:,.3f}십억 달러입니다.",
        passages=[index[i] for i in PASSAGES],
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=period_checks,
            cashAfterInvestmentLeaseSbc=v("cfo") - net_capex - principal - v("sbc"),
        ),
        anchors=dict(
            workingCashEffect=working_effect,
            revenueIncrease=revenue_increase,
            daOtherDifference=v("daOther") - v("depreciation"),
            priorCapexRatio=(
                facts["capex"]["components"][0]["fact"]["value"]
                - facts["assetProceeds"]["components"][0]["fact"]["value"]
            )
            / core["value"],
        ),
        rules=[
            "초기 가정은 사업부 성장 0%, 최근 1년 이익률·투입 비율 유지다. AWS 투자 회수나 정상 가치를 입증한 전망이 아니다.",
            "최근 1년은 직전 연간+당기 반기−전년 반기다. 현금흐름표가 직접 제시한 12개월 수치와도 맞췄으며, 각 구성 기간의 영업이익→영업현금도 따로 대사한다.",
            "미래 되돌림은 설비의 감가상각·상각만 사용한다. 콘텐츠 원가·영업리스 등은 영업이익의 비용으로 남겨 반복 현금 부담의 대용으로 삼는다. 실제 콘텐츠 지급·임차료·자본화 시차 예측은 아니다.",
            "운전자본 대용치는 반기 재고·채권 및 기타 영업자산·매입채무·미지급 부채·선수 수익의 현금 효과다. 콘텐츠·리스와 섞일 수 있는 기타 장기자산 변동을 자동 반복하지 않는다. 제외 금액은 원문 영업현금 대사에서 확인할 수 있다.",
            "설비 취득에서 자산 매각·인센티브를 차감한 순현금 비율을 가정한다. 매각·인센티브의 지속성을 가정하므로 총 취득 비율로 높인 대안도 확인해야 한다. 기업 인수·금융 투자를 설비로 포함하지 않는다.",
            "금융리스와 시설금융 의무의 원금 상환을 합산해 별도 차감한다. 비현금 신규 리스 취득을 다시 차감하지 않는다. 차입 원금은 차환/순차입 0 가정이다.",
            "주식보상은 영업이익에 이미 비용 처리돼 미래에 되돌리지 않는다. 자사주 매입을 추가로 차감하지 않는다.",
            "세율은 보고 세금비용/세전손익 비율에서 출발하지만 투자 평가손익과 이연세금의 영향을 받았다. 영업의 정상 현금세율로 승인하지 않으며 연구자가 별도 가정한다.",
            "영업외 이익 전체 대신 순이자 수익 비율만 미래에 유지한다. 영업외로 분류된 투자·파생·지분법 손익과 초과 현금·투자자산 매각가치는 포함하지 않는다.",
            "현재 부문 마진에는 기술·인프라 비용에 반영된 에너지 계약 미실현 평가이익이 남아 있다. 회사는 이 평가가 현금흐름에 영향을 주지 않는다고 설명한다. 미래 마진 가정을 정상화하기 전 해당 이익과 위성망 비용·자본화 시점을 별도로 조정해야 한다.",
            "연차 할인은 관측 종가 기준 1년 간격이다. 6년차 말기 현금은 새 매출·세금·운전자본·설비·상환을 다시 산출한다. 말기 현금이 음수이면 주당 가치는 계산 보류한다.",
        ],
        remaining=[
            "AWS 에너지 계약 미실현 이익과 위성망 비용·자본화에 대한 이익률 조정",
            "AWS/소매별 투자·가동·자산 수명과 공유 설비 배분",
            "콘텐츠 자본화·실제 지급 및 임차료와 비용 시차",
            "설비 공급자 인센티브·매각의 반복 가능성",
            "대규모 금융 투자와 현금 세율·부채 차환·투자자산 배분",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
