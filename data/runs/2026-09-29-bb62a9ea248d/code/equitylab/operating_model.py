"""Business-led cash paths; source reconciliation and assumptions stay separate."""

import math
from .data import canonical, digest
from .xbrl import company_filing, select

VERSION = "operating-cash-path-v1"
WC = [
    ("IncreaseDecreaseInAccountsReceivable", "매출채권", -1),
    ("IncreaseDecreaseInInventories", "재고", -1),
    ("IncreaseDecreaseInOtherCurrentAssets", "기타 유동자산", -1),
    ("IncreaseDecreaseInOtherNoncurrentAssets", "기타 장기자산", -1),
    ("IncreaseDecreaseInAccountsPayable", "매입채무", 1),
    ("IncreaseDecreaseInContractWithCustomerLiability", "선수 수익", 1),
    ("IncreaseDecreaseInOtherCurrentLiabilities", "기타 유동부채", 1),
    ("IncreaseDecreaseInOtherNoncurrentLiabilities", "기타 장기부채", 1),
]
PASSAGES = [
    "0e5d63a88713aac8972d",
    "cfdf64ea8d027762fa47",
    "9ae8d6492b78b4a08baf",
    "eafe5acecd863c607bd2",
    "377e41dda8a198a0528f",
    "d862615d5702a90d5218",
]


