"""Source-bound research conclusions, peer trade-offs and future observations."""

from datetime import date
from .data import canonical, digest


def peer_rows(c, companies):
    rows = []
    t = c.get("trailingYear", {})
    if t.get("status") != "ready":
        return rows
    for other in companies:
        if other["id"] == c["id"] or other.get("status") != "ready":
            continue
        cloud_pair = {c["id"], other["id"]} == {"MSFT", "GOOGL"}
        if other["peerGroup"] != c["peerGroup"] and not cloud_pair:
            continue
        q = other.get("trailingYear", {})
        if q.get("status") != "ready":
            continue
        issues = []
        investment_comparable = t["investmentScope"] == q["investmentScope"]
        cash_scope_comparable = not any(
            x.get("cashScope", {}).get("status") == "review_required"
            for x in [c, other]
        )
        if not investment_comparable:
            issues.append("투자자산 범위 차이")
        if not cash_scope_comparable:
            issues.append("중단영업 현금과 계속영업 매출·투자 범위 대사 전 비교 보류")
            investment_comparable = False
        if abs((date.fromisoformat(t["end"]) - date.fromisoformat(q["end"])).days) > 35:
            issues.append("최근 일 년 종료일 차이")
        if c["financials"]["standard"] != other["financials"]["standard"]:
            issues.append("회계 기준·현금 분류 차이")
        if cloud_pair:
            issues.append(
                "클라우드를 포함한 연결 회사 비교; 클라우드 사업부 단독 우열 아님"
            )
        fields = ["operatingMargin", "cfoMargin", "investmentMargin", "cashMargin"]
        differences = {
            k: (
                t["metrics"][k] - q["metrics"][k]
                if t["metrics"][k] is not None and q["metrics"][k] is not None
                else None
            )
            for k in fields
        }
        if not investment_comparable:
            differences["cashMargin"] = None
            differences["investmentMargin"] = None
        if not cash_scope_comparable:
            differences["cfoMargin"] = None
        cash, invest = differences["cashMargin"], differences["investmentMargin"]
        if not cash_scope_comparable:
            conclusion = "중단영업 현금과 계속영업 매출·투자 범위 대사 후 비교"
        elif not investment_comparable:
            conclusion = "투자자산 정의를 일치시킨 뒤 현금·투자 비율 우열 비교"
        elif cash is None or invest is None:
            conclusion = "공통 비율 보완 후 비교"
        elif cash > 0 and invest <= 0:
            conclusion = "투자 부담이 작고 투자 후 현금 비율이 높음: 반복성 조사 우선"
        elif cash > 0:
            conclusion = (
                "더 큰 투자 부담에도 투자 후 현금 비율이 높음: 성장투자 회수 확인"
            )
        elif invest < 0:
            conclusion = (
                "투자 부담이 작은데도 투자 후 현금 비율이 낮음: 영업현금 구조 확인"
            )
        else:
            conclusion = (
                "투자 부담이 크고 투자 후 현금 비율이 낮음: 투자 주기·회수 조건 확인"
            )
        rows.append(
            dict(
                id=other["id"],
                name=other["name"],
                market=other["market"],
                period=[q["start"], q["end"]],
                metrics=q["metrics"],
                investmentComparable=investment_comparable,
                differences=differences,
                cautions=issues,
                conclusion=conclusion,
                evidenceHash=q["evidenceHash"],
                source=other["financials"]["current"]["cfo"]["sourceUrl"],
                comparisonScope="연결 회사 현금 구조의 조사 비교. 투자 선호·동일 사업모형·가치평가 우열을 뜻하지 않음",
            )
        )
    return sorted(rows, key=lambda r: (r["market"] == c["market"], r["id"]))


