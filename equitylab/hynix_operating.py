"""SK hynix's sole operating segment, source-bound indirect cash reconciliation."""

import json
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from .data import ROOT, canonical, digest, read_verified
from .narrative import load
from .xbrl import company_filing, instance_rows, select

DOCUMENT_ROOT = ROOT
ACCESSION = "20260814003509"
CORPUS = "cc42332c9798267a3a1d67deb0af37fb3e34357ff2354ce780cc98d94332b34e"
CURRENT_XBRL = "9f76c636bc699d6c90b3fbd3e2f8d6c611a9b4427e305c426c80dba3c4a94563"
ANNUAL_XBRL = "d4d4c54b6d29401fe81d4e1d07258a01d606a649a481f86108d6c0b404891a07"
ANNUAL_DOC = "a60977e3b5cc989ee5f056dab5540f2c04bf86cea811beabe9384c30d8990a0c"
CONSOLIDATED = [
    ("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")
]
INDIRECT = sorted(
    CONSOLIDATED
    + [
        (
            "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis",
            "ReportedAmountMember",
        )
    ]
)
OTHER_PAY = "AdjustmentsForIncreaseDecreaseInOtherPayablesOfCashFlowsFromUsedInOperatingActivitiesLineItemsOfCashFlowsFromUsedInOperatingActivitiesTableOfItems"
PENSION = "AdjustmentsForPaymentOfExternallyFundedAssetsOfCashFlowsFromUsedInOperatingActivitiesLineItemsOfCashFlowsFromUsedInOperatingActivitiesTableOfItems"
# Coefficients are checked against each original Korean cash table, not inferred
# from the English tag name. The annual pension fact has the opposite raw sign.
ADJUSTMENTS = {
    "반기순이익": ("ProfitLoss", 1),
    "당기순이익": ("ProfitLoss", 1),
    "법인세비용": ("AdjustmentsForIncomeTaxExpense", 1),
    "이자비용": ("AdjustmentsForInterestExpense", 1),
    "이자수익": ("AdjustmentsForInterestIncome", -1),
    "감가상각비": ("AdjustmentsForDepreciationExpense", 1),
    "무형자산상각비": ("AdjustmentsForAmortisationExpense", 1),
    "퇴직급여": ("AdjustmentsForProvisionForSeveranceIndemnities", 1),
    "외화환산손실": ("AdjustmentsForLossesOnForeignExchangeTranslations", 1),
    "외화환산이익": ("AdjustmentsForGainOnForeignExchangeTranslations", -1),
    "금융상품처분이익": ("AdjustmentsForGainsOnDisposalsOfFinancialAssets", -1),
    "유형자산처분손실": (
        "AdjustmentsForLossesOnDispositionOfPropertyPlantAndEquipment",
        1,
    ),
    "유형자산처분이익": ("AdjustmentsForGainOnDispositionOfTangibleAssets", -1),
    "지분법손익": (
        "AdjustmentsForLossesOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
        1,
    ),
    "무형자산손상차손": ("AdjustmentsForImpairmentLossesOfIntangibleAssets", 1),
    "금융상품평가이익": (
        "AdjustmentsForGainsOnEvaluationOfFairValueFinancialAssets",
        -1,
    ),
    "금융상품평가손실": (
        "AdjustmentsForLossesOnEvaluationOfFairValueFinancialAssets",
        1,
    ),
    "파생상품관련손익": (
        "AdjustmentsForGainsLossesOnChangeInFairValueOfDerivatives",
        -1,
    ),
    "배당금수익": ("AdjustmentsForDividendIncome", 1),
    "지분법투자주식손상차손": (
        "AdjustmentsForImpairmentLossesOnInvestmentsInAssociates",
        1,
    ),
    "주식보상비용": ("AdjustmentsForShareBasedPayment", 1),
    "매각예정비유동자산처분이익": (
        "AdjustmentsForGainsOnDisposalsOfNoncurrentAssetsOrDisposalGroupsClassifiedAsHeldForSale",
        -1,
    ),
    "기타": ("OtherAdjustmentsToReconcileProfitLoss", 1),
    "매출채권의증가": ("AdjustmentsForDecreaseIncreaseInTradeAccountReceivable", 1),
    "재고자산의감소(증가)": ("AdjustmentsForDecreaseIncreaseInInventories", 1),
    "재고자산의증가": ("AdjustmentsForDecreaseIncreaseInInventories", 1),
    "기타자산의감소(증가)": ("AdjustmentsForDecreaseIncreaseInOtherAssets", 1),
    "기타수취채권의감소": (
        "AdjustmentsForDecreaseIncreaseInMiscellaneousReceivables",
        1,
    ),
    "매입채무의증가": ("AdjustmentsForIncreaseDecreaseInTradeAccountPayable", 1),
    "매입채무의감소": ("AdjustmentsForIncreaseDecreaseInTradeAccountPayable", 1),
    "미지급금의증가(감소)": ("AdjustmentsForIncreasedecreaseInOtherPayables", 1),
    "미지급금의증가": ("AdjustmentsForIncreasedecreaseInOtherPayables", 1),
    "기타지급채무의증가": (OTHER_PAY, 1),
    "충당부채의증가(감소)": ("AdjustmentsForIncreasedecreaseInProvisions", 1),
    "기타부채의증가(감소)": ("AdjustmentsForIncreaseDecreaseInOtherLiabilities", 1),
    "퇴직금의지급": ("CashOutflowForSeverancePay", -1),
    "사외적립자산의납부": (PENSION, -1),
}
TAGS = {
    "revenue": ("Revenue", CONSOLIDATED),
    "operatingIncome": ("OperatingIncomeLoss", CONSOLIDATED),
    "pretax": ("ProfitLossBeforeTax", CONSOLIDATED),
    "tax": ("IncomeTaxExpenseContinuingOperations", CONSOLIDATED),
    "netIncome": ("ProfitLoss", CONSOLIDATED),
    "cashOperations": ("CashFlowsFromUsedInOperations", CONSOLIDATED),
    "cfo": ("CashFlowsFromUsedInOperatingActivities", CONSOLIDATED),
    "capex": (
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        CONSOLIDATED,
    ),
    "intangibles": (
        "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
        CONSOLIDATED,
    ),
    "leaseCash": (
        "PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities",
        CONSOLIDATED,
    ),
    "interestReceived": (
        "InterestReceivedClassifiedAsOperatingActivities",
        CONSOLIDATED,
    ),
    "interestPaid": ("InterestPaidClassifiedAsOperatingActivities", CONSOLIDATED),
    "dividendsReceived": (
        "DividendsReceivedClassifiedAsOperatingActivities",
        CONSOLIDATED,
    ),
    "cashTaxes": ("IncomeTaxesPaidRefundClassifiedAsOperatingActivities", CONSOLIDATED),
    "depreciation": ("AdjustmentsForDepreciationExpense", INDIRECT),
    "amortization": ("AdjustmentsForAmortisationExpense", INDIRECT),
    "ppeDepreciation": ("DepreciationPropertyPlantAndEquipment", INDIRECT),
    "rouDepreciation": ("DepreciationRightofuseAssets", INDIRECT),
    "sbcAdjustment": ("AdjustmentsForShareBasedPayment", INDIRECT),
    "fairValueGain": (
        "AdjustmentsForGainsOnEvaluationOfFairValueFinancialAssets",
        INDIRECT,
    ),
    "minority": ("ProfitLossAttributableToNoncontrollingInterests", CONSOLIDATED),
}
TRADE = [
    ADJUSTMENTS[k][0]
    for k in [
        "매출채권의증가",
        "재고자산의감소(증가)",
        "기타자산의감소(증가)",
        "기타수취채권의감소",
        "매입채무의증가",
        "미지급금의증가(감소)",
        "기타지급채무의증가",
    ]
]
PASSAGES = [
    "2ad2490e2977332171ea",
    "298d981655f07061c87e",
    "48838c318fe869c9dc50",
    "aec141f5b29b3f1c221b",
    "f418ea55781e55d3cc9d",
    "322450b7978df1bd33f3",
    "6af2278329fd45a42bbd",
    "5f6e0869debaecf030df",
]


