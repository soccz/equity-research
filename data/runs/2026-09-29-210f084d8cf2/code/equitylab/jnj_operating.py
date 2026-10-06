"""JNJ pretax segment paths with source cash reconciliation and explicit investment scope."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import extract, load
from .pharma_comparison import CURRENT, CORPUS, SOURCE, PRETAX, REVENUE, ROLES

ANNUAL = "0000200406-26-000016"
ANNUAL_XBRL = "37d6dddc840c2dc70cbb41d1d9fbfca17bdf0a0f3ae9cac4593b3b7c655937c9"
ANNUAL_HTML = "12283864a644d9980728e193a3acc8960e110f6b445939be44f2b0bfb3001adf"
ANNUAL_ROOT = ROOT
PASSAGES = [
    "f10212711e6978e3f926",
    "3fc5990413bc8fe4e532",
    "dfa309bf29d032949ae0",
    "5f3cc8eafe91860981cd",
    "4e22ed56461e098489a2",
    "fcac921abb3356e03efb",
    "1710e48a81b4a53e9d49",
    "223eca7b64af8202d03d",
    "5440199e5853f880961e",
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="JNJ 제품·부문 세전이익·미배분 비용과 인수·소송 현금을 새 공시에서 대사해야 합니다.",
        )
    source, current = company_filing(c, as_of)
    a = json.loads(
        (ANNUAL_ROOT / f"data/sources/filing-{ANNUAL}-xbrl.manifest.json").read_text()
    )
    h = json.loads(
        (ANNUAL_ROOT / f"data/sources/filing-{ANNUAL}.manifest.json").read_text()
    )
    if (
        source["sha256"] != SOURCE
        or a["sha256"] != ANNUAL_XBRL
        or h["sha256"] != ANNUAL_HTML
    ):
        raise ValueError("JNJ reviewed source changed")
    if a["accession"] != ANNUAL or a["cik"] != c["cik"] or as_of < "2026-07-23":
        raise ValueError("JNJ source identity or timing changed")
    annual = instance_rows(
        read_verified(ANNUAL_ROOT / a["file"], ANNUAL_XBRL), c, a, ANNUAL, "2026-02-11"
    )
    annual_ps = extract(read_verified(ANNUAL_ROOT / h["file"], ANNUAL_HTML))
    for item in [a, a["indexSource"], h]:
        item = dict(item, provider="SEC")
        item.setdefault("retrievedAt", a["retrievedAt"])
        read_verified(ANNUAL_ROOT / item["file"], item["sha256"])
        if item["file"] not in {s["file"] for s in c["sources"]}:
            c["sources"].append(item)
    f = c["financials"]
    periods = [
        (1, annual, "2024-12-30", "2025-12-28"),
        (1, current, f["start"], f["end"]),
        (-1, current, f["priorStart"], f["priorEnd"]),
    ]
    if [(s, e) for _, _, s, e in periods][1:] != [
        ("2025-12-29", "2026-06-28"),
        ("2024-12-30", "2025-06-29"),
    ]:
        raise ValueError("JNJ fiscal periods changed")

    def exact(rs, tag, start, end, dims=(), precision="-6"):
        if end == "2025-12-28":
            tag = {
                "InProcessResearchAndDevelopmentCharge": "ResearchAndDevelopmentExpense",
                "PaymentsToAcquireInProcessResearchAndDevelopmentAssets": "PaymentsToAcquiredInProcessResearchAndDevelopmentAssets",
            }.get(tag, tag)
        r = select(
            [r for r in rs if r["decimals"] == precision], tag, start, end, dims, "USD"
        )
        if r is None:
            raise ValueError("JNJ missing exact fact " + tag + " " + end)
        return r

    def combined(tag, dims=()):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, start, end, dims))
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            start="2025-06-30",
            end="2026-06-28",
            unit="USD",
            derived=True,
            sourceUrl=source["primaryUrl"],
        )

    tags = dict(
        revenue=REVENUE,
        pretax=PRETAX,
        unallocated="SegmentReportingOtherItemAmount",
        netIncome="NetIncomeLoss",
        tax="IncomeTaxExpenseBenefit",
        cfo="NetCashProvidedByUsedInOperatingActivities",
        depreciation="DepreciationDepletionAndAmortization",
        sbc="ShareBasedCompensation",
        ppe="PaymentsToAcquirePropertyPlantAndEquipment",
        acquisitions="PaymentsToAcquireBusinessesNetOfCashAcquired",
        researchPurchases="PaymentsToAcquireInProcessResearchAndDevelopmentAssets",
        otherInvestment="PaymentsForProceedsFromOtherInvestingActivities",
    )
    facts = {key: combined(tag) for key, tag in tags.items()}
    v = lambda key: facts[key]["value"]
    checks = []
    for coefficient, rs, start, end in periods:
        parts = []
        for tag, label, sign, _ in ROLES:
            fact = exact(rs, tag, start, end)
            parts.append(
                dict(label=label, tag=tag, value=sign * fact["value"], fact=fact)
            )
        cfo = exact(rs, tags["cfo"], start, end)["value"]
        residual = cfo - sum(p["value"] for p in parts)
        pre = exact(rs, PRETAX, start, end)["value"]
        tax = exact(rs, tags["tax"], start, end)["value"]
        if residual != 0 or pre - tax != parts[0]["value"]:
            raise ValueError("JNJ pretax-to-cash bridge mismatch")
        checks.append(
            dict(
                coefficient=coefficient,
                start=start,
                end=end,
                parts=parts,
                reportedCfo=cfo,
                residual=residual,
            )
        )
    segments = []
    for member, label in [
        ("InnovativeMedicineMember", "Innovative Medicine"),
        ("MedTechMember", "MedTech"),
    ]:
        dims = [
            ("ConsolidationItemsAxis", "OperatingSegmentsMember"),
            ("StatementBusinessSegmentsAxis", member),
        ]
        rev = combined(REVENUE, dims)
        profit = combined(PRETAX, dims)
        cur = exact(current, REVENUE, f["start"], f["end"], dims)
        old = exact(current, REVENUE, f["priorStart"], f["priorEnd"], dims)
        current_profit = exact(current, PRETAX, f["start"], f["end"], dims)
        old_profit = exact(current, PRETAX, f["priorStart"], f["priorEnd"], dims)
        segments.append(
            dict(
                id=member,
                label=label,
                revenue=rev["value"],
                margin=profit["value"] / rev["value"],
                priorMargin=old_profit["value"] / old["value"],
                observedGrowth=cur["value"] / old["value"] - 1,
                evidence=[rev, profit, cur, old, current_profit, old_profit],
            )
        )
        for _, rs, start, end in periods:
            reported = exact(
                rs,
                PRETAX,
                start,
                end,
                [("ConsolidationItemsAxis", "OperatingSegmentsMember")],
            )["value"]
            corp = exact(rs, tags["unallocated"], start, end)["value"]
            if reported - corp != exact(rs, PRETAX, start, end)["value"]:
                raise ValueError("JNJ corporate cost reconciliation changed")
    for _, rs, start, end in periods:
        dimensions = [
            [
                ("ConsolidationItemsAxis", "OperatingSegmentsMember"),
                ("StatementBusinessSegmentsAxis", member),
            ]
            for member in ["InnovativeMedicineMember", "MedTechMember"]
        ]
        segment_sales = sum(
            exact(rs, REVENUE, start, end, d)["value"] for d in dimensions
        )
        segment_profit = sum(
            exact(rs, PRETAX, start, end, d)["value"] for d in dimensions
        )
        if (
            segment_sales != exact(rs, REVENUE, start, end)["value"]
            or segment_profit - exact(rs, tags["unallocated"], start, end)["value"]
            != exact(rs, PRETAX, start, end)["value"]
        ):
            raise ValueError("JNJ source-period segment totals changed")
    if (
        sum(s["revenue"] for s in segments) != v("revenue")
        or abs(
            sum(s["revenue"] * s["margin"] for s in segments)
            - v("unallocated")
            - v("pretax")
        )
        > 1
    ):
        raise ValueError("JNJ trailing segment bridge mismatch")
    revenue = v("revenue")
    increase = f["current"]["revenue"]["value"] - f["previous"]["revenue"]["value"]
    working = -sum(
        exact(current, tag, f["start"], f["end"])["value"]
        for tag in [
            "IncreaseDecreaseInAccountsReceivable",
            "IncreaseDecreaseInInventories",
        ]
    )
    capital = sum(
        v(k) for k in ["ppe", "acquisitions", "researchPurchases", "otherInvestment"]
    )
    investment_parts = [
        dict(label=label, fact=facts[key])
        for key, label in [
            ("ppe", "유형자산 현금 취득"),
            ("acquisitions", "기업 인수 순현금"),
            ("researchPurchases", "취득 진행 중 연구개발·마일스톤"),
            ("otherInvestment", "기타 투자 (라이선스·마일스톤 포함)"),
        ]
    ]
    index = {x["id"]: x for x in load(c)["passages"]}
    if any(pid not in index for pid in PASSAGES):
        raise ValueError("JNJ business passages missing")
    historic = [
        p
        for p in annual_ps
        if "Commitments under finance leases are not significant" in p["text"]
        or "Cash paid for amounts included in the measurement" in p["text"]
    ]
    if len(historic) != 2:
        raise ValueError("JNJ annual lease disclosure changed")
    bridge_parts = [
        dict(label=label, value=sign * combined(tag)["value"], fact=combined(tag))
        for tag, label, sign, _ in ROLES
    ]
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        corporateStart=v("unallocated") / revenue,
        corporateEnd=v("unallocated") / revenue,
        tax=0.25,
        netInterest=0,
        depreciation=v("depreciation") / revenue,
        workingCapital=-working / increase if increase > 0 else 0,
        capexStart=capital / revenue,
        capexEnd=capital / revenue,
        leaseStart=0,
        leaseEnd=0,
        discount=0.12,
        terminal=0.02,
    )
    m = dict(
        status="research_workspace",
        version="jnj-pretax-investment-path-v1",
        sourcePeriod=["2025-06-30", "2026-06-28"],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        basisLabel="보고 부문 세전이익·미배분 비용 및 세 기간 현금 대사",
        groupLabel="보고 부문 (세전이익 기준)",
        growthLabel="같은 상반기 대비",
        marginLabel="부문 세전이익률",
        pretaxPath=True,
        unallocatedPath=True,
        corporateLabel="미배분 소송·이자·본사 순비용",
        netInterestLabel="추가 순이자 (미배분 비용 포함·0 고정)",
        capexLabel="설비·인수·취득 연구개발·기타 투자",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        intro="Innovative Medicine·MedTech의 보고 세전이익에서 미배분 비용을 차감합니다. 이 비용에는 이자·소송·본사 항목이 들어가므로 순이자를 다시 빼지 않습니다. 다른 기업의 영업이익률과 같은 지표로 비교하지 않습니다.",
        businessCaption="제품 구성·인수·환율·평가손익과 사업 분리 비용이 보고 부문 이익에 포함됩니다. 최근 반기 성장률은 유기 성장이나 미래 전망이 아닙니다.",
        bridgeLabel="순이익 → 공시 영업현금 대사 (보고 세전이익−법인세 별도 확인)",
        bridge=dict(
            parts=bridge_parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=v("cfo") - capital - v("sbc"),
        ),
        observedResidualLabel="영업현금 − 설비·인수·취득 연구개발·기타 투자 − 주식보상 비용 대용 (금융리스 전액 미확인)",
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=increase,
            actualFinanceLeasePrincipal=None,
            investmentComponents=investment_parts,
            corporateCost=v("unallocated"),
            cashDepreciation=v("depreciation"),
        ),
        anchorSummary="추가 매출당 자금 소요는 최근 반기의 매출채권·재고 현금 유출만 사용한 제한된 대용입니다. 기타 영업자산·부채의 큰 변동과 소송·조세·파생계약 담보를 고객 자금으로 합치지 않습니다.",
        cashAnchors=[
            dict(
                label=x["label"],
                period="최근1년",
                value=x["fact"]["value"],
                sourceUrl=source["primaryUrl"],
                scope="원 현금표의 별도 행. 미래 반복 비율은 편집 가정이며 정상 투자 부담으로 승인되지 않음",
            )
            for x in investment_parts
        ]
        + [
            dict(
                label="금융리스 실제 원금 지급 전액",
                period="최근1년",
                value=None,
                sourceUrl=h["url"],
                scope="연간 주석의 중요하지 않은 약정이 실제 지급0을 입증하지 않음. 미래 기본0은 연구자 가정",
            )
        ],
        passages=[index[p] for p in PASSAGES],
        historicalPassages=[
            dict(x, sourceUrl=h["url"], sourceHash=ANNUAL_HTML) for x in historic
        ],
        rules=[
            "세전이익은 영업이익과 다른 보고 지표입니다. 미배분 항목에 이자가 이미 들어 있어 추가 순이자 가정은0으로 고정합니다. 사업 부문과 미배분 비용을 별도로 편집합니다.",
            "연간+당기 반기−전년 반기로 같은 회계 범위의 최근1년을 연결합니다. 전년 반기 talc 충당금 환입은 연간과 전년 반기에 함께 있으므로 최근1년에서 다시70억 달러를 차감하지 않습니다.",
            "감가상각·무형상각을 되돌리는 대신 설비·기업 인수 순현금·취득 연구개발·기타 투자를 모두 재투자 경로에 넣습니다. 인수 무형자산의 공정가치를 현금 취득에 다시 합치지 않습니다.",
            "기타 투자 행은 라이선스·마일스톤을 포함하나 전액을 그 항목으로 확정하지 않습니다. 인수액이 큰 해와 작은 해의 차이를 정상 재투자율 차이로 승인하지 않습니다. 인수 현금이 미래 매출 성장을 자동으로 만드는 모델도 아닙니다.",
            "주식보상은 미래 이익에서 비용으로 남기며 현금표 되돌림을 미래 가용 현금에 더하지 않습니다. 운영리스 비용을 되돌리거나 금융리스0을 실제 지급액으로 단정하지 않습니다.",
            "기본 세율25%는 명시적 연구 가정이며 법정세율·회사 전망이 아닙니다. 보고 실효세율에는 지역 구성·공제·이연 항목이 포함됩니다.",
            "미배분 소송·본사 비용과 부문 평가손익·구조조정·인수통합·사업분리 비용의 정상화는 별도 검토 대상입니다. talc 충당금의 현재가치를 최대 손실로 사용하지 않습니다.",
            "초과현금·투자자산·부채 상환 일정·미확인 계약 지급은 전체 주식가치 검토에서 추가 보완합니다. 신규 순차입0과 현재 사업 범위 지속은 미래 연구 가정입니다.",
        ],
        remaining=[
            "반복 연구개발·인수·라이선스 대체 부담과 제품별 현금 회수",
            "talc 및 소송·본사 비용 정상화와 실제 지급 시점",
            "MedTech 분리 범위·일회 비용과 인수 무형상각 조정",
            "금융리스 전액·초과현금·주주 배분과 세율 근거",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
