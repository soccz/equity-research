"""AMD continuing operations, corporate adjustments and contingent commitments."""

import json
from .data import ROOT, canonical, digest, read_verified
from .narrative import load, extract
from .xbrl import company_filing, instance_rows, select

DOCUMENT_ROOT = ROOT
CURRENT = "0000002488-26-000123"
CORPUS = "727a7e15fe6960a693ad9c2c0e435ad56f253bbd41e474bc9bc58df7c8a52d91"
CURRENT_SHA = "39e82b6aaec2de306ebbe9368ec7d71375d45cb7f36e0e0f2cbcc34ad50c8a09"
ANNUAL_SHA = "7a073e96fa640527505f4b53c4cda1f5b0af4d6e6a3b54b4cb056e78c36d328e"
ANNUAL_HTML = "9ffe0320478f60eb39b134bc38d123da29f01bc03862a996ee23cfeea81f367e"
TAGS = dict(
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    operatingIncome="OperatingIncomeLoss",
    netIncome="NetIncomeLoss",
    continuingIncome="IncomeLossFromContinuingOperations",
    discontinuedIncome="OtherAdjustmentsToIncomeDiscontinuedOperations",
    tax="IncomeTaxExpenseBenefit",
    pretax="IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    equityIncome="IncomeLossFromEquityMethodInvestments",
    cfo="NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    totalCfo="NetCashProvidedByUsedInOperatingActivities",
    discontinuedCfo="CashProvidedByUsedInOperatingActivitiesDiscontinuedOperations",
    sbc="ShareBasedCompensation",
    depreciation="OtherDepreciationAndAmortization",
    acquisitionAmortization="AmortizationOfIntangibleAssets",
    deferredTax="DeferredIncomeTaxesAndTaxCredits",
    equityGains="GainsLossesOnLongTermInvestmetnsNet",
    otherNoncash="OtherNoncashIncomeExpense",
    receivables="IncreaseDecreaseInAccountsReceivable",
    inventory="IncreaseDecreaseInInventories",
    prepaids="IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",
    payables="IncreaseDecreaseInAccountsPayable",
    accrued="IncreaseDecreaseInAccruedLiabilitiesAndOtherOperatingLiabilities",
    capex="PaymentsToAcquirePropertyPlantAndEquipment",
    interestExpense="InterestExpense",
)
ANNUAL_TAGS = dict(
    acquisitionAmortization="AdjustmentForAmortization",
    equityGains="GainLossOnSaleOfInvestments",
)
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("discontinuedIncome", "중단영업 순이익 제거", -1),
    ("sbc", "주식보상 비용 조정", 1),
    ("depreciation", "감가상각·기타 상각", 1),
    ("acquisitionAmortization", "인수 무형자산 상각", 1),
    ("deferredTax", "이연 법인세", 1),
    ("equityGains", "장기투자 이익 차감", -1),
    ("otherNoncash", "기타 비현금 조정", -1),
    ("receivables", "매출채권 변동", -1),
    ("inventory", "재고 변동", -1),
    ("prepaids", "선급 및 기타 자산 변동", -1),
    ("payables", "매입채무 변동", 1),
    ("accrued", "미지급 및 기타 부채 변동", 1),
]
PASSAGES = [
    "1c17fe64a2843e34fcc7",
    "550afa4afbf039ef9ea7",
    "219d124c87c82baf3fe3",
    "a238aba746139a0da83d",
    "774981b0a23e332deb8f",
    "9a21c5bbea6f3395b74c",
    "24a32cccd89c556d092c",
    "c5427723554025e4e12d",
    "25eb18fef39aee25c3eb",
    "a0dfe2ad14de1fbb42a5",
    "80960baaf2ebba1336fb",
    "2b45695ba6ace13eeaa3",
    "7322c7028f6573823f53",
    "df7884cadc08682ad73c",
    "0141d2786bc1296231b6",
    "3099be0239ad320f1d14",
    "13e6dfba21df8bd222a0",
    "a4c61e3d0f3fb5d55688",
]


