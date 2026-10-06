"""Celltrion candidate: internal profit, cash classification and financing."""

import io
import json
import zipfile
from lxml import etree
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "20260814003751"
CORPUS = "0f031aab19f9782895da03f3bd628b3a0f580775aaa9d1534c56e46e7391fe9e"
CURRENT_SHA = "d75988763cb8b436050be3ebf6d8555b61a84df345a8e14442028530ca3876d9"
ANNUAL_SHA = "918103648a799e622c30391295aefaec3e2c6ed6301f26de8e117535834fb3af"
ANNUAL_DOC = "f459a72e3a161026d5baae2de34a6fce47360ad6a88c8d3fb50ccd9aec0af7a0"
CON = [("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")]
IND = CON + [
    (
        "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis",
        "ReportedAmountMember",
    )
]
TAGS = dict(
    revenue=("Revenue", CON),
    operatingIncome=("OperatingIncomeLoss", CON),
    netIncome=("ProfitLoss", CON),
    cfo=("CashFlowsFromUsedInOperatingActivities", CON),
    adjustments=("AdjustmentsForReconcileProfitLoss", IND),
    working=("IncreaseDecreaseInWorkingCapital", IND),
    taxCash=("IncomeTaxesPaidRefundClassifiedAsOperatingActivities", CON),
    interestPaid=("InterestPaidClassifiedAsFinancingActivities", CON),
    interestReceived=("InterestReceivedClassifiedAsInvestingActivities", CON),
    dividends=("DividendsReceivedClassifiedAsInvestingActivities", CON),
    interestIncome=("AdjustmentsForInterestIncome", IND),
    interestExpense=("AdjustmentsForInterestExpenses", IND),
    depreciation=("AdjustmentsForDepreciationExpense", IND),
    amortization=("AdjustmentsForAmortisationExpense", IND),
    investmentDepreciation=("AdjustmentsForDepreciationInvestmentProperty", IND),
    ppe=("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", CON),
    intangible=("PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities", CON),
    lease=("PaymentsOfFinanceLeaseLiabilitiesClassifiedAsFinancingActivities", CON),
    minority=("ProfitLossAttributableToNoncontrollingInterests", CON),
    sbc=("AdjustmentsForShareBasedPayment", IND),
    capitalizedInterest=("InterestCostsCapitalised", IND),
)
PASSAGES = [
    "46bae7b73fe5c23ad6cb",
    "e5435f2147aa268ba5b4",
    "f002ca7d6787dde68bc5",
    "95f9bb261046707ab27b",
    "eba1ad8289d02c39f71c",
    "933863fd39457c9988d0",
    "5858292d731ae8bd2a57",
    "1aa2670ff7657af0d3e6",
    "e2b900a7e40de55c914c",
]
PACKAGES = [
    (
        "20260316001415",
        "26872ba9560cc32093cd5030931226e0752f14fa5da1702a6ecb8212a3cbc1fd",
        "entity00413046_2025-12-31_pre.xml",
        "67bf2d38e1f89213db2d5d47ca8a76a46565506d96c591ea685ee399d786ae29",
        "http://www.xbrl.org/2003/role/totalLabel",
        1,
    ),
    (
        CURRENT,
        "f125dbba7abe50e4278cf165113abf822fa4a6c6a67f0e9f601a2910276eab39",
        "entity00413046_2026-06-30_pre.xml",
        "1f9535d6c74a0d047f18a7c267bfb508afe01be292e5ad2169431f4b48b1c93f",
        "http://www.xbrl.org/2009/role/negatedTotalLabel",
        -1,
    ),
]