def calculate(model, assumptions):
    """Five explicit years plus a separately recalculated terminal cash year."""
    a = assumptions
    income_key = "pretaxIncome" if model.get("pretaxPath") else "operatingIncome"
    if model.get("pretaxPath") and (
        a.get("netInterest") != 0
        or any(
            model.get(k)
            for k in ("grossProfitPath", "consolidationPath", "normalizationPath")
        )
    ):
        raise ValueError(
            "Pretax paths already include interest and cannot mix profit bases"
        )
    required = {
        "segments",
        "tax",
        "netInterest",
        "depreciation",
        "workingCapital",
        "capexStart",
        "capexEnd",
        "leaseStart",
        "leaseEnd",
        "discount",
        "terminal",
    }
    if model.get("consolidationPath"):
        required |= {
            "eliminationStart",
            "eliminationEnd",
            "otherProfitStart",
            "otherProfitEnd",
            "minority",
        }
    if model.get("reservePath"):
        required |= {"warrantyAccrual", "warrantyUseStart", "warrantyUseEnd"}
    if model.get("grossProfitPath"):
        required |= {
            "researchStart",
            "researchEnd",
            "sellingStart",
            "sellingEnd",
            "otherOperatingStart",
            "otherOperatingEnd",
            "minority",
        }
    if model.get("normalizationPath"):
        required |= {"excludedProfitStart", "excludedProfitEnd"}
    if model.get("unallocatedPath"):
        required |= {"corporateStart", "corporateEnd"}
    if model.get("minorityPath"):
        required.add("minority")
    if model.get("equityInvestmentPath"):
        required.add("equityInvestmentValue")
    if set(a) != required or len(a["segments"]) != len(model["segments"]):
        raise ValueError("Operating path requires every explicit assumption")
    for key in required - {"segments", "equityInvestmentValue"}:
        if type(a[key]) not in (float, int) or not math.isfinite(a[key]):
            raise ValueError("Non-finite operating assumption")
    if model.get("equityInvestmentPath"):
        asset = a["equityInvestmentValue"]
        if asset is not None and (
            type(asset) not in (float, int) or not math.isfinite(asset) or asset < 0
        ):
            raise ValueError(
                "Investment value must be unassessed or a nonnegative assumption"
            )
    if not 0 <= a["tax"] <= 0.6 or not 0 <= a["terminal"] < a["discount"] <= 0.3:
        raise ValueError("Invalid tax or terminal discount assumptions")
    if any(
        not 0 <= a[k] <= 1
        for k in ("depreciation", "capexStart", "capexEnd", "leaseStart", "leaseEnd")
    ):
        raise ValueError("Invalid asset or lease intensity")
    if not -0.5 <= a["workingCapital"] <= 1 or not -0.2 <= a["netInterest"] <= 0.2:
        raise ValueError("Invalid working-capital or net interest assumption")
    if model.get("minorityPath") and not 0 <= a["minority"] <= 1:
        raise ValueError("Invalid minority outflow")
    if model.get("reservePath") and any(
        not 0 <= a[k] <= 0.2
        for k in ("warrantyAccrual", "warrantyUseStart", "warrantyUseEnd")
    ):
        raise ValueError("Invalid warranty cash assumption")
    if model.get("normalizationPath") and any(
        not 0 <= a[k] <= 0.5 for k in ("excludedProfitStart", "excludedProfitEnd")
    ):
        raise ValueError("Invalid excluded operating profit assumption")
    if model.get("grossProfitPath") and any(
        not 0 <= a[k] <= 1
        for k in required
        if k.startswith(("research", "selling", "otherOperating")) or k == "minority"
    ):
        raise ValueError("Invalid unallocated operating cost or minority outflow")
    if model.get("unallocatedPath") and any(
        not 0 <= a[k] <= 1 for k in ("corporateStart", "corporateEnd")
    ):
        raise ValueError("Invalid corporate net cost assumption")
    if model.get("consolidationPath"):
        if (
            any(not 0 <= a[k] < 1 for k in ("eliminationStart", "eliminationEnd"))
            or any(
                not -0.1 <= a[k] <= 0.1 for k in ("otherProfitStart", "otherProfitEnd")
            )
            or not 0 <= a["minority"] <= 1
        ):
            raise ValueError("Invalid consolidation elimination or minority assumption")
    for base, item in zip(model["segments"], a["segments"]):
        if set(item) != {"growthStart", "growthEnd", "marginEnd"} or any(
            type(v) not in (float, int) or not math.isfinite(v) for v in item.values()
        ):
            raise ValueError("Invalid segment assumptions")
        if not all(
            base.get("minGrowth", -0.5) <= item[k] <= 0.8
            for k in ("growthStart", "growthEnd")
        ) or not base.get("minMargin", -0.5) <= item["marginEnd"] <= (
            1 if model.get("grossProfitPath") else 0.9
        ):
            raise ValueError("Segment assumptions outside supported range")
    previous = [s["revenue"] for s in model["segments"]]
    previous_net = (
        model["consolidation"]["reportedRevenue"]
        if model.get("consolidationPath")
        else sum(previous)
    )
    years = []
    for year in range(1, 7):
        t = min((year - 1) / 4, 1)
        segments = []
        for base, v, old in zip(model["segments"], a["segments"], previous):
            growth = (
                a["terminal"]
                if year == 6
                else v["growthStart"] + (v["growthEnd"] - v["growthStart"]) * t
            )
            margin = base["margin"] + (v["marginEnd"] - base["margin"]) * min(
                year / 5, 1
            )
            revenue = old * (1 + growth)
            segments.append(
                dict(
                    label=base["label"],
                    revenue=revenue,
                    **{
                        (
                            "grossProfit"
                            if model.get("grossProfitPath")
                            else income_key
                        ): revenue
                        * margin
                    },
                )
            )
        revenue = sum(s["revenue"] for s in segments)
        consolidated = {}
        if model.get("consolidationPath"):
            internal = revenue * (
                a["eliminationStart"]
                + (a["eliminationEnd"] - a["eliminationStart"]) * t
            )
            consolidated = dict(segmentRevenue=revenue, internalRevenue=internal)
            revenue -= internal
            consolidated["otherOperatingProfit"] = revenue * (
                a["otherProfitStart"]
                + (a["otherProfitEnd"] - a["otherProfitStart"]) * t
            )
            consolidated["minority"] = revenue * a["minority"]
        gross_path = {}
        if model.get("grossProfitPath"):
            gross = sum(s["grossProfit"] for s in segments)
            costs = {
                k: revenue * (a[k + "Start"] + (a[k + "End"] - a[k + "Start"]) * t)
                for k in ("research", "selling", "otherOperating")
            }
            op = gross - sum(costs.values())
            gross_path = dict(
                grossProfit=gross, **costs, minority=revenue * a["minority"]
            )
        else:
            op = sum(s[income_key] for s in segments)
        op += consolidated.get("otherOperatingProfit", 0)
        unallocated = {}
        if model.get("unallocatedPath"):
            corporate = revenue * (
                a["corporateStart"] + (a["corporateEnd"] - a["corporateStart"]) * t
            )
            unallocated = {
                (
                    "segmentPretaxIncome"
                    if model.get("pretaxPath")
                    else "segmentOperatingIncome"
                ): op,
                "corporateCost": corporate,
            }
            op -= corporate
        normalization = {}
        if model.get("normalizationPath"):
            excluded = revenue * (
                a["excludedProfitStart"]
                + (a["excludedProfitEnd"] - a["excludedProfitStart"]) * t
            )
            normalization = dict(unadjustedOperatingIncome=op, excludedProfit=excluded)
            op -= excluded
        net_interest = revenue * a["netInterest"]
        # No immediate cash tax credit is assumed for a loss.
        tax = max(0, op + net_interest) * a["tax"]
        depreciation = revenue * a["depreciation"]
        working = (
            revenue
            - (previous_net if model.get("consolidationPath") else sum(previous))
        ) * a["workingCapital"]
        capex = revenue * (a["capexStart"] + (a["capexEnd"] - a["capexStart"]) * t)
        lease = revenue * (a["leaseStart"] + (a["leaseEnd"] - a["leaseStart"]) * t)
        cash = (
            op
            + net_interest
            - tax
            + depreciation
            - working
            - capex
            - lease
            - revenue * a.get("minority", 0)
        )
        warranty = {}
        if model.get("reservePath"):
            accrual = revenue * a["warrantyAccrual"]
            used = revenue * (
                a["warrantyUseStart"]
                + (a["warrantyUseEnd"] - a["warrantyUseStart"]) * t
            )
            cash += accrual - used
            warranty = dict(warrantyAccrual=accrual, warrantyUse=used)
        years.append(
            dict(
                year=year,
                segments=segments,
                revenue=revenue,
                **{income_key: op},
                netInterest=net_interest,
                tax=tax,
                depreciation=depreciation,
                workingCapital=working,
                capex=capex,
                leasePrincipal=lease,
                cash=cash,
                **warranty,
                **gross_path,
                **normalization,
                **unallocated,
                **consolidated,
                **(
                    {"minority": revenue * a["minority"]}
                    if model.get("minorityPath")
                    else {}
                ),
            )
        )
        previous_net = revenue
        previous = [s["revenue"] for s in segments]
    terminal = years.pop()
    pv = sum(r["cash"] / (1 + a["discount"]) ** r["year"] for r in years)
    tv = (
        terminal["cash"] / (a["discount"] - a["terminal"]) / (1 + a["discount"]) ** 5
        if terminal["cash"] > 0
        else None
    )
    total = pv + tv if tv is not None else None
    equity = total if total is not None and total > 0 else None
    market = model["security"]["marketCapProxy"]
    investment_bridge = None
    if model.get("equityInvestmentPath"):
        asset = a["equityInvestmentValue"]
        remainder = market - asset if market is not None and asset is not None else None
        subtotal = equity + asset if equity is not None and asset is not None else None
        eligible = model["security"]["status"] == "available"
        investment_bridge = dict(
            assumedValue=asset,
            cashPathValue=equity,
            selectedSubtotal=subtotal,
            selectedSubtotalPrice=(
                subtotal / model["security"]["shares"]["value"]
                if subtotal is not None and eligible
                else None
            ),
            marketRemainder=remainder if eligible else None,
            status=(
                "security_unresolved"
                if not eligible
                else (
                    "investment_unassessed"
                    if asset is None
                    else (
                        "nonpositive_market_remainder"
                        if remainder is None or remainder <= 0
                        else "conditional_subtotal"
                    )
                )
            ),
        )
        market = (
            remainder if investment_bridge["status"] == "conditional_subtotal" else None
        )
    required_terminal = (
        (market - pv) * (1 + a["discount"]) ** 5 * (a["discount"] - a["terminal"])
        if market
        else None
    )
    result = dict(
        years=years,
        terminal=terminal,
        explicitPv=pv,
        terminalPv=tv,
        equityValue=equity,
        price=(
            equity / model["security"]["shares"]["value"]
            if equity and model["security"]["status"] == "available"
            else None
        ),
        terminalShare=tv / equity if equity else None,
        requiredTerminalCash=required_terminal,
        terminalCashGap=(
            required_terminal - terminal["cash"]
            if required_terminal is not None
            else None
        ),
        reinvestmentCaution=a["capexEnd"] + a["leaseEnd"] < a["depreciation"],
        status="calculated" if equity else "nonpositive_terminal_or_value",
    )
    if investment_bridge is not None:
        result["investmentBridge"] = investment_bridge

    if model.get("contractSupport"):
        exposure = model["contractSupport"]["maximumExposure"]
        if (
            not isinstance(exposure, (int, float))
            or not math.isfinite(exposure)
            or exposure < 0
        ):
            raise ValueError("Invalid contingent exposure")
        cases = []
        for fraction in [0.1, 0.5, 1.0]:
            for year in [1, 3, 5]:
                payment = exposure * fraction
                present = payment / (1 + a["discount"]) ** year
                stressed = equity - present if equity is not None else None
                eligible = stressed is not None and stressed > 0
                cases.append(
                    dict(
                        fraction=fraction,
                        year=year,
                        payment=payment,
                        presentValue=present,
                        equityValue=stressed if eligible else None,
                        price=(
                            stressed / model["security"]["shares"]["value"]
                            if eligible and model["security"]["status"] == "available"
                            else None
                        ),
                    )
                )
        result["contingentLossCases"] = cases
    return result


