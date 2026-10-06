"""Broadcom segment costs, customer financing and contract revenue."""

import json
from .data import ROOT, canonical, digest, read_verified
from .narrative import load, extract
from .xbrl import company_filing, instance_rows, select

DOCUMENT_ROOT = ROOT / "artifacts/local/broadcom-study"
CURRENT = "0001730168-26-000080"
CORPUS = "965d893de9b66ba32400a567a25fe931201430ddcbca16b78ff975148719254e"
CURRENT_SHA = "cc0b495acb2d4f2b3b425baf26e4cb1073eda573b4892b4d4e769d2099ea55ef"
ANNUAL_SHA = "e1635fbb72a4cf49c8e3cfd5574e46e8e1b435b710912d5724bcebed5b8d601e"
ANNUAL_HTML = "d0746ce878e74bf06c92b5bdd542a9abe9f717d3dc2665a122a4b5a8ddfba44f"
TAGS = dict(
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    operatingIncome="OperatingIncomeLoss",
    netIncome="ProfitLoss",
    tax="IncomeTaxExpenseBenefit",
    pretax="IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    sbc="ShareBasedCompensation",
    depreciation="Depreciation",
    cashAmortization="Amortizationofintangibleandrightofuseassets",
    acquisitionAmortization="AmortizationOfIntangibleAssets",
    deferredTax="DeferredIncomeTaxesandOtherNoncashTaxExpense",
    debtExtinguishment="GainsLossesOnExtinguishmentOfDebt",
    financingAmortization="AmortizationOfFinancingCostsAndDiscounts",
    otherNoncash="OtherNoncashIncomeExpense",
    receivables="IncreaseDecreaseInAccountsReceivable",
    inventory="IncreaseDecreaseInInventories",
    payables="IncreaseDecreaseInAccountsPayable",
    employee="IncreaseDecreaseInEmployeeRelatedLiabilities",
    otherCurrent="IncreaseDecreaseInOtherCurrentAssetsAndLiabilitiesNet",
    otherLong="IncreaseDecreaseInOtherNoncurrentAssetsAndLiabilitiesNet",
    capex="PaymentsToAcquirePropertyPlantAndEquipment",
    interestExpense="InterestExpense",
)
ANNUAL_TAGS = dict(interestExpense="InterestExpenseNonoperating")
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("cashAmortization", "무형·사용권자산 상각 조정", 1),
    ("depreciation", "감가상각 조정", 1),
    ("sbc", "주식보상 비용 조정", 1),
    ("deferredTax", "이연·기타 비현금 법인세", 1),
    ("debtExtinguishment", "차입 조기상환 손실 조정", -1),
    ("financingAmortization", "금융비용·할인 상각 조정", 1),
    ("otherNoncash", "기타 비현금 조정", -1),
    ("receivables", "매출채권 현금 변동", -1),
    ("inventory", "재고 현금 변동", -1),
    ("payables", "매입채무 현금 변동", 1),
    ("employee", "임직원 보상·복리후생 현금 변동", 1),
    ("otherCurrent", "기타 유동 자산·부채 현금 변동", -1),
    ("otherLong", "기타 장기 자산·부채 현금 변동", -1),
]
PASSAGES = [
    "de1eb61bb5255b2c6a6b",
    "3cfe5fa623cddb482a2b",
    "b8adaceafe2970d66e0d",
    "9c59ee17df25f0e4f96f",
    "8af10929c539d4fd8227",
    "9b9df3bed29f0c8ffdcb",
    "d0a563d4a623e99be847",
    "c0690c82ca2270420019",
    "c474051eb034c5917fc5",
    "4ddfc0e9e61913df446a",
    "8fd33d3f8d1935a1a9b5",
    "1bc81cf8e833fdd5331b",
    "7e651c31dbaa36fe7801",
    "2ef652fcb2a8b62762c4",
    "dd5586da8ded19664709",
    "6cc4ecbb8a5652ff6cb3",
    "d4162e26d3b06a7ef8e6",
    "f4c058393a1e5aeedc41",
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
            reason="Broadcom의 고객 금융·계약 인식·부문 현금을 새 공시와 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    annual_source = h["review"]["annualSource"]
    if source["sha256"] != CURRENT_SHA or annual_source["sha256"] != ANNUAL_SHA:
        raise ValueError("Broadcom source identity changed")
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if core["accession"] != "0001730168-25-000121":
        raise ValueError("Broadcom annual identity changed")
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
            raise ValueError("Broadcom source missing: " + tag)
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

    facts = {key: combine(key, tag) for key, tag in TAGS.items()}
    v = lambda key: facts[key]["value"]
    corporate = h["reconciliations"]["operatingIncome"]["adjustments"]
    if len(corporate) != 4:
        raise ValueError("Broadcom needs all four corporate cost series")
    corporate_cost = -sum(x["coefficient"] * x["series"]["value"] for x in corporate)
    checks = []
    for i, (coefficient, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        cash = sum(sign * val(key) for key, _, sign in CASH)
        cost = -sum(
            x["coefficient"]
            * x["series"]["components"][i]["coefficient"]
            / coefficient
            * x["series"]["components"][i]["fact"]["value"]
            for x in corporate
        )
        income = sum(
            s["operatingIncome"]["components"][i]["fact"]["value"]
            for s in h["segments"]
        )
        revenue = sum(
            s["revenue"]["components"][i]["fact"]["value"] for s in h["segments"]
        )
        if (
            cash != val("cfo")
            or income - cost != val("operatingIncome")
            or revenue != val("revenue")
            or val("pretax") - val("tax") != val("netIncome")
        ):
            raise ValueError(
                f"Broadcom period cash or segment income does not reconcile: {end}; cash={cash-val('cfo')}; operating={income-cost-val('operatingIncome')}; revenue={revenue-val('revenue')}; net={val('pretax')-val('tax')-val('netIncome')}"
            )
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=val("cfo"),
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
    revenue = v("revenue")
    if revenue != c["trailingYear"]["values"]["revenue"]["value"]:
        raise ValueError("Broadcom trailing revenue differs")
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
        if key in {"receivables", "inventory", "payables", "employee", "otherCurrent"}
    )
    increase = (
        facts["revenue"]["components"][1]["fact"]["value"]
        - facts["revenue"]["components"][2]["fact"]["value"]
    )
    if increase <= 0:
        raise ValueError("Broadcom capital proxy requires review")
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
        corporateStart=corporate_cost / revenue,
        corporateEnd=corporate_cost / revenue,
        discount=0.12,
        terminal=0.02,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("Broadcom source passages changed")
    manifest = json.loads(
        (
            DOCUMENT_ROOT / f"data/sources/filing-{core['accession']}.manifest.json"
        ).read_text()
    )
    if manifest["sha256"] != ANNUAL_HTML or manifest["cik"] != 1730168:
        raise ValueError("Broadcom annual narrative changed")
    ps = extract(read_verified(DOCUMENT_ROOT / manifest["file"], ANNUAL_HTML))
    annual_ps = [p for p in ps if p["ordinal"] in [527, 528, 925, 927]]
    if len(annual_ps) != 4:
        raise ValueError("Broadcom annual lease evidence changed")
    if manifest["file"] not in {s["file"] for s in c["sources"]}:
        c["sources"].append(manifest)
    m = dict(
        status="research_workspace",
        version="broadcom-contract-operating-cash-v1",
        unallocatedPath=True,
        sourcePeriod=[h["start"], h["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        basisLabel="최근 1년 부문·연결 현금 대사",
        growthLabel="최근 9개월 전년 대비",
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        corporateLabel="미배분 보상·인수 상각·구조조정·인수 비용",
        netInterestLabel="보고 이자비용 차감 · 수익 미반영",
        capexLabel="설비 현금 취득 · 인수대금 별도",
        leaseLabel="금융리스 원금 가정 · 실제 미확인",
        bridgeLabel="연결 순이익 → 영업현금 대사",
        intro="반도체 솔루션과 인프라 소프트웨어 부문에서 출발해 네 가지 미배분 비용을 연결합니다. 고객의 구매와 금융 조달, 소프트웨어 계약의 해지권과 수익 인식, 채권 매각을 영업 성장과 구별해 읽습니다.",
        businessCaption="반도체에는 AI 가속기·네트워크 외의 제품과 IP도 포함됩니다. 소프트웨어에는 VCF와 다른 인프라 사업이 들어갑니다. 두 부문의 마진을 XPU·VMware 단독 마진으로 바꾸지 않습니다.",
        anchorSummary="현재 9개월 영업자산·유동부채의 현금 효과를 같은 기간 매출 증가에 연결합니다. 비현금 이자·기타 장기 자산부채는 운전자본 성장 대용에서 제외합니다. 21% 세율과 금융리스 추가 지급 0은 연구 가정이며 확정 세금·관측 지급액이 아닙니다.",
        passages=[index[p] for p in PASSAGES],
        historicalPassages=[
            dict(p, sourceUrl=manifest["url"], sourceHash=ANNUAL_HTML)
            for p in annual_ps
        ],
        observedResidualLabel="영업현금 − 설비 현금 취득 − 주식보상 비용 조정 · 금융리스 전액 별도 미확인",
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
            reportedCorporateCost=corporate_cost,
            corporateAdjustments=corporate,
            actualFinanceLeasePrincipal=None,
            cashAmortization=v("cashAmortization"),
            acquisitionAmortization=v("acquisitionAmortization"),
            unmodeledAmortization=v("cashAmortization") - v("acquisitionAmortization"),
            backstopMaximum=29e9,
            backstopPaid=0,
            customerNotesMaximum=42e9,
            customerNotesIssued=0,
        ),
        contractSupport=dict(
            maximumExposure=29e9,
            sourceUrl=source["primaryUrl"],
            sourcePassage="8fd33d3f8d1935a1a9b5",
            label="AI랙 고객 리스 Backstop",
            scope="모든 랙 배치를 가정한 비할인 최대액. 손실 비율은 고객 부도·85% 잔여의무·회수자산·구제수단을 거친 최종 순지급액의 가정이며 발생확률이 아닙니다.",
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
                    "미이행 계약의 배분 거래가격",
                    "2026-08-02",
                    179.2e9,
                    "약 25%를 향후12개월 매출로 기대. 해지권·단기계약·로열티 제외; 확정 현금 유입이나 전체 미래 매출 아님",
                ),
                (
                    "무조건부 구매 약정",
                    "2026-08-02",
                    126.821e9,
                    "잔여1년 이하 계약 제외. 재고 중심 총액이며 당기 취득 현금·한 해 지출 아님",
                ),
                (
                    "고객 리스 Backstop 최대 노출",
                    "모든 AI랙 배치 가정 · 5년리스",
                    29e9,
                    "고객 부도·잔여의무85%·회수자산가치·구제수단에 따른 조건부 부담. 현재 지급0; 전액 손실 아님",
                ),
                (
                    "고객이 발행할 수 있는 전환어음 한도",
                    "2026-08-02",
                    42e9,
                    "고객 리스의무용·조건 충족 시 발행. 발행0; Broadcom 자기주식 희석이나 보유현금42bn 아님",
                ),
                (
                    "비소구 매출채권 매각",
                    "현재9개월",
                    3.950e9,
                    "영업현금에 포함된 매각채권액. 직전9개월5.651bn; 매각총액을 CFO에서 단순차감하면 정상회수도 중복제거 가능",
                ),
                (
                    "확인한 금융리스 원금 전액",
                    "최근1년",
                    None,
                    "연말 리스부채0이 기간 지급0을 입증하지 않음. 미래 기본0은 명시적 가정",
                ),
            ]
        ],
        rules=[
            "연간+현재9개월−전년9개월로 현금을 연결하고 세 기간 각각 순이익·부문 이익·미배분 비용을 대사합니다. 첫 미배분 항목만 쓰지 않고 상각·보상·구조조정·인수 비용 네 가지를 모두 차감합니다.",
            "미배분 비용을 뺀 뒤 감가·인수 무형상각만 되돌리고 주식보상은 대체 비용으로 남깁니다. 현금표 무형·사용권자산 상각 전체를 되돌려 운영리스 비용을 없애지 않습니다. 무형자산 대체 인수·개발의 정상 부담은 아직 확정하지 않았습니다.",
            "이자비용은 손익 비용을 미래 대용으로 남깁니다. 비현금 금융상각을 현금표에서 되돌린 사실과 미래 대용 가정을 구별하며 이자수익·투자이익·매각손익은 기본 경로에 더하지 않습니다.",
            "해지권 없는 소프트웨어 계약의 추가 라이선스 인식과 반복 현금 회수를 구분합니다. 제품/서비스 매출 재분류를 반도체/소프트웨어 부문 간 사업 이동으로 오인하지 않습니다.",
            "채권 비소구 매각은 보고 영업현금에 포함됩니다. 매각총액만으로 수금 개선·부실을 판정하지 않고 원래 만기·매각수수료·매각 없는 잔액과 기간 현금 전환을 추가 확인합니다.",
            "AI XPV Backstop 최대29bn은 모든 랙 배치를 가정한 조건부 최대 노출입니다. 고객 부도 때 잔여의무85%와 자산회수·구제수단을 따르며 현재 지급액은0입니다. 기대손실·현재부채로 최대액을 자동 차감하거나 낮은 장부 공정가치를 무위험으로 읽지 않습니다.",
            "42bn 전환어음은 고객이 Broadcom에 발행할 수 있는 권리입니다. Broadcom이 고객에게 발행한 주식 권리와 구분하며 현재 미발행 상태에서 현금·투자자산 또는 자기주식 희석을 만들어 넣지 않습니다.",
            "현재 기본 경로에는 고객 금융 보증의 미래 지급을 포함하지 않습니다. 이는 지급확률0의 예측이 아니며 원계약·배치 일정·상대방 지급과 회수자산에 대한 조건부 손실 검토가 추가로 필요합니다.",
            "최대 고객 직접매출은 유통상 비중이며 상위 최종고객의 합계와 다릅니다. 서로 다른 고객 집중 지표를 중복 합치지 않습니다.",
        ],
        remaining=[
            "AI XPV 원계약·배치별 보증과 실제 지급·회수조건",
            "해지권 제거에 따른 선인식과 반복 매출·현금 전환",
            "채권 매각 전 현금 회수·조건과 투자자산 대체 부담",
            "금융리스 원금 전액 및 계속영업 범위의 긴 이력",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
