"""Applied Materials: issuer-recast segment history with exact cash periods."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT / "artifacts/local/applied-study"
CURRENT = "0001628280-26-058235"
CORPUS = "2786cc7cda304365a90d6325336711dcc418759e804c0771c62334bdfe114bc8"
CURRENT_SHA = "b99f8724b74013f5167d3842cd7f9acfbd92076a4c73290b3c24d1798ee5d0a9"
ANNUAL_SHA = "577915485e85536faa5c0d86be33ddb2dda1445478c9f49a61c6f24ac274f02d"
ANNUAL_HTML = "06e824d2f5b5200a80b682a9f690361f67ac71f803fc53e57cd1d1607e356297"
RECAST_SHA = "a62200d39fa26fe93a434201a29871eb1777a78b166eb1ba5ed64572db55486f"
RECAST_MANIFEST = "data/sources/filing-AMAT-20260212-segment-recast.manifest.json"
SEGMENTS = [
    (
        "SemiconductorSystemsSegmentMember",
        "반도체 시스템",
        [5597, 5401, 5564, 4879],
        [1872, 1770, 1837, 1430],
    ),
    (
        "AppliedGlobalServicesSegmentMember",
        "Applied Global Services",
        [1353, 1420, 1463, 1506],
        [336, 378, 400, 433],
    ),
    ("Other", "기타 사업·비배분 항목", [216, 279, 275, 415], [-33, 21, -4, -151]),
]
TAGS = dict(
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    operatingIncome="OperatingIncomeLoss",
    netIncome="NetIncomeLoss",
    pretax="IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    tax="IncomeTaxExpenseBenefit",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    depreciation="DepreciationAndAmortization",
    restructuring="RestructuringCosts",
    investmentGain="GainLossOnInvestments",
    sbc="ShareBasedCompensation",
    deferredTax="IncreaseDecreaseInDeferredIncomeTaxes",
    other="OtherOperatingActivitiesCashFlowStatement",
    receivables="IncreaseDecreaseInAccountsReceivable",
    inventory="IncreaseDecreaseInInventories",
    otherAssets="IncreaseDecreaseInOtherOperatingAssets",
    payables="IncreaseDecreaseInAccountsPayableAndAccruedLiabilities",
    contractLiabilities="IncreaseDecreaseInContractWithCustomerLiability",
    taxPayable="IncreaseDecreaseInAccruedIncomeTaxesPayable",
    otherLiabilities="IncreaseDecreaseInOtherOperatingLiabilities",
    capex="PaymentsToAcquirePropertyPlantAndEquipment",
    interestIncome="InvestmentIncomeInterest",
    interestExpense="InterestExpenseNonoperating",
)
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("depreciation", "감가상각·상각 조정", 1),
    ("restructuring", "현금표 구조조정 조정", 1),
    ("investmentGain", "투자 이익·손상 조정", -1),
    ("sbc", "현금표 주식보상 조정", 1),
    ("deferredTax", "이연 법인세 조정", -1),
    ("other", "기타 영업현금 조정", 1),
    ("receivables", "매출채권 현금 변동", -1),
    ("inventory", "재고 현금 변동", -1),
    ("otherAssets", "기타 영업자산 현금 변동", -1),
    ("payables", "매입채무·미지급 현금 변동", 1),
    ("contractLiabilities", "계약부채 현금 변동", 1),
    ("taxPayable", "미지급 법인세 현금 변동", 1),
    ("otherLiabilities", "기타 부채 현금 변동", 1),
]
PASSAGES = [
    "576a980f308fb69b495e",
    "296a7b7a138f9faf5267",
    "d696b0524116dd649024",
    "19a34fa5d98ce844f19a",
    "bae93b0df6a530b5d624",
    "69cf07823d356771b420",
    "1436301441455453f83b",
    "aa5c8346367badc1d838",
    "638cbf5c2027060942db",
    "1a28193c8c07f4a9f8d2",
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="Applied Materials의 200mm 사업 이동·본사비 배분 기준과 현금을 새 공시에서 확인해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    annual = json.loads(
        (
            DOCUMENT_ROOT
            / "data/sources/filing-0001628280-25-056742-xbrl.manifest.json"
        ).read_text()
    )
    if (
        not source
        or source["sha256"] != CURRENT_SHA
        or annual["sha256"] != ANNUAL_SHA
        or annual["cik"] != 6951
    ):
        raise ValueError("Applied source identity changed")
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if core["accession"] != "0001628280-25-056742":
        raise ValueError("Applied annual identity changed")
    annual_rows = instance_rows(
        read_verified(DOCUMENT_ROOT / annual["file"], ANNUAL_SHA),
        c,
        annual,
        core["accession"],
        core["filedAt"],
    )
    recast = json.loads((DOCUMENT_ROOT / RECAST_MANIFEST).read_text())
    if (
        recast["sha256"] != RECAST_SHA
        or recast["company"] != "AMAT"
        or recast["publishedAt"] > as_of
        or recast["page"] != 23
    ):
        raise ValueError("Applied recast source identity or point-in-time changed")
    read_verified(DOCUMENT_ROOT / recast["file"], RECAST_SHA)
    # Issuer's page 23 left-hand RECAST table: GAAP operating income, not
    # adjacent non-GAAP lines or the right-hand PREVIOUSLY REPORTED table.
    f = c["financials"]
    periods = [
        (1, annual_rows, core["start"], core["end"]),
        (1, rows, f["start"], f["end"]),
        (-1, rows, f["priorStart"], f["priorEnd"]),
    ]

    def exact(rs, tag, start, end, dims=()):
        r = select(rs, tag, start, end, dims, "USD")
        if r is None:
            raise ValueError("Applied cash fact missing: " + tag)
        return r

    def combine(key, tag):
        ps = [
            dict(coefficient=k, fact=exact(rs, tag, start, end))
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in ps),
            components=ps,
            sourceUrl=source["primaryUrl"],
            unit="USD",
            derived=True,
        )

    facts = {k: combine(k, t) for k, t in TAGS.items()}
    v = lambda k: facts[k]["value"]
    segments = []
    recast_rows = []
    for sid, label, qrev, qop in SEGMENTS:
        dims = (
            [("ConsolidationItemsAxis", "CorporateAndReconcilingItemsMember")]
            if sid == "Other"
            else [
                ("ConsolidationItemsAxis", "OperatingSegmentsMember"),
                ("StatementBusinessSegmentsAxis", sid),
            ]
        )
        current = exact(rows, TAGS["revenue"], f["start"], f["end"], dims)
        prior = exact(rows, TAGS["revenue"], f["priorStart"], f["priorEnd"], dims)
        current_op = exact(rows, TAGS["operatingIncome"], f["start"], f["end"], dims)
        prior_op = exact(
            rows, TAGS["operatingIncome"], f["priorStart"], f["priorEnd"], dims
        )
        if (
            sum(qrev[:3]) * 1e6 != prior["value"]
            or sum(qop[:3]) * 1e6 != prior_op["value"]
        ):
            raise ValueError("Applied recast quarter sum differs from comparative YTD")
        reported_rev = exact(annual_rows, TAGS["revenue"], core["start"], core["end"], dims)
        reported_op = exact(annual_rows, TAGS["operatingIncome"], core["start"], core["end"], dims)
        annual_rev = sum(qrev) * 1e6
        annual_op = sum(qop) * 1e6
        ttm_rev = annual_rev + current["value"] - prior["value"]
        ttm_op = annual_op + current_op["value"] - prior_op["value"]
        evidence = dict(
            start=core["start"],
            end=core["end"],
            value=annual_rev,
            unit="USD",
            sourceFile=recast["file"],
            sourceHash=RECAST_SHA,
            sourceUrl=recast["url"] + "#page=23",
            filedAt=recast["publishedAt"],
            derived=True,
            basis="issuer_recast_sum_of_four_quarters",
            quarterlyValues=[x * 1e6 for x in qrev],
        )
        segments.append(
            dict(
                id=sid,
                label=label,
                revenue=ttm_rev,
                margin=ttm_op / ttm_rev,
                observedGrowth=current["value"] / prior["value"] - 1,
                evidence=[evidence, current, prior],
            )
        )
        recast_rows.append(
            dict(
                id=sid,
                label=label,
                reportedAnnualRevenue=reported_rev,
                reportedAnnualOperatingIncome=reported_op,
                annualRevenue=annual_rev,
                annualOperatingIncome=annual_op,
                currentRevenue=current,
                priorRevenue=prior,
                currentOperatingIncome=current_op,
                priorOperatingIncome=prior_op,
                quarterRevenue=[x * 1e6 for x in qrev],
                quarterOperatingIncome=[x * 1e6 for x in qop],
                sourceUrl=evidence["sourceUrl"],
            )
        )
    checks = []
    for i, (k, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        cash = sum(sign * val(key) for key, _, sign in CASH)
        revenue = sum(
            (
                r["annualRevenue"]
                if i == 0
                else r["currentRevenue" if i == 1 else "priorRevenue"]["value"]
            )
            for r in recast_rows
        )
        income = sum(
            (
                r["annualOperatingIncome"]
                if i == 0
                else r["currentOperatingIncome" if i == 1 else "priorOperatingIncome"][
                    "value"
                ]
            )
            for r in recast_rows
        )
        if (
            cash != val("cfo")
            or revenue != val("revenue")
            or income != val("operatingIncome")
            or val("pretax") - val("tax") != val("netIncome")
        ):
            raise ValueError(
                f'Applied cash or recast segment reconciliation failed: {end} cash residual {cash-val("cfo")}'
            )
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=val("cfo"),
                reportedOperatingIncome=val("operatingIncome"),
                reportedRevenue=val("revenue"),
                residual=0,
                incomeResidual=0,
                revenueResidual=0,
            )
        )
    revenue = v("revenue")
    if (
        sum(s["revenue"] for s in segments) != revenue
        or revenue != c["trailingYear"]["values"]["revenue"]["value"]
    ):
        raise ValueError("Applied recast trailing revenue differs")
    working = sum(
        sign * facts[k]["components"][1]["fact"]["value"]
        for k, _, sign in CASH
        if k
        in {
            "receivables",
            "inventory",
            "otherAssets",
            "payables",
            "contractLiabilities",
        }
    )
    increase = (
        facts["revenue"]["components"][1]["fact"]["value"]
        - facts["revenue"]["components"][2]["fact"]["value"]
    )
    if increase <= 0:
        raise ValueError("Applied growth cash proxy requires review")
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
        leaseStart=0,
        leaseEnd=0,
        discount=0.12,
        terminal=0.02,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("Applied source passages changed")
    html = json.loads(
        (
            DOCUMENT_ROOT / "data/sources/filing-0001628280-25-056742.manifest.json"
        ).read_text()
    )
    if html["sha256"] != ANNUAL_HTML:
        raise ValueError("Applied annual text changed")
    ps = extract(read_verified(DOCUMENT_ROOT / html["file"], ANNUAL_HTML))
    annual_ps = [p for p in ps if p["ordinal"] in [596, 597, 598, 599, 600, 609, 611]]
    if len(annual_ps) != 7:
        raise ValueError("Applied annual cash paragraphs missing")
    for source_item in [annual, annual.get("indexSource"), html, recast]:
        if source_item and source_item["file"] not in {s["file"] for s in c["sources"]}:
            item = dict(source_item)
            item.setdefault("provider", "SEC")
            item.setdefault("retrievedAt", annual["retrievedAt"])
            read_verified(DOCUMENT_ROOT / item["file"], item["sha256"])
            c["sources"].append(item)
    m = dict(
        status="research_workspace",
        version="applied-recast-operating-cash-v1",
        sourcePeriod=["2025-07-28", f["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        basisLabel="새 부문 기준으로 재작성한 최근1년",
        growthLabel="재작성한 전년 9개월 대비",
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        groupLabel="두 공시 사업부와 기타 항목",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        bridgeLabel="연결 순이익 → 영업현금 대사",
        netInterestLabel="이자수익 − 이자비용",
        leaseLabel="금융리스 원금 가정 · 현재 미확인",
        intro="200mm 장비의 부문 이동과 본사 지원비의 완전 배분을 반영한 회사 재작성 표를 사용합니다. 반도체 시스템·AGS·기타의 손익을 연결한 뒤 투자 평가이익, 실제 설비 취득과 현금표 조정을 분리합니다.",
        businessCaption="Other는 독립적인 세 번째 공시 사업부가 아닙니다. 디스플레이 등 사업과 미배분 항목을 포함한 공시 범위를 그대로 보존합니다. AGS의 과거 200mm 장비를 서비스 매출로 계속 세거나 옛 본사비를 다시 차감하지 않습니다.",
        anchorSummary="현재 9개월 매출채권·재고·기타 자산·미지급·계약부채의 현금 효과를 같은 기간 매출 증가와 연결합니다. 미지급 세금·기타 장기부채는 성장 대용에서 제외합니다. 요구수익률·세율·금융리스 추가 지급은 연구자가 바꾸는 가정입니다.",
        passages=[index[p] for p in PASSAGES],
        historicalPassages=[
            dict(p, sourceUrl=html["url"], sourceHash=ANNUAL_HTML) for p in annual_ps
        ],
        observedResidualLabel="영업현금 − 설비 현금 취득 − 주식보상 조정 · 금융리스 전액 별도 미확인",
        bridge=dict(
            parts=[
                dict(
                    label=label,
                    value=sign * v(k),
                    fact=dict(
                        sourceUrl=source["primaryUrl"],
                        components=[
                            dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                            for p in facts[k]["components"]
                        ],
                    ),
                )
                for k, label, sign in CASH
            ],
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=v("cfo") - v("capex") - v("sbc"),
        ),
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=increase,
            actualFinanceLeasePrincipal=None,
            annualFinanceLeasePrincipal=0,
            recastSource=recast,
            recastSegments=recast_rows,
            legalSettlementExpense=253e6,
            legalSettlementPaid=253e6,
        ),
        cashAnchors=[
            dict(label=label, period=period, value=value, sourceUrl=url, scope=scope)
            for label, period, value, url, scope in [
                (
                    "재작성 반도체 연간 매출",
                    "2025 회계연도",
                    recast_rows[0]["annualRevenue"],
                    recast["url"] + "#page=23",
                    "새 기준 분기 네 개의 합; 이전20.798bn을 그대로 쓰지 않음",
                ),
                (
                    "재작성 AGS 연간 매출",
                    "2025 회계연도",
                    recast_rows[1]["annualRevenue"],
                    recast["url"] + "#page=23",
                    "200mm 장비 이동과 본사비 배분을 반영",
                ),
                (
                    "수출 규제 합의 비용·지급",
                    "현재9개월",
                    253e6,
                    source["primaryUrl"],
                    "현재 영업이익에 비용 포함·2분기 전액 지급. 미래 초기 마진에 포함되며 자동 환입하지 않음",
                ),
                (
                    "확인한 연간 금융리스 원금",
                    "2025 회계연도",
                    0,
                    html["url"],
                    "실제 연간0; 현재9개월 지급 미확인을 영으로 대체하지 않음",
                ),
                (
                    "금융리스 원금 전액",
                    "최근1년",
                    None,
                    source["primaryUrl"],
                    "미래 기본0은 연구 가정",
                ),
            ]
        ],
        rules=[
            "부문 연간값은 2026-02-12 회사 발표자료23쪽 RECAST 표의 GAAP 분기 네 개를 합칩니다. 오른쪽 이전 보고값과 Non-GAAP 이익률을 사용하지 않습니다. 세 분기 합을 현재10-Q의 재작성 전년9개월과 대사한 뒤 연간+현재9개월−전년9개월로 연결합니다.",
            "합계가 연결 매출·영업이익에 맞는지 세 기간마다 확인합니다. 본사 지원비가 새 부문에 이미 배분됐으므로 과거 본사비를 별도로 또 차감하지 않습니다.",
            "손익 구조조정 비용181m과 현금표 조정179m, 손익표 주식보상660m과 현금표 조정668m은 다른 범위입니다. 현금대사에는 현금표 항목을 쓰고 차이를 영으로 덮지 않습니다.",
            "투자 이익·손상은 현금표에서 제거한 원금액으로 대사합니다. 미래 기본 영업외는 이자수익−비용만 포함하며 투자 평가이익·배당·매각이익을 반복 현금으로 더하지 않습니다.",
            "253m 규제 합의 비용과 전액 지급은 같은 기간의 서로 다른 단계입니다. 비용과 현금을 중복 차감하지 않습니다. 정상화로 미래 마진을 높이려면 해당 일회 비용과 다른 수출 제한 영향을 각각 검토해야 합니다.",
            "설비 취득·기업 인수·금융투자를 분리합니다. 연구개발·고객 협업 시설 투자 확대가 미래 성장과 어느 시점에 연결되는지는 추가 근거가 필요합니다.",
            "금융리스 원금의 연간 영과 현재 기간 미확인을 구분합니다. 미래 추가원금0은 실제 보고0으로 표시하지 않습니다.",
            "현재 성장0·마진 유지·세율21%·요구수익률12%·영구성장2%는 비교 시작점입니다. 판독·계산 통과로 정상 현금이나 투자 선호를 승인하지 않습니다.",
        ],
        remaining=[
            "EPIC 등 투자 집행·정상 재투자와 현금 회수",
            "규제 합의 제외 마진과 지속 수출 제한의 별도 영향",
            "현재 금융리스 원금 및 주식보상 손익/현금 조정 차이",
            "설비·서비스의 고객 믹스·수익 인식과 경쟁 대안",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