def cash_table(blob, net_income):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(blob, "html.parser")
    tables = []
    for tr in soup.find_all("tr"):
        cells = [
            "".join(x.get_text().split())
            for x in tr.find_all(["td", "th", "te", "tu"], recursive=False)
        ]
        if (
            len(cells) == 2
            and cells[0] in ("당기순이익", "반기순이익")
            and cells[1] == f"{int(net_income / 1e6):,}"
        ):
            table = tr.find_parent("table")
            if "영업으로부터 창출된 현금" in table.get_text(" "):
                tables.append(table)
    if len(tables) != 1:
        raise ValueError("Hynix original indirect cash table is ambiguous or missing")
    rows = []
    for tr in tables[0].find_all("tr"):
        cells = [
            "".join(x.get_text().split())
            for x in tr.find_all(["td", "th", "te", "tu"], recursive=False)
        ]
        if len(cells) != 2:
            continue
        label, number = cells
        if not label and number == "공시금액":
            continue
        if label.startswith("영업으로부터창출된현금"):
            continue
        if label not in ADJUSTMENTS:
            raise ValueError("Unreviewed Hynix cash adjustment: " + label)
        number = number.replace(",", "")
        amount = -int(number[1:-1]) if number.startswith("(") else int(number)
        rows.append(dict(label=label, value=amount * 1_000_000))
    return rows


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != ACCESSION or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="SK하이닉스 새 공시의 사업·현금·증권 변동을 다시 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if (
        source["sha256"] != CURRENT_XBRL
        or core["sourceHash"] != ANNUAL_XBRL
        or core["accession"] != "20260317000635"
    ):
        raise ValueError("Hynix source identity changed")
    annual_source = next(s for s in c["sources"] if s["file"] == core["sourceFile"])
    annual = instance_rows(
        read_verified(ROOT / annual_source["file"], ANNUAL_XBRL),
        c,
        annual_source,
        core["accession"],
        core["filedAt"],
    )
    manifest = json.loads(
        (
            DOCUMENT_ROOT / "data/sources/dart-document-20260317000635.manifest.json"
        ).read_text()
    )
    doc = next(d for d in manifest["files"] if d["sha256"] == ANNUAL_DOC)
    annual_blob = read_verified(DOCUMENT_ROOT / doc["file"], ANNUAL_DOC)
    annual_doc_source = dict(
        doc, provider="DART", url=manifest["url"], retrievedAt=manifest["retrievedAt"]
    )
    if doc["file"] not in {s["file"] for s in c["sources"]}:
        c["sources"].append(annual_doc_source)
    corpus = load(c)
    by_id = {p["id"]: p for p in corpus["passages"]}
    if any(p not in by_id for p in PASSAGES):
        raise ValueError("Hynix business passages changed")
    main = by_id[PASSAGES[0]]
    current_blob = read_verified(ROOT / main["sourceFile"], main["sourceHash"])
    f = c["financials"]
    periods = [
        (1, annual, core["start"], core["end"], annual_blob),
        (1, rows, f["start"], f["end"], current_blob),
        (-1, rows, f["priorStart"], f["priorEnd"], current_blob),
    ]

    def exact(rs, tag, dims, start, end):
        result = select(rs, tag, start, end, dims, "KRW")
        if result is None:
            raise ValueError("Hynix cash source missing: " + tag)
        return result

    def combine(tag, dims):
        parts = [
            dict(
                coefficient=k,
                fact=exact(
                    rs,
                    tag,
                    (
                        CONSOLIDATED
                        if tag == "DepreciationPropertyPlantAndEquipment"
                        and end == "2025-12-31"
                        else dims
                    ),
                    start,
                    end,
                ),
            )
            for k, rs, start, end, _ in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            derived=True,
            tag=tag,
            unit="KRW",
            sourceUrl=source["url"],
        )

    facts = {key: combine(*spec) for key, spec in TAGS.items()}
    v = lambda key: facts[key]["value"]
    adjustments, checks = {}, []
    for i, (k, rs, start, end, blob) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        table = cash_table(blob, val("netIncome"))
        for row in table:
            tag, sign = ADJUSTMENTS[row["label"]]
            if i == 0 and tag == PENSION:
                sign = 1
            fact = exact(rs, tag, INDIRECT, start, end)
            if sign * fact["value"] != row["value"]:
                raise ValueError(
                    "Hynix source-table amount/sign differs: " + row["label"]
                )
            label = {
                "ProfitLoss": "연결 순이익",
                "AdjustmentsForDecreaseIncreaseInInventories": "재고 변동",
                "AdjustmentsForIncreaseDecreaseInTradeAccountPayable": "매입채무 변동",
                "AdjustmentsForIncreasedecreaseInOtherPayables": "미지급금 변동",
            }.get(tag, row["label"])
            adjustments.setdefault(label, []).append(
                dict(coefficient=k * sign, fact=fact)
            )
        subtotal = sum(r["value"] for r in table)
        total = (
            subtotal
            + val("interestReceived")
            - val("interestPaid")
            + val("dividendsReceived")
            - val("cashTaxes")
        )
        if (
            subtotal != val("cashOperations")
            or total != val("cfo")
            or val("pretax") - val("tax") != val("netIncome")
        ):
            raise ValueError("Hynix period cash does not reconcile")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=val("cfo"),
                residual=0,
                indirectRows=len(table),
                indirectSubtotal=subtotal,
                depreciationNoteDifference=val("depreciation")
                - val("ppeDepreciation")
                - val("rouDepreciation"),
            )
        )
    parts = [
        dict(
            label=label,
            value=sum(p["coefficient"] * p["fact"]["value"] for p in components),
            fact=dict(sourceUrl=source["url"], components=components),
        )
        for label, components in adjustments.items()
    ]
    for key, label, sign in [
        ("interestReceived", "이자 수취", 1),
        ("interestPaid", "이자 지급", -1),
        ("dividendsReceived", "배당 수취", 1),
        ("cashTaxes", "법인세 납부", -1),
    ]:
        parts.append(
            dict(
                label=label,
                value=sign * v(key),
                fact=dict(
                    sourceUrl=source["url"],
                    components=[
                        dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                        for p in facts[key]["components"]
                    ],
                ),
            )
        )
    revenue = v("revenue")
    if revenue != c["trailingYear"]["values"]["revenue"]["value"] or sum(
        p["value"] for p in parts
    ) != v("cfo"):
        raise ValueError("Hynix trailing scope does not reconcile")
    trade = [combine(tag, INDIRECT) for tag in TRADE]
    working = sum(t["components"][1]["fact"]["value"] for t in trade)
    increase = (
        facts["revenue"]["components"][1]["fact"]["value"]
        - facts["revenue"]["components"][2]["fact"]["value"]
    )
    if increase <= 0 or any(
        p["fact"]["value"] < 0 for p in facts["leaseCash"]["components"]
    ):
        raise ValueError("Hynix growth/lease direction requires review")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=v("operatingIncome") / revenue)
        ],
        tax=0.275,
        netInterest=(v("interestReceived") - v("interestPaid")) / revenue,
        depreciation=(v("depreciation") + v("amortization")) / revenue,
        workingCapital=-working / increase,
        capexStart=(v("capex") + v("intangibles")) / revenue,
        capexEnd=(v("capex") + v("intangibles")) / revenue,
        leaseStart=v("leaseCash") / revenue,
        leaseEnd=v("leaseCash") / revenue,
        discount=0.12,
        terminal=0.02,
    )
    m = dict(
        status="research_workspace",
        version="hynix-operating-cash-path-v1",
        sourcePeriod=["2025-07-01", "2026-06-30"],
        accession=ACCESSION,
        corpusHash=CORPUS,
        basisLabel="최근 1년 공시 연결에서 출발",
        growthLabel="최근 반기 전년 대비",
        currency="KRW",
        displayScale=1e12,
        displayUnit="조 원",
        groupLabel="공시 단일 사업",
        netInterestLabel="이자 수취−지급 (배당 제외)",
        intro="단일 반도체 사업의 매출·마진과 설비·무형 투자, 리스 원금, 수금·재고·채무를 현금 경로로 연결합니다. 투자자산 평가이익과 배당 수취는 반복 사업 현금에서 분리합니다.",
        businessCaption="회사는 단일 영업부문으로 보고합니다. DRAM·NAND·HBM 판매 구성을 별도 공시 이익률로 만들지 않습니다. 최근 급증한 매출과 마진의 반복은 전망으로 승인하지 않습니다.",
        capexLabel="유형·무형 현금 취득",
        leaseLabel="리스 원금",
        bridgeLabel="공시 연결 순이익 → 영업현금 대사",
        observedResidualLabel="영업현금 − 유형·무형 취득 − 리스 원금 − 배당 유입 − 주식보상 현금조정",
        anchorSummary="영업자금 계수는 같은 반기 매출 증가와 매출채권·재고 등 7개 조정에서 계산합니다. 기타부채·충당금·퇴직 급여와 투자자산 평가이익을 매출 연동 자금으로 바꾸지 않습니다. 미래 세율 27.5%는 비교용 연구 가정이며 법정세율이나 회사 정상 세율의 추정치가 아닙니다.",
        passages=[by_id[i] for i in PASSAGES],
        segments=[
            dict(
                id="semiconductor",
                label="반도체 제조·판매 연결 단일 사업",
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
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=v("cfo")
            - v("capex")
            - v("intangibles")
            - v("leaseCash")
            - v("dividendsReceived")
            - v("sbcAdjustment"),
        ),
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=increase,
            tradeFacts=trade,
            minorityProfit=v("minority"),
            observedTaxRate=v("tax") / v("pretax"),
        ),
        cashAnchors=[
            dict(
                label=label,
                period="2026-01-01–2026-06-30",
                value=facts[key]["components"][1]["fact"]["value"],
                sourceUrl=source["url"],
                scope=scope,
            )
            for key, label, scope in [
                (
                    "fairValueGain",
                    "금융상품 평가이익",
                    "공시 순이익에서 영업현금으로 대사할 때 차감. 미래 영업이익에 가산하지 않음",
                ),
                (
                    "dividendsReceived",
                    "배당 현금 수취",
                    "한국 공시 영업현금에 포함. 미래 사업현금에서 제외; 투자자산 자체 가치 미배분",
                ),
                (
                    "depreciation",
                    "현금표 감가상각 조정",
                    "유형·사용권 포함. 유형자산 및 사용권 주석 합계와 기간별 차이를 별도 보존",
                ),
                (
                    "leaseCash",
                    "재무현금 리스 원금",
                    "리스 주석의 다른 지급액과 혼합하지 않음",
                ),
            ]
        ]
        + [
            dict(
                label="미기표 유형자산 구매 약정",
                period="2026-06-30",
                value=61_484_533_000_000,
                sourceUrl=by_id["48838c318fe869c9dc50"]["sourceUrl"],
                scope="향후 지급시점 미확정인 계약액. 이번 반기 현금 지출이나 한 해 투자계획으로 차감하지 않음",
            )
        ],
        rules=[
            "연간+현재 반기−전년 반기로 최근 1년을 계산하고 각 기간의 원문 현금표를 따로 대사합니다. 전기 연간 사외적립자산 태그와 당·전 반기 태그의 부호 차이를 원문 금액으로 확인합니다.",
            "순이익에는 금융상품 평가·파생·배당·환산 손익이 섞입니다. 미래는 영업이익에서 출발하며 평가이익을 보고 영업현금에서 다시 차감하지 않습니다. 투자자산의 처분 가치·추가 배당 가치는 포함하지 않습니다.",
            "과거 현금표 주식보상 조정을 관측 잔액에서 차감합니다. 미래 영업이익에 이미 반영된 주식보상비는 되돌리지 않으며, 현금조정액과 당기 손익의 보상비 전액이 같다고 보지 않습니다.",
            "미래 감가·무형 상각은 현금표 비율을 유지합니다. 사용권 상각을 포함하고 리스 원금을 별도 차감하며 이자는 순수취 현금 비율에 포함합니다. 현금표와 유형·사용권 주석 합계의 차이는 연간 12백만원·당기 반기 6백만원·전년 반기 5백만원이며 영으로 맞추지 않습니다.",
            "27.5% 세율은 조정 가능한 연구 시나리오입니다. 평가이익이 큰 보고 세전이익의 유효세율을 정상 영업 세율로 옮기지 않으며 손실의 즉시 환급을 가정하지 않습니다.",
            "미기표 설비 구매 약정은 실제 취득 현금과 다릅니다. 지원금·자산매각·사업결합 현금을 설비 취득액에 조용히 상계하지 않습니다.",
            "비지배 지분의 현금 배분·비리스 순차입·금융자산 가치는 별도 미배분 상태입니다. 미래 비지배 현금 유출 영과 차환 유지의 조건부 사업 경로이며 보통주 가치 확정이 아닙니다.",
            "반기 말 이후 신주·자기주식 변동은 별도 증권 검토로 연결합니다. 미국 ADR과 한국 원주를 동시에 더하지 않습니다.",
            "성장 0%·현재 마진 유지·요구수익률 12%·영구성장 2%는 초기 비교 가정입니다. 메모리 가격·물량·원가에 대한 확인된 정상 전망이 아니며 마진 하락과 높은 투자 부담을 함께 비교해야 합니다.",
        ],
        remaining=[
            "HBM·DRAM·NAND의 물량·판매가격·원가와 사이클 하락 마진",
            "설비 구매 약정의 연도별 지급·정부지원·대체투자",
            "수금·재고·공급자금융의 성장 민감도",
            "투자자산·비지배 현금 배분 및 반기 이후 발행·자기주식 대사",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
