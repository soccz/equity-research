"""NVIDIA segment cash with corporate costs and partner commitments kept explicit."""

import json
from .data import ROOT, canonical, digest, read_verified
from .narrative import load, extract
from .xbrl import company_filing, instance_rows, select

DOCUMENT_ROOT = ROOT
CURRENT = "0001045810-26-000075"
CORPUS = "c6079c3c96a23d82426b958715d0455824faa0be9d3a58ea18004d093c7b25fe"
CURRENT_SHA = "fd37c5c3b08be610fa48f8e3e394ab8d2108a23bbc2dfa26ee0bf0d91493bdfd"
ANNUAL_SHA = "af8398105d629d98defacca572c8e85fe0d8a5f551266b01df2d8be4fa03558f"
ANNUAL_HTML = "cf20715eecb0a532b75763ea48056d560e76777156c9ec6fb706a9762b55f644"
CORPORATE = [("ConsolidationItemsAxis", "CorporateNonSegmentMember")]
CORPORATE_TAGS = [
    "AllocatedShareBasedCompensationExpense",
    "UnallocatedCorporateOperatingExpendituresAndOtherExpenses",
    "AcquisitionRelatedAndOtherCosts",
]
TAGS = dict(
    revenue="Revenues",
    operatingIncome="OperatingIncomeLoss",
    netIncome="NetIncomeLoss",
    tax="IncomeTaxExpenseBenefit",
    pretax="IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    sbc="ShareBasedCompensation",
    depreciation="DepreciationDepletionAndAmortization",
    deferredTax="DeferredIncomeTaxExpenseBenefit",
    equityGains="GainLossOnInvestments",
    otherNoncash="OtherNoncashIncomeExpense",
    receivables="IncreaseDecreaseInAccountsReceivable",
    inventory="IncreaseDecreaseInInventories",
    prepaids="IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",
    payables="IncreaseDecreaseInAccountsPayable",
    accrued="IncreaseDecreaseInAccruedLiabilitiesAndOtherOperatingLiabilities",
    longLiabilities="IncreaseDecreaseInOtherNoncurrentLiabilities",
    capex="PaymentsToAcquireProductiveAssets",
    financedAssets="PaymentsForFinancedPropertyPlantAndEquipmentAndIntangibleAssetsFinancingActivities",
    interestIncome="InvestmentIncomeInterest",
    interestExpense="InterestExpenseNonoperating",
    intangibleAmortization="AmortizationOfIntangibleAssets",
)
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("sbc", "주식보상 비용 조정", 1),
    ("depreciation", "감가상각·상각", 1),
    ("deferredTax", "이연 법인세", 1),
    ("equityGains", "투자 증권 이익 차감", -1),
    ("otherNoncash", "기타 비현금 조정", -1),
    ("receivables", "매출채권 변동", -1),
    ("inventory", "재고 변동", -1),
    ("prepaids", "선급 및 기타 자산 변동", -1),
    ("payables", "매입채무 변동", 1),
    ("accrued", "미지급 및 기타 유동부채 변동", 1),
    ("longLiabilities", "기타 장기부채 변동", 1),
]
PASSAGES = [
    "e5f922166ccd902a1991",
    "42a733779d01bbc0c54d",
    "db16a6d8d5ec712f3a56",
    "34b5cdec43bccbdb353e",
    "1e9948d5db92d73d0560",
    "0db0ccce0cb9594f8a88",
    "f446203b61875276f116",
    "3119758f5814a9f20992",
    "96a3b1d2e55fa6c5ecfd",
    "884ebdb57d42e10e85df",
    "43cf740775b4e544d151",
    "8bea9fd6492738183cb7",
    "cac6584c8a1c637637b5",
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    h = c.get("segmentHistory") or {}
    if (
        meta.get("accession") != CURRENT
        or meta.get("evidenceHash") != CORPUS
        or h.get("status") != "ready"
    ):
        return dict(
            status="source_review_required",
            reason="NVIDIA 새 부문·본사 비용·현금 공시를 다시 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    annual_source = h["review"]["annualSource"]
    if source["sha256"] != CURRENT_SHA or annual_source["sha256"] != ANNUAL_SHA:
        raise ValueError("NVIDIA source identity changed")
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if core["accession"] != "0001045810-26-000021":
        raise ValueError("NVIDIA annual period identity changed")
    annual = instance_rows(
        read_verified(ROOT / annual_source["file"], ANNUAL_SHA),
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

    def exact(rs, tag, start, end, dims=()):
        # The tax note rounds 7,920 million to 7.9 billion. Preserve the primary
        # statement's million-dollar precision instead of picking either value.
        candidates = [
            r for r in rs if tag != "IncomeTaxExpenseBenefit" or r["decimals"] == "-6"
        ]
        result = select(candidates, tag, start, end, dims, "USD")
        if result is None:
            raise ValueError("NVIDIA cash source missing: " + tag)
        return result

    def combine(tag, dims=()):
        ps = [
            dict(coefficient=k, fact=exact(rs, tag, start, end, dims))
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in ps),
            components=ps,
            unit="USD",
            derived=True,
            sourceUrl=source["primaryUrl"],
        )

    facts = {k: combine(tag) for k, tag in TAGS.items()}
    corporate = [combine(tag, CORPORATE) for tag in CORPORATE_TAGS]
    v = lambda key: facts[key]["value"]
    checks = []
    for i, (_, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        cash = sum(sign * val(key) for key, _, sign in CASH)
        costs = sum(p["components"][i]["fact"]["value"] for p in corporate)
        segment_income = sum(
            s["operatingIncome"]["components"][i]["fact"]["value"]
            for s in h["segments"]
        )
        segment_revenue = sum(
            s["revenue"]["components"][i]["fact"]["value"] for s in h["segments"]
        )
        if (
            cash != val("cfo")
            or val("pretax") - val("tax") != val("netIncome")
            or segment_income - costs != val("operatingIncome")
            or segment_revenue != val("revenue")
        ):
            raise ValueError("NVIDIA period cash or segment income does not reconcile")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=val("cfo"),
                residual=0,
                incomeResidual=0,
                revenueResidual=0,
                corporateCosts=costs,
            )
        )
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
    revenue = v("revenue")
    if revenue != c["trailingYear"]["values"]["revenue"]["value"]:
        raise ValueError("NVIDIA trailing scope differs")
    segments = []
    for s in h["segments"]:
        current = s["revenue"]["components"][1]["fact"]["value"]
        prior = s["revenue"]["components"][2]["fact"]["value"]
        segments.append(
            dict(
                id=s["id"],
                label=s["label"],
                revenue=s["revenue"]["value"],
                margin=s["operatingIncome"]["value"] / s["revenue"]["value"],
                observedGrowth=current / prior - 1,
                evidence=[p["fact"] for p in s["revenue"]["components"]],
            )
        )
    working = sum(
        sign * facts[key]["components"][1]["fact"]["value"]
        for key, _, sign in CASH
        if key in {"receivables", "inventory", "prepaids", "payables", "accrued"}
    )
    increase = (
        facts["revenue"]["components"][1]["fact"]["value"]
        - facts["revenue"]["components"][2]["fact"]["value"]
    )
    if increase <= 0:
        raise ValueError("NVIDIA growth-based capital proxy requires review")
    corp = sum(p["value"] for p in corporate)
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.21,
        netInterest=(v("interestIncome") - v("interestExpense")) / revenue,
        depreciation=v("depreciation") / revenue,
        workingCapital=-working / increase,
        capexStart=v("capex") / revenue,
        capexEnd=v("capex") / revenue,
        leaseStart=v("financedAssets") / revenue,
        leaseEnd=v("financedAssets") / revenue,
        corporateStart=corp / revenue,
        corporateEnd=corp / revenue,
        discount=0.12,
        terminal=0.02,
    )
    corpus = load(c)
    index = {p["id"]: p for p in corpus["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("NVIDIA source passages changed")
    manifest = json.loads(
        (
            DOCUMENT_ROOT / f"data/sources/filing-{core['accession']}.manifest.json"
        ).read_text()
    )
    if manifest["sha256"] != ANNUAL_HTML or manifest["cik"] != 1045810:
        raise ValueError("NVIDIA annual narrative changed")
    ps = extract(read_verified(DOCUMENT_ROOT / manifest["file"], ANNUAL_HTML))
    lease_ps = [p for p in ps if p["ordinal"] in [813, 959, 1167]]
    if len(lease_ps) != 3:
        raise ValueError("NVIDIA annual lease cost scope missing")
    if manifest["file"] not in {s["file"] for s in c["sources"]}:
        c["sources"].append(manifest)
    current_url = source["primaryUrl"]
    m = dict(
        status="research_workspace",
        version="nvidia-operating-cash-path-v1",
        unallocatedPath=True,
        sourcePeriod=[h["start"], h["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        basisLabel="최근 1년 부문·본사·연결 현금 대사",
        growthLabel="최근 반기 전년 대비",
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        corporateLabel="본사 비용·주식보상·인수 관련 비용",
        netInterestLabel="이자수익−이자비용",
        capexLabel="설비·무형 현금 취득",
        leaseLabel="설비·무형 분할취득 원금",
        bridgeLabel="공시 연결 순이익 → 영업현금 대사",
        intro="컴퓨트·네트워킹과 그래픽스의 이익에서 미배분 주식보상·본사·인수 관련 비용을 뺍니다. 증권 평가이익을 반복 현금에서 분리하고 재고·수금·공급 약정과 AI 클라우드 구매 계약을 함께 검토합니다.",
        businessCaption="데이터센터·엣지 제품 매출과 두 영업부문은 다른 구분입니다. 데이터센터 매출 전체에 컴퓨트·네트워킹 이익률을 붙이거나 자동차 손익을 임의 배분하지 않습니다.",
        anchorSummary="최근 반기의 채권·재고·선급 및 기타자산·유동채무 현금 효과와 같은 반기 매출 증가를 연결합니다. 장기부채는 반복 영업자금에서 제외하며 그 증가 전액을 고객 선급금이라고 부르지 않습니다. 초기 21%는 공시에 언급된 미국 연방 법정세율을 비교 가정으로 쓴 것이며 실제 글로벌 현금세율이 아닙니다.",
        passages=[index[p] for p in PASSAGES],
        historicalPassages=[
            dict(p, sourceUrl=manifest["url"], sourceHash=ANNUAL_HTML) for p in lease_ps
        ],
        observedResidualLabel="영업현금 − 설비·무형 현금 취득 − 분할취득 원금 − 주식보상 비용 조정",
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=v("cfo")
            - v("capex")
            - v("financedAssets")
            - v("sbc"),
        ),
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=increase,
            corporateFacts=corporate,
            reportedCorporateCost=corp,
            actualFinanceLeasePrincipal=None,
        ),
        cashAnchors=[
            dict(
                label=label,
                period=period,
                value=value,
                sourceUrl=current_url,
                scope=scope,
            )
            for label, period, value, scope in [
                (
                    "공급·생산능력 확보 약정",
                    "2026-07-26",
                    279e9,
                    "기억장치·생산시설 중심의 미래 약정. 변경 가능 조건과 비용 별도; 현재 설비 현금 지출 아님",
                ),
                (
                    "연구개발 클라우드 서비스 약정",
                    "2026-07-26",
                    29e9,
                    "연구개발 인프라 계약. 아래 AI 클라우드 파트너 계약과 구분",
                ),
                (
                    "AI 클라우드 파트너 서비스 약정",
                    "2026-07-26",
                    36e9,
                    "통상 6년; 제3자 또는 자사 이용 시 감소. 전체 금액을 당기 비용·확정 현금 손실로 보지 않음",
                ),
                (
                    "확인된 분할취득 원금 지급",
                    "2026-01-26–2026-07-26",
                    facts["financedAssets"]["components"][1]["fact"]["value"],
                    "현금흐름표 재무활동 항목. 금융리스 전액이라고 바꾸지 않음",
                ),
                (
                    "금융리스 원금 전액",
                    "최근 1년",
                    None,
                    "별도 전액 미확인. 비용이 중요하지 않다는 공시는 실제 지급 영의 증거가 아님",
                ),
            ]
        ],
        rules=[
            "직전 연간+현재 반기−전년 반기로 두 부문과 연결 실적을 대사합니다. 각 기간의 본사 비용·주식보상·인수 관련 비용을 부문 이익에서 차감하며 현금표 주식보상 되돌림을 미래 현금에 다시 더하지 않습니다.",
            "투자 증권 이익은 보고 순이익과 영업현금 대사에서 차감됩니다. 미래 영업이익에 증권 평가·처분 이익을 더하지 않으며 투자자산 별도 가치는 미배분입니다.",
            "미래 상각은 현금표 감가·상각 비율, 투자는 설비·무형 현금 취득 비율에서 출발합니다. 취득자산 대금의 재무활동 원금 지급을 별도 차감하며 금융리스 원금 전액으로 표시하지 않습니다.",
            "운영리스 비용은 보고 영업손익에 포함됩니다. 운영리스 지급을 그 비용 외에 전액 추가 차감하지 않습니다. 새 미개시 데이터센터 계약은 개시 시점과 재배정 가능성을 별도 검토해야 합니다.",
            "공급·생산능력 약정은 향후 매출원가·재고·지급 시점과 연결될 금액입니다. 현재 자본적 지출과 같은 금액으로 빼거나 미래 한 해 지출로 연환산하지 않습니다.",
            "AI 클라우드 파트너는 NVIDIA 인프라를 구매하고 NVIDIA는 서비스 이용을 약정합니다. 제3자 사용과 계약 조건에 따라 부담이 감소하므로 총 약정을 당기 환급액이나 부실 매출로 단정하지 않습니다. 실제 현금 지급·서비스 이용·제3자 판매를 후속 공시에서 대사해야 합니다.",
            "초기 21%는 연구 비교 세율이며 보고 글로벌 실효세율이나 현금 납세 예측이 아닙니다. 반기 세금 주석의 억 단위 반올림 대신 손익계산서 백만 달러 단위 원금액으로 대사합니다.",
            "H20·H200 재고·구매 의무 비용과 충당금 환입은 보고 사업 마진 안에 있습니다. 공급 제약·수출 제한·제품 전환이 계속될 수 있으므로 자동 일회성 제거하지 않습니다.",
            "추가 인수대금·비리스 순차입·금융자산 배분은 미래 기본값에 별도로 넣지 않았습니다. 정상 사업 현금의 검증이나 모든 주주 배분 가능 현금의 확정이 아닙니다.",
            "성장 0%·현재 마진과 본사 비율 유지, 요구수익률 12%·영구성장 2%는 비교 시작점입니다. 고객·공급·제품 전환과 계약 부담이 변하는 별도 시나리오를 함께 검토해야 합니다.",
        ],
        remaining=[
            "고객별 수금·직접/간접 고객 중복·선급금 소진",
            "공급·클라우드 계약의 실제 이행과 비용 반영",
            "제품 전환·수출 제약의 재고 및 구매 의무 비용",
            "금융리스 전액·미개시 계약·인수대금과 투자자산 가치 배분",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