def build(c, as_of):
    from .operating_model import calculate

    meta, h = c.get("narrative") or {}, c.get("segmentHistory") or {}
    if (
        meta.get("accession") != CURRENT
        or meta.get("evidenceHash") != CORPUS
        or h.get("status") != "ready"
    ):
        return dict(
            status="source_review_required",
            reason="AMD 계속영업·부문·조건부 권리의 새 공시를 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    annual_source = h["review"]["annualSource"]
    if source["sha256"] != CURRENT_SHA or annual_source["sha256"] != ANNUAL_SHA:
        raise ValueError("AMD source identity changed")
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if core["accession"] != "0000002488-26-000018":
        raise ValueError("AMD annual identity changed")
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

    def exact(rs, tag, start, end):
        r = select(rs, tag, start, end, (), "USD")
        if r is None:
            raise ValueError("AMD cash source missing: " + tag)
        return r

    def combine(key, tag):
        ps = [
            dict(
                coefficient=k,
                fact=exact(
                    rs, ANNUAL_TAGS.get(key, tag) if i == 0 else tag, start, end
                ),
            )
            for i, (k, rs, start, end) in enumerate(periods)
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in ps),
            components=ps,
            unit="USD",
            derived=True,
            sourceUrl=source["primaryUrl"],
        )

    facts = {k: combine(k, tag) for k, tag in TAGS.items()}
    v = lambda key: facts[key]["value"]
    recovery = exact(
        annual,
        "InventoryLossAtRecoveryFromContractManufacturer",
        core["start"],
        core["end"],
    )
    corporate = h["reconciliations"]["operatingIncome"]["adjustments"][0]["series"]
    checks = []
    for i, (coefficient, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        cash = sum(sign * val(key) for key, _, sign in CASH) + (
            recovery["value"] if i == 0 else 0
        )
        part = corporate["components"][i]
        cost = -part["coefficient"] / coefficient * part["fact"]["value"]
        income = sum(
            s["operatingIncome"]["components"][i]["fact"]["value"]
            for s in h["segments"]
        )
        revenue = sum(
            s["revenue"]["components"][i]["fact"]["value"] for s in h["segments"]
        )
        if (
            cash != val("cfo")
            or val("cfo") + val("discontinuedCfo") != val("totalCfo")
            or val("netIncome") - val("discontinuedIncome") != val("continuingIncome")
            or val("pretax") - val("tax") + val("equityIncome")
            != val("continuingIncome")
            or income - cost != val("operatingIncome")
            or revenue != val("revenue")
        ):
            raise ValueError(
                "AMD period cash or continuing segment income does not reconcile"
            )
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=val("cfo"),
                totalCfo=val("totalCfo"),
                discontinuedCfo=val("discontinuedCfo"),
                capex=val("capex"),
                corporateCosts=cost,
                residual=0,
                incomeResidual=0,
                revenueResidual=0,
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
    parts.append(
        dict(
            label="직전 연간 계약 제조사 재고 손실 회수",
            value=recovery["value"],
            fact=dict(
                sourceUrl=recovery["sourceUrl"],
                components=[dict(coefficient=1, fact=recovery)],
            ),
        )
    )
    revenue = v("revenue")
    if revenue != c["trailingYear"]["values"]["revenue"]["value"]:
        raise ValueError("AMD trailing revenue differs")
    segments = []
    for s in h["segments"]:
        current, prior = [
            s["revenue"]["components"][i]["fact"]["value"] for i in [1, 2]
        ]
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
        raise ValueError("AMD capital proxy requires review")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.21,
        netInterest=-v("interestExpense") / revenue,
        depreciation=(v("depreciation") + v("acquisitionAmortization")) / revenue,
        workingCapital=-working / increase,
        capexStart=v("capex") / revenue,
        capexEnd=v("capex") / revenue,
        leaseStart=0,
        leaseEnd=0,
        corporateStart=-corporate["value"] / revenue,
        corporateEnd=-corporate["value"] / revenue,
        discount=0.12,
        terminal=0.02,
    )
    corpus = load(c)
    index = {p["id"]: p for p in corpus["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("AMD source passages changed")
    manifest = json.loads(
        (
            DOCUMENT_ROOT / f"data/sources/filing-{core['accession']}.manifest.json"
        ).read_text()
    )
    if manifest["sha256"] != ANNUAL_HTML or manifest["cik"] != 2488:
        raise ValueError("AMD annual narrative changed")
    ps = extract(read_verified(DOCUMENT_ROOT / manifest["file"], ANNUAL_HTML))
    annual_ps = [
        p
        for p in ps
        if p["ordinal"] in [475, 498, 608, 613, 614, 622, 623, 626, 635, 698, 910, 1110]
    ]
    if len(annual_ps) != 12:
        raise ValueError("AMD annual cash/lease passages missing")
    if manifest["file"] not in {s["file"] for s in c["sources"]}:
        c["sources"].append(manifest)
    m = dict(
        status="research_workspace",
        version="amd-continuing-operating-cash-v1",
        unallocatedPath=True,
        sourcePeriod=[h["start"], h["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        basisLabel="최근 1년 계속영업 부문·현금 대사",
        growthLabel="최근 반기 전년 대비",
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        corporateLabel="미배분 주식보상·인수 상각·기타 비용",
        netInterestLabel="이자비용 차감 · 이자수익 미반영",
        capexLabel="계속영업 설비 현금 취득",
        leaseLabel="금융리스 원금 가정 · 실제액 미확인",
        bridgeLabel="연결 순이익 → 계속영업 영업현금 대사",
        intro="매각한 ZT 제조사업의 손익·현금을 분리하고 세 사업부 이익에서 미배분 주식보상·인수 상각·관련 비용을 뺍니다. 인수 무형자산 상각의 되돌림과 후속 기술 투자 부담을 구분하며, 고객 구매에 연동된 주식 권리도 함께 검토합니다.",
        businessCaption="클라이언트·게이밍은 하나의 영업부문입니다. PC 출하·가격과 게임 매출의 다른 방향을 보존하며, 따로 공시되지 않은 PC·게임 이익률이나 데이터센터 GPU 단독 마진을 만들지 않습니다.",
        anchorSummary="현재 반기 계속영업의 채권·재고·선급·채무 현금 효과를 같은 기간 매출 증가와 연결합니다. 미래 초기 세율 21%는 연구 가정이며 과거 세금 구제 혜택을 반복하지 않습니다. 이자수익·투자 평가이익과 관계기업 손익은 미래 기본값에서 제외합니다.",
        passages=[index[p] for p in PASSAGES],
        historicalPassages=[
            dict(p, sourceUrl=manifest["url"], sourceHash=ANNUAL_HTML)
            for p in annual_ps
        ],
        observedResidualLabel="계속영업 영업현금 − 설비 현금 취득 − 주식보상 비용 조정 · 금융리스 별도 미확인",
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=v("cfo") - v("capex") - v("sbc"),
        ),
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=increase,
            reportedCorporateCost=-corporate["value"],
            totalCfo=v("totalCfo"),
            discontinuedCfo=v("discontinuedCfo"),
            actualFinanceLeasePrincipal=None,
            inventoryRecovery=recovery,
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
                (
                    "분리한 중단영업 현금",
                    "최근 1년",
                    v("discontinuedCfo"),
                    "보고 총액에서 분리. 새 계속영업 현금표와 일반 연결 총액은 서로 다른 범위",
                ),
                (
                    "무조건부 구매·서비스 약정",
                    "2026-06-27",
                    30.3e9,
                    "웨이퍼·부품·클라우드·라이선스. 잔여 2026년분 17.4bn; 현재 지급액 아님",
                ),
                (
                    "미개시 리스 지급 약정",
                    "2026-06-27",
                    4.5e9,
                    "개시 전 총 미래 지급액이며 현재 리스 원금 지급액 아님",
                ),
                (
                    "상업 파트너 리스 최대 보증",
                    "2026-06-27",
                    4.1e9,
                    "최대 15년·상대방 부도 시 지급 조건. 현재 손실·전액 차입금 아님",
                ),
                (
                    "후속 조건부 투자 약정",
                    "2026-06-27 이후 · 현재 10-Q 공시",
                    5e9,
                    "조건 충족 시 최대 금액, 2028년까지 예정. 결산일 현재 집행금액 아님",
                ),
                (
                    "후속 데이터센터 리스 약정",
                    "2026-06-27 이후 · 현재 10-Q 공시",
                    9.5e9,
                    "2027·2028 개시 예정·최대 16년. 위 결산일 약정과 시점 구분",
                ),
                (
                    "금융리스 원금 전액",
                    "최근 1년",
                    None,
                    "연간 공시는 중요하지 않다고 설명하나 정확한 지급액 영을 증명하지 않음",
                ),
            ]
        ],
        rules=[
            "연간+현재 반기−전년 반기로 계속영업 현금을 연결합니다. 각 기간 순이익에서 중단영업 순이익을 제거하고 세 부문 손익과 연결 계속영업 손익을 대사합니다. 중단영업 현금은 미래 사업현금에 더하지 않습니다.",
            "연간 인수 상각·장기투자이익 태그가 현재 반기와 다릅니다. 연간 계약 제조사 재고 회수는 별도 행이며, 연간 이연세금 조정은 양수입니다. 다른 기간의 태그·부호를 덮어쓰지 않습니다.",
            "계속영업 설비 취득만 사용합니다. 매각한 ZT 제조사업의 설비 지급·처분대금과 이번 반기 매각 정산 지급 243백만 달러는 계속영업 투자에서 분리합니다. 별도 인수대금과 금융자산 매입도 정상 설비 투자에 섞지 않습니다.",
            "보고 부문 이익은 미배분 주식보상과 인수 무형자산 상각을 제외합니다. 본사 비용으로 먼저 차감하고 감가·상각을 현금 조정으로 되돌리되 주식보상을 다시 더하지 않습니다. 인수자산 상각 되돌림은 대체 기술·고객관계 투자가 필요 없다는 뜻이 아닙니다.",
            "금융리스 실제 지급액은 미확인입니다. 초기 별도 원금 가정 0은 연구 시작점이며 확인된 지급 영이 아닙니다. 운영리스 비용은 영업이익에 포함되어 전액 중복 차감하지 않습니다. 새 대규모 미개시 리스는 미래 비용·투자 가정의 추가 근거가 필요합니다.",
            "초기 이자 가정은 보고 이자비용만 차감합니다. 이자수익 미반영은 연구자 선택이며 실제 수익 영이 아닙니다. 장기투자 이익·관계기업 손익과 비영업자산 가치를 자동 주주 현금으로 배분하지 않습니다.",
            "OpenAI·Meta의 워런트는 각각 최대 1억6천만 주이며 결산일 가득·행사 가능 수량은 영입니다. 구매·주가·기술·상업 조건의 충족에 따른 희석을 확인하기 전 최대 3억2천만 주를 현재 유통주식에 더하거나 희석이 없다고 단정하지 않습니다.",
            "파트너 리스 보증의 최대 노출과 직접 지급 의무·구매 약정·후속 투자 약정을 구분합니다. 계약 총액을 한 해 현금 지출로 연환산하거나 조건부 보증 전액을 확정 손실로 넣지 않습니다.",
            "초기 성장 0%·현재 마진·요구수익률 12%·영구성장 2%는 비교 시작 가정입니다. 출하와 평균가격·게임 약세·데이터센터 믹스 및 수출 규제 비용을 반영한 대안 경로를 함께 검토해야 합니다.",
        ],
        remaining=[
            "고객 워런트 원계약별 가득·행사·주가 조건 및 최신 희석",
            "계속영업 기준 장기 현금 비교와 인수 무형자산 대체 투자",
            "신규 리스 개시·실제 금융리스 원금·보증 이행",
            "고객 GPU 구매 이행·현금 회수·재고 및 공급 약정 전환",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
