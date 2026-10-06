import math

def calculate(model, assumptions):
    """Five explicit years plus a separately recalculated terminal cash year."""
    a = assumptions
    income_key = "pretaxIncome" if model.get("pretaxPath") else "operatingIncome"
    if model.get("pretaxPath") and (a.get("netInterest") != 0 or any(model.get(k) for k in ("grossProfitPath", "consolidationPath", "normalizationPath"))):
        raise ValueError("Pretax paths already include interest and cannot mix profit bases")
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
            unallocated = {("segmentPretaxIncome" if model.get("pretaxPath") else "segmentOperatingIncome"): op, "corporateCost": corporate}
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