def build(c, as_of):
    if c["id"] == "NOW":
        from .servicenow_operating import build as servicenow

        return servicenow(c, as_of)
    if c["id"] == "018260":
        from .sds_operating import build as sds

        return sds(c, as_of)
    if c["id"] == "JNJ":
        from .jnj_operating import build as jnj_build

        return jnj_build(c, as_of)
    if c["id"] == "068270":
        from .celltrion_operating import build as celltrion

        return celltrion(c, as_of)
    if c["id"] == "035420":
        from .naver_operating import build as naver

        return naver(c, as_of)
    # This source contract is issuer-specific. Other companies must be reconciled
    # before adopting it; ordinary shared cash ratios do not qualify.
    if c["id"] == "012330":
        from .mobis_operating import build as mobis

        return mobis(c, as_of)
    if c["id"] == "AVGO":
        from .broadcom_operating import build as broadcom

        return broadcom(c, as_of)
    if c["id"] == "LRCX":
        from .lam_operating import build as lam

        return lam(c, as_of)
    if c["id"] == "AMAT":
        from .applied_operating import build as applied

        return applied(c, as_of)
    if c["id"] == "005930":
        from .samsung_operating import build as samsung

        return samsung(c, as_of)
    if c["id"] == "AMD":
        from .amd_operating import build as amd

        return amd(c, as_of)
    if c["id"] == "NVDA":
        from .nvidia_operating import build as nvidia

        return nvidia(c, as_of)
    if c["id"] == "000660":
        from .hynix_operating import build as hynix

        return hynix(c, as_of)
    if c["id"] == "MU":
        from .micron_operating import build as micron_build

        return micron_build(c, as_of)
    if c["id"] == "AAPL":
        from .apple_operating import build as apple

        return apple(c, as_of)
    if c["id"] == "META":
        from .meta_operating import build as meta

        return meta(c, as_of)
    if c["id"] == "GOOGL":
        from .alphabet_operating import build as alphabet

        return alphabet(c, as_of)
    if c["id"] == "AMZN":
        from .amazon_operating import build as amazon

        return amazon(c, as_of)
    if c["id"] == "000270":
        from .kia_operating import build as kia

        return kia(c, as_of)
    if c["id"] == "TSLA":
        from .tesla_operating import build as tesla

        return tesla(c, as_of)
    if c["id"] != "MSFT":
        return None
    f = c["financials"]
    if (
        not 350 <= f["days"] <= 380
        or c.get("narrative", {}).get("accession") != "0001193125-26-323660"
    ):
        return dict(
            status="source_review_required",
            reason="새 공시의 사업·현금 조정과 가정을 다시 대사해야 합니다.",
        )
    _, rows = company_filing(c, as_of)
    from .narrative import load

    corpus = load(c)
    if not corpus or any(
        i not in {p["id"] for p in corpus["passages"]} for i in PASSAGES
    ):
        raise ValueError("Operating model source passages changed")

    def fact(tag, prior=False):
        start, end = (
            (f["priorStart"], f["priorEnd"]) if prior else (f["start"], f["end"])
        )
        r = select(rows, tag, start, end, (), c["currency"])
        if r is None:
            raise ValueError("Operating cash source missing: " + tag)
        return r

    tags = {
        "operatingIncome": "OperatingIncomeLoss",
        "nonoperating": "NonoperatingIncomeExpense",
        "pretax": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "tax": "IncomeTaxExpenseBenefit",
        "netIncome": "NetIncomeLoss",
        "daOther": "DepreciationAmortizationAndOther",
        "sbc": "ShareBasedCompensation",
        "investmentGains": "GainLossOnInvestmentsAndDerivativeInstruments",
        "deferredTax": "DeferredIncomeTaxesAndTaxCredits",
        "taxPayable": "IncreaseDecreaseInAccruedIncomeTaxesPayable",
        "cfo": "NetCashProvidedByUsedInOperatingActivities",
        "depreciation": "Depreciation",
        "amortization": "AmortizationOfIntangibleAssets",
        "interestIncome": "InvestmentIncomeNet",
        "interestExpense": "InterestExpenseNonoperating",
        "cashTaxes": "IncomeTaxesPaidNet",
        "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
        "lease": "FinanceLeasePrincipalPayments",
    }
    facts = {key: fact(tag) for key, tag in tags.items()}
    val = lambda k: facts[k]["value"]
    parts = [
        dict(
            label="연결 영업이익",
            value=val("operatingIncome"),
            fact=facts["operatingIncome"],
        )
    ]
    for k, label, coefficient in [
        ("nonoperating", "영업외 손익", 1),
        ("tax", "법인세 비용", -1),
        ("daOther", "감가상각·상각·기타 조정", 1),
        ("sbc", "주식보상 되돌림", 1),
        ("investmentGains", "투자·파생 이익 되돌림", -1),
        ("deferredTax", "이연법인세 조정", 1),
        ("taxPayable", "법인세 부채 변동", 1),
    ]:
        parts.append(dict(label=label, value=val(k) * coefficient, fact=facts[k]))
    working = []
    for tag, label, coefficient in WC:
        r = fact(tag)
        working.append(dict(label=label, value=r["value"] * coefficient, fact=r))
    parts += working
    residual = val("cfo") - sum(p["value"] for p in parts)
    if (
        abs(residual) > 1
        or abs(
            val("operatingIncome") + val("nonoperating") - val("tax") - val("netIncome")
        )
        > 1
    ):
        raise ValueError("Operating-to-cash reconciliation failed")
    revenue = f["current"]["revenue"]["value"]
    revenue_growth_amount = revenue - f["previous"]["revenue"]["value"]
    if revenue_growth_amount <= 0:
        raise ValueError("Review operating capital assumption when sales contract")
    segments = []
    for s in c["business"]["segments"]:
        cur, prev = s["current"], s["previous"]
        segments.append(
            dict(
                id=s["id"],
                label=s["label"],
                revenue=cur["revenue"]["value"],
                margin=cur["operatingIncome"]["value"] / cur["revenue"]["value"],
                priorMargin=prev["operatingIncome"]["value"] / prev["revenue"]["value"],
                observedGrowth=cur["revenue"]["value"] / prev["revenue"]["value"] - 1,
                evidence=[
                    cur["revenue"],
                    cur["operatingIncome"],
                    prev["revenue"],
                    prev["operatingIncome"],
                ],
            )
        )
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=val("tax") / val("pretax"),
        netInterest=(val("interestIncome") - val("interestExpense")) / revenue,
        depreciation=(val("depreciation") + val("amortization")) / revenue,
        workingCapital=-sum(w["value"] for w in working) / revenue_growth_amount,
        capexStart=val("capex") / revenue,
        capexEnd=val("capex") / revenue,
        leaseStart=val("lease") / revenue,
        leaseEnd=val("lease") / revenue,
        discount=0.11,
        terminal=0.02,
    )
    m = dict(
        status="research_workspace",
        version=VERSION,
        sourcePeriod=[f["start"], f["end"]],
        accession=c["narrative"]["accession"],
        corpusHash=c["narrative"]["evidenceHash"],
        passages=[p for p in corpus["passages"] if p["id"] in PASSAGES],
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        bridge=dict(
            parts=parts,
            reportedCfo=val("cfo"),
            residual=residual,
            cashAfterInvestmentLeaseSbc=val("cfo")
            - val("capex")
            - val("lease")
            - val("sbc"),
        ),
        anchors=dict(
            workingCashEffect=sum(w["value"] for w in working),
            revenueIncrease=revenue_growth_amount,
            priorCapexRatio=fact(tags["capex"], True)["value"]
            / f["previous"]["revenue"]["value"],
            daOtherDifference=val("daOther")
            - val("depreciation")
            - val("amortization"),
        ),
        rules=[
            "초기 가정은 부문 매출 성장 0%, 현재 영업이익률·투입 비율 유지다. 예상 실적이나 목표가가 아니다.",
            "영업이익에는 주식보상 비용이 포함된다. 미래 현금 계산에서 이를 되돌리지 않아 보상 대체 비용을 반영하며, 매입주식을 다시 차감하지 않는다.",
            "영업외 항목은 공시 이자·배당수익에서 이자비용을 뺀 비율만 유지한다. 투자·파생·OpenAI 평가 손익은 미래에 반복하지 않는 가정이다. 기존 투자자산 별도 매각가치는 더하지 않는다.",
            "세율은 당기 법인세 비용/세전이익에서 출발한다. 실제 현금 납부세율이나 세무 전망이 아니며 이연세금·세금 납부시차를 정상화하는 연구자 가정이다.",
            "운전자본 계수는 법인세를 제외한 공시 영업자산·부채 변동 전체를 매출 증가액으로 나눈 대용치다. 장기 항목도 포함되며 매출 증가가 원인임을 뜻하지 않는다.",
            "감가상각과 무형자산 상각을 합산한다. 현금흐름표의 감가상각·상각·기타와의 차이는 별도 표시하고 미래에는 반복하지 않는 가정이다.",
            "현금 설비 취득과 금융리스 원금은 따로 차감한다. 금융리스 이자는 이자비용에 포함되고 영업리스는 영업비용에 포함된다. 비현금 리스 취득을 다시 빼지 않는다.",
            "연결 차입금은 차환해 순차입 0을 유지하는 가정이다. 초과 현금·비영업 투자자산의 일회성 배분가치를 더하지 않는다. 이 현금 경로만의 가치를 완전한 증권 적정가치로 해석하지 않는다.",
            "모형 연차는 관측 가격 기준일부터 1년 간격으로 할인한다. 연간 공시의 종료일과 가격 기준일 사이를 별도로 분기 예측하지 않았으므로 실제 회계연도 전망과 다르다.",
            "말기 현금은 6년차 매출·세금·운전자본·재투자를 다시 계산한다. 매출 성장과 운전자본 지출 없이 5년차 현금을 단순 확대하지 않는다.",
        ],
        remaining=[
            "사업부별 투자·가동률과 설비 감가상각 연령 분포",
            "신규 리스 계약과 기존 계약의 원금 상환 증가 경로",
            "고객별 수금·선수금 시차와 비반복 영업자산 변동",
            "실제 현금 세금과 초과 현금·투자자산 배분의 별도 검토",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