def build(c, companies):
    m, t = c["metrics"], c.get("trailingYear", {})
    v, b = c.get("valuation", {}), c.get("business") or {}
    peers = peer_rows(c, companies)
    watch = [
        dict(
            id="cash_margin",
            label="같은 길이 전년 대비 투자 후 현금 마진",
            metric="cashMarginChange",
            baseline=0,
            operator=">",
            expected=None,
            definition="같은 공시 기간의 전년 대비 현금 마진 변화가 영보다 큰지 관측",
            weakens="개선되지 않으면 현금 확장 지속성을 재검토한다. 투자 목적·수금 시점은 별도 조사한다.",
        )
    ]
    observations = []
    for s in b.get("segments", []):
        cur, prev = s["current"], s["previous"]
        if not all(cur.get(k) and prev.get(k) for k in ["revenue", "operatingIncome"]):
            continue
        if min(cur["revenue"]["value"], prev["revenue"]["value"]) <= 0:
            continue
        growth = cur["revenue"]["value"] / prev["revenue"]["value"] - 1
        margin = cur["operatingIncome"]["value"] / cur["revenue"]["value"]
        old_margin = prev["operatingIncome"]["value"] / prev["revenue"]["value"]
        observations.append(
            dict(
                id=s["id"],
                label=s["label"],
                revenueGrowth=growth,
                margin=margin,
                marginChange=margin - old_margin,
                revenue=cur["revenue"]["value"],
                operatingIncome=cur["operatingIncome"]["value"],
                source=cur["revenue"]["sourceUrl"],
                evidence=[*cur.values(), *prev.values()],
            )
        )
    driver = max(observations, key=lambda r: abs(r["operatingIncome"]), default=None)
    if driver:
        watch.append(
            dict(
                id="segment_margin:" + driver["id"],
                metric="segmentMarginChange",
                segmentId=driver["id"],
                label=driver["label"] + " 영업이익률 전년 대비 변화",
                baseline=0,
                operator=">",
                expected=None,
                definition=driver["label"]
                + "의 동일 범위·같은 길이 전년 대비 이익률이 개선되는지 관측",
                weakens="이익률이 개선되지 않으면 해당 부문의 이익 확대 설명을 재검토한다. 부문 변경·공통비 배분 변경 시 비교를 보류한다.",
            )
        )
    if c.get("dossier"):
        observations_scope = "현금·채권 주석과 기초·기말·전년 관측을 함께 확인"
    elif driver:
        observations_scope = (
            driver["label"]
            + "의 영업이익 절댓값이 확인된 부문 중 가장 큼. 연결 이익의 인과 기여도와는 다름"
        )
    else:
        observations_scope = (
            "연결 공시의 이익·현금·재투자와 자본 구조를 확인; 사업부 원인은 미확인"
        )
    pricing = dict(
        state=(
            "사업 범위 대사"
            if c.get("cashScope", {}).get("status") == "review_required"
            else "증권 범위 보완"
        ),
        statement=(
            c["cashScope"]["reason"]
            if c.get("cashScope", {}).get("status") == "review_required"
            else "보통주 배분 범위와 공시 유통주식수를 확인한 뒤 가격 조건을 판단한다."
        ),
    )
    if v.get("status") == "workspace" and v.get("priceRequirement"):
        req = v["requiredCfoMargin"]
        low, high = v["historicalCfoRange"]
        ref, favorable = v["cases"][1], v["cases"][2]
        price = c["priceSummary"]["close"]
        if favorable["price"] is None or favorable["price"] < price:
            state = "추가 성장 근거 필요"
            statement = "과거 범위의 현금 여유 조합도 기본 할인 가정에서는 현재 가격에 미달한다. 성장·재투자 또는 요구수익률 가정의 변경 근거가 먼저 필요하다."
        elif ref["price"] is None or ref["price"] < price:
            state = "실적 조건부 검토"
            statement = "과거 비율의 중앙값 조합으로는 현재 가격에 미달하지만 현금 여유 조합에서는 도달한다. 더 나은 현금 창출·투자 부담의 지속 여부가 판단을 가른다."
        else:
            state = "가정 충족 시 선호 검토"
            statement = "과거 비율의 중앙값 조합이 기본 할인 가정에서 현재 가격을 넘는다. 누락된 배분 부담과 현금 지속성, 비교 기업의 대안을 확인하면 조건부 선호를 검토할 수 있다."
        pricing = dict(
            state=state,
            statement=statement,
            requiredCfoMargin=req,
            historicalRange=[low, high],
            referencePrice=ref["price"],
            favorablePrice=favorable["price"],
            price=price,
            assumptions=v["defaults"],
            unknownAdjustments=v["unknownAdjustments"],
            evidenceHash=v["evidenceHash"],
        )
    from .operating_judgment import build as operating_judgment

    operating = operating_judgment(c)
    if operating:
        pricing = operating
    result = dict(
        version="research-case-v1",
        company=c["id"],
        scope="관측과 명시적 가정에 따른 연구 판단. AI 문장을 채택하거나 검증된 초과수익으로 바꾸지 않음",
        observationScope=observations_scope,
        segments=observations,
        driver=driver,
        peers=peers,
        pricing=pricing,
        watch=watch,
        thesis=(
            "현금 확대의 지속성"
            if m["cashMarginChange"] is not None and m["cashMarginChange"] > 0
            else "재투자 부담과 현금 회복 조건"
        ),
        countercase=(
            "연결 현금 개선이 일시적 수금·지급 시점이나 투자 지연에서 왔다면 반복 가정이 약해진다. 해당 원인은 공시 수치만으로 확정하지 않는다."
            if m["cashMarginChange"] is not None and m["cashMarginChange"] > 0
            else "현금 감소가 장래 수익을 위한 투자와 일시적 운전자본에서 왔다면 단기 현금만으로 사업 악화를 판단하기 어렵다. 투자 회수와 매출 전환 근거를 확인한다."
        ),
        nextEvidence=(b.get("remaining") or c["analysis"]["questions"]),
        filedAt=c["financials"]["filedAt"],
        periodEnd=c["financials"]["end"],
        source=c["financials"]["current"]["cfo"]["sourceUrl"],
    )
    insight = c.get("businessInsight") or {}
    if insight.get("status") == "source_draft" and insight.get("corpusHash") == c.get(
        "narrative", {}
    ).get("evidenceHash"):
        result.update(
            version="research-case-v2",
            thesis=insight["title"],
            interpretation=insight["interpretation"],
            countercase=insight["countercase"],
            businessEvidenceHash=insight["evidenceHash"],
            businessSources=insight["sources"],
            nextEvidence=list(
                dict.fromkeys(
                    [
                        insight["changeCondition"],
                        *(
                            operating["unknownAdjustments"]
                            if operating
                            else result["nextEvidence"]
                        ),
                    ]
                )
            ),
        )
    result["evidenceHash"] = digest(canonical(result))
    return result