def presentation_signs(c):
    verified = []
    ns = {"l": "http://www.xbrl.org/2003/linkbase", "x": "http://www.w3.org/1999/xlink"}
    for receipt, sha, member, member_hash, label, sign in PACKAGES:
        file = f"data/sources/dart-package-{receipt}-{sha[:16]}.zip"
        with zipfile.ZipFile(io.BytesIO(read_verified(ROOT / file, sha))) as z:
            body = z.read(member)
        if digest(body) != member_hash:
            raise ValueError("Celltrion presentation member changed")
        root = etree.fromstring(body)
        labels = []
        for link in root.findall("l:presentationLink", ns):
            if (
                link.get("{" + ns["x"] + "}role")
                != "http://dart.fss.or.kr/role/ifrs/ias_7_role-D851100"
            ):
                continue
            loc = {
                x.get("{" + ns["x"] + "}label"): x.get("{" + ns["x"] + "}href").split(
                    "#"
                )[-1]
                for x in link.findall("l:loc", ns)
            }
            for arc in link.findall("l:presentationArc", ns):
                if (
                    loc.get(arc.get("{" + ns["x"] + "}to"))
                    == "ifrs-full_IncreaseDecreaseInWorkingCapital"
                ):
                    labels.append(arc.get("preferredLabel"))
        if labels != [label]:
            raise ValueError(
                "Celltrion working-capital presentation sign requires review"
            )
        src = dict(
            file=file,
            sha256=sha,
            provider="DART",
            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
            retrievedAt=None,
            mode="보존 XBRL 패키지·수집 시각 미기록",
        )
        if file not in {x["file"] for x in c["sources"]}:
            c["sources"].append(src)
        verified.append(
            dict(
                source=src,
                member=member,
                memberHash=member_hash,
                preferredLabel=label,
                cashEffectSign=sign,
            )
        )
    return verified


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="셀트리온의 부문 내부거래·개발비·공급자금융과 현금 범위를 새 공시에서 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if source["sha256"] != CURRENT_SHA or core["sourceHash"] != ANNUAL_SHA:
        raise ValueError("Celltrion financial source changed")
    annual_source = next(x for x in c["sources"] if x["file"] == core["sourceFile"])
    annual = instance_rows(
        read_verified(ROOT / core["sourceFile"], ANNUAL_SHA),
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

    def exact(rs, tag, start, end, dims):
        fact = select(rs, tag, start, end, dims, "KRW")
        if fact is None:
            raise ValueError(
                "Celltrion missing fact: " + tag + " " + str(start) + " " + end
            )
        return fact

    def combined(tag, dims):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, start, end, dims))
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            unit="KRW",
            sourceUrl=source["url"],
        )

    facts = {k: combined(tag, dims) for k, (tag, dims) in TAGS.items()}
    v = lambda k: facts[k]["value"]
    signs = presentation_signs(c)
    for i, p in enumerate(facts["working"]["components"]):
        p["coefficient"] *= signs[0 if i == 0 else 1]["cashEffectSign"]
    facts["working"]["value"] = sum(
        p["coefficient"] * p["fact"]["value"] for p in facts["working"]["components"]
    )
    history = c["segmentHistory"]
    # This candidate retains the global segment-history residual status. It
    # separately tests this source's explicit thousand-won precision.
    segment_rows = []
    for s in history["segments"]:
        rev = s["revenue"]
        profit = s["operatingIncome"]
        for series in [rev, profit]:
            for i, part in enumerate(series["components"]):
                fact = part["fact"]
                actual = exact(
                    periods[i][1],
                    fact["tag"],
                    fact["start"],
                    fact["end"],
                    [tuple(d) for d in fact["dimensions"]],
                )
                if (
                    actual["value"] != fact["value"]
                    or actual["sourceHash"] != fact["sourceHash"]
                ):
                    raise ValueError("Celltrion segment value differs from original")
            if series["value"] != sum(
                p["coefficient"] * p["fact"]["value"] for p in series["components"]
            ):
                raise ValueError("Celltrion segment period sum differs")
        segment_rows.append(
            dict(
                id=s["id"],
                label=s["label"],
                revenue=rev["value"],
                margin=profit["value"] / rev["value"],
                observedGrowth=rev["components"][1]["fact"]["value"]
                / rev["components"][2]["fact"]["value"]
                - 1,
                evidence=[
                    dict(rev, sourceUrl=source["url"]),
                    dict(profit, sourceUrl=source["url"]),
                ],
            )
        )
    recon = history["reconciliations"]
    checks = []
    cash_keys = [
        ("netIncome", "연결 순이익", 1),
        ("adjustments", "현금표 손익·비현금 조정", 1),
        ("working", "표시 부호를 확인한 영업자산·부채", 1),
        ("taxCash", "현금 법인세", -1),
    ]
    for i, (_, rs, start, end) in enumerate(periods):
        val = lambda k: facts[k]["components"][i]["fact"]["value"]
        working_sign = signs[0 if i == 0 else 1]["cashEffectSign"]
        reconstructed = (
            val("netIncome")
            + val("adjustments")
            + working_sign * val("working")
            - val("taxCash")
        )
        bound = sum(
            0.5 * 10 ** (-int(facts[k]["components"][i]["fact"]["decimals"]))
            for k, _, _ in cash_keys
        )
        residual = val("cfo") - reconstructed
        if abs(residual) > bound:
            raise ValueError("Celltrion cash bridge exceeds stated fact precision")
        rp, op = recon["revenue"]["periods"][i], recon["operatingIncome"]["periods"][i]
        if (
            sum(
                s["evidence"][0]["components"][i]["fact"]["value"] for s in segment_rows
            )
            != rp["subtotal"]
            or sum(
                s["evidence"][1]["components"][i]["fact"]["value"] for s in segment_rows
            )
            != op["subtotal"]
        ):
            raise ValueError("Celltrion segment subtotals differ from reconciliation")
        if abs(rp["residual"]) > 2500 or abs(op["residual"]) > 2500:
            raise ValueError("Celltrion segment reconciliation exceeds table precision")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=val("cfo"),
                reconstructedCfo=reconstructed,
                residual=residual,
                roundingBound=bound,
                workingRaw=val("working"),
                workingCashEffect=working_sign * val("working"),
                segmentRevenue=rp["subtotal"],
                internalRevenue=-rp["adjustment"],
                consolidatedRevenue=rp["total"],
                unallocatedOperatingIncome=op["adjustment"],
                revenueResidual=rp["residual"],
                incomeResidual=op["residual"],
            )
        )
    trade = [
        exact(rows, t, f["start"], f["end"], IND)
        for t in [
            "AdjustmentsForDecreaseIncreaseInTradeAccountReceivable",
            "AdjustmentsForDecreaseIncreaseInInventories",
        ]
    ]
    payable = exact(
        rows,
        "AdjustmentsForIncreaseDecreaseInTradeAccountPayable",
        f["start"],
        f["end"],
        IND,
    )
    increase = (
        facts["revenue"]["components"][1]["fact"]["value"]
        - facts["revenue"]["components"][2]["fact"]["value"]
    )
    if increase <= 0:
        raise ValueError("Celltrion growth anchor requires review")
    working = sum(x["value"] for x in trade)
    rev = v("revenue")
    gross = sum(s["revenue"] for s in segment_rows)
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"])
            for s in segment_rows
        ],
        eliminationStart=-recon["revenue"]["adjustment"] / gross,
        eliminationEnd=-recon["revenue"]["adjustment"] / gross,
        otherProfitStart=0,
        otherProfitEnd=0,
        minority=max(0, v("minority")) / rev,
        tax=0.275,
        netInterest=(v("interestIncome") - v("interestExpense")) / rev,
        depreciation=(
            v("depreciation") + v("amortization") + v("investmentDepreciation")
        )
        / rev,
        workingCapital=-working / increase,
        capexStart=(v("ppe") + v("intangible")) / rev,
        capexEnd=(v("ppe") + v("intangible")) / rev,
        leaseStart=v("lease") / rev,
        leaseEnd=v("lease") / rev,
        discount=0.12,
        terminal=0.02,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("Celltrion passages missing")
    manifest = json.loads(
        (
            DOCUMENT_ROOT / "data/sources/dart-document-20260316001415.manifest.json"
        ).read_text()
    )
    doc = next(x for x in manifest["files"] if x["sha256"] == ANNUAL_DOC)
    annual_text = extract(read_verified(DOCUMENT_ROOT / doc["file"], ANNUAL_DOC))
    annual_ids = {
        "8628e34a86630b6df4c0",
        "25f714d17a0898d77b85",
        "86b2d9d6ae31c62f3fa6",
        "d01c7143d02d059e2556",
    }
    selected = [x for x in annual_text if x["id"] in annual_ids]
    if len(selected) != len(annual_ids):
        raise ValueError("Celltrion annual passages changed")
    item = dict(
        doc, provider="DART", url=manifest["url"], retrievedAt=manifest["retrievedAt"]
    )
    if item["file"] not in {x["file"] for x in c["sources"]}:
        c["sources"].append(item)
    cf_parts = [
        dict(
            label=l,
            value=k * v(key),
            fact=dict(
                sourceUrl=source["url"],
                components=[
                    dict(coefficient=k * x["coefficient"], fact=x["fact"])
                    for x in facts[key]["components"]
                ],
            ),
        )
        for key, l, k in cash_keys
    ]
    development_dims = CON + [
        (
            "ClassesOfIntangibleAssetsAndGoodwillAxis",
            "CapitalisedDevelopmentExpenditureMember",
        )
    ]
    development = {
        k: exact(rows, tag, start, end, development_dims)
        for k, tag, start, end in [
            ("opening", "IntangibleAssetsAndGoodwill", None, "2025-12-31"),
            ("closing", "IntangibleAssetsAndGoodwill", None, "2026-06-30"),
            (
                "added",
                "AdditionsOtherThanThroughBusinessCombinationsIntangibleAssetsOtherThanGoodwill",
                f["start"],
                f["end"],
            ),
            (
                "amortized",
                "AmortisationIntangibleAssetsOtherThanGoodwill",
                f["start"],
                f["end"],
            ),
        ]
    }
    development["residual"] = (
        development["closing"]["value"]
        - development["opening"]["value"]
        - development["added"]["value"]
        + development["amortized"]["value"]
    )
    if development["residual"] != 0:
        raise ValueError("Celltrion capitalized-development rollforward changed")
    development["stageGross"] = [
        dict(label=label, value=value, passage=index[pid])
        for label, value, pid in [
            ("임상 1상·생동시험", 369663179000, "f3d5b85910deff5d2a3d"),
            ("임상 3상", 1086164518000, "0b2f6f6312b19a8f66b5"),
            ("판매승인", 221451553000, "5db47cd77c598600ebb8"),
        ]
    ]
    development["grossBeforeImpairment"] = sum(
        x["value"] for x in development["stageGross"]
    )
    development["accumulatedImpairment"] = 51846600000
    development["impairmentPassage"] = index["711850de94e229711d0e"]
    if (
        development["grossBeforeImpairment"] - development["accumulatedImpairment"]
        != development["closing"]["value"]
    ):
        raise ValueError("Celltrion development stage scope differs")
    supplier_dims = CON + [
        (
            "LiabilitiesArisingFromFinancingActivitiesAxis",
            "FinancialLiabilitiesThatArePartOfSupplierFinanceArrangementsMember",
        )
    ]
    supplier = {
        k: exact(rows, tag, start, end, supplier_dims)
        for k, tag, start, end in [
            (
                "opening",
                "LiabilitiesArisingFromFinancingActivities",
                None,
                "2025-12-31",
            ),
            (
                "closing",
                "LiabilitiesArisingFromFinancingActivities",
                None,
                "2026-06-30",
            ),
            (
                "netFinancingCash",
                "IncreaseDecreaseThroughFinancingCashFlowsLiabilitiesArisingFromFinancingActivities",
                f["start"],
                f["end"],
            ),
            (
                "fx",
                "IncreaseDecreaseThroughEffectOfChangesInForeignExchangeRatesLiabilitiesArisingFromFinancingActivities",
                f["start"],
                f["end"],
            ),
        ]
    }
    supplier["residual"] = (
        supplier["closing"]["value"]
        - supplier["opening"]["value"]
        - supplier["netFinancingCash"]["value"]
        - supplier["fx"]["value"]
    )
    if supplier["residual"] != 0:
        raise ValueError("Celltrion supplier financing does not reconcile")
    supplier.update(
        disclosedOtherPayableTransfer=14176000000,
        ordinaryDays=60,
        financedDays=180,
        passage=index["eba1ad8289d02c39f71c"],
    )
    classification = [
        dict(
            start=start,
            end=end,
            cfo=facts["cfo"]["components"][i]["fact"]["value"],
            interestPaid=facts["interestPaid"]["components"][i]["fact"]["value"],
            interestReceived=facts["interestReceived"]["components"][i]["fact"][
                "value"
            ],
            dividends=facts["dividends"]["components"][i]["fact"]["value"],
            capitalizedInterest=facts["capitalizedInterest"]["components"][i]["fact"][
                "value"
            ],
        )
        for i, (_, rs, start, end) in enumerate(periods)
    ]
    for x in classification:
        x["cfoAfterCashInterest"] = x["cfo"] - x["interestPaid"] + x["interestReceived"]
    m = dict(
        status="research_workspace",
        version="celltrion-cash-classification-v1",
        sourcePeriod=[history["start"], history["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="KRW",
        displayScale=1e12,
        displayUnit="조 원",
        basisLabel="세 기간 공시 현금·내부거래와 반올림 대사",
        groupLabel="내부거래 전 공시 부문",
        growthLabel="같은 상반기 대비",
        segments=segment_rows,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        consolidationPath=True,
        pharmaEvidence=dict(
            development=development,
            supplierFinancing=supplier,
            cashClassification=classification,
        ),
        consolidation=dict(
            periods=checks,
            segmentRevenue=gross,
            internalRevenue=-recon["revenue"]["adjustment"],
            reportedRevenue=rev,
            unallocatedOperatingIncome=recon["operatingIncome"]["adjustment"],
            adjustmentLabel="공시 내부거래 이익 조정",
            scope="세 부문은 법인 단순합산으로 내부거래 조정 전입니다. 내부이익 조정의 최근1년 양수를 정상 수익으로 확정하지 않습니다. 원 단위 연결값과 천 원 주석의 잔차를 보존합니다.",
            profitScope="부문 이익은 내부거래 조정 전입니다. 기타 이익 가정에서 내부 이익의 제거·실현을 한 번만 반영합니다. 초기0은 미래에 조정이 영이라는 연구 가정이며 실제 공시 금액이 아닙니다.",
        ),
        intro="바이오·케미컬·기타 법인 매출의 내부거래를 제거하고, 부문 이익과 내부이익 조정을 구분합니다. 합산 부문 매출을 제품별 외부 판매로 바꾸지 않으며 개별 신약의 성공 확률이나 가치를 만들어 넣지 않습니다.",
        businessCaption="세 기간은 공시 부문 범위로 연결했습니다. 내부거래 이익 조정의 변화를 모두 합병 재고 해소로 단정하지 않고 제품 믹스·외부 판매와 추가 대사합니다.",
        anchorSummary="반기 매출채권·재고 현금 효과만 같은 반기 매출 증가로 나눈 좁은 자금 대용입니다. 공급자금융과 매입·기타채무를 함께 정상화했다고 표시하지 않습니다. 세율27.5%·순이자·투자 강도는 미래 연구 가정입니다.",
        bridgeLabel="순이익 → 현금표 조정·운전자본·세금 대사 (이자 별도 분류)",
        bridge=dict(
            parts=cf_parts,
            reportedCfo=v("cfo"),
            residual=v("cfo") - sum(x["value"] for x in cf_parts),
            periods=checks,
            cashAfterInvestmentLeaseSbc=v("cfo")
            - v("ppe")
            - v("intangible")
            - v("lease")
            - v("interestPaid")
            + v("interestReceived")
            - v("sbc"),
        ),
        observedResidualLabel="영업현금−유형·무형 취득−리스−재무활동 이자+투자활동 이자−주식보상 비용 대용 (배당 제외)",
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=increase,
            tradeFacts=trade,
            excludedPayableCash=payable,
            presentationSigns=signs,
            capitalizedInterest=facts["capitalizedInterest"],
            internalProfitAssumption=0,
        ),
        cashAnchors=[
            dict(
                label=l,
                period="최근1년",
                value=v(k),
                sourceUrl=source["url"],
                scope=scope,
            )
            for k, l, scope in [
                (
                    "interestPaid",
                    "재무활동 현금 이자 지급",
                    "영업현금에 포함되지 않음; 부채 원금·리스와 구별",
                ),
                (
                    "interestReceived",
                    "투자활동 현금 이자 수취",
                    "영업현금에 포함되지 않음",
                ),
                (
                    "capitalizedInterest",
                    "자산 원가에 포함한 발생 이자",
                    "현금 지급액 아님; 취득 현금에 자동 중복 가산하지 않음",
                ),
                (
                    "sbc",
                    "현금표 주식보상 조정",
                    "미래 마진에 비용을 남기고 별도로 되돌리지 않음",
                ),
                (
                    "lease",
                    "리스 원금 지급",
                    "이미 포함된 사용권 상각을 다시 더하지 않음",
                ),
            ]
        ],
        passages=[index[p] for p in PASSAGES],
        historicalPassages=[
            dict(p, sourceUrl=manifest["url"], sourceHash=ANNUAL_DOC) for p in selected
        ],
        rules=[
            "연간 운전자본의 음수 원금액과 반기 양수 표시의 부호는 연결 XBRL presentation 원문에서 별도로 확인했습니다. 같은 태그에 같은 부호를 강제하지 않습니다.",
            "순이익+비현금 조정+운전자본−세금과 공시 영업현금의 원 단위 잔차를 보존합니다. 반올림 범위 일치는 해석 승인과 다릅니다.",
            "부문 합산 매출은 내부거래 전입니다. 내부매출 제거율과 내부 이익 조정은 서로 다른 입력이며 이익 조정의 초기0은 연구 가정입니다.",
            "주식보상은 보고 이익에 비용으로 남기며 미래 현금에 되돌리지 않습니다. 상각은 현금표 비용 조정만 사용하고 사용권 자산을 중복 가산하지 않습니다.",
            "임상 단계의 개발비 장부액은 신약 성공 확률이나 미래 매출이 아닙니다. 개발비 자산화·상각과 현금 취득을 구분합니다.",
            "이자 지급은 재무활동, 이자·배당 수취는 투자활동입니다. 과거 잔여 현금에서 이자를 별도 연결하고 미래에는 현금표에서 되돌린 순이자 비용의 발생 대용을 씁니다.",
            "공급자금융의 은행 지급은 공시상 영업유출·재무유입, 은행 후속 상환은 재무유출입니다. 지급기한60→180일 연장을 수금 개선으로 해석하지 않습니다.",
            "신규 순차입0을 가정한 사업 현금이며 실제 부채 만기·리파이낸싱·자본화 이자 지급의 정상화는 별도입니다. 현금·금융자산과 지분 가치를 자동 가산하지 않습니다.",
        ],
        remaining=[
            "제품별 외부 판매·리베이트·가격정산과 매출채권 현금화",
            "내부 재고 이익 조정의 귀속·반복성",
            "개발비 자산화·상각·임상 투자와 시설투자의 유지·성장 구분",
            "공급자금융·선급이자·부채 만기 및 투자자산·비지배 배분",
        ],
        financialApproval=False,
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
