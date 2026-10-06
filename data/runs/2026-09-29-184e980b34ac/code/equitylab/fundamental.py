"""Walk-forward accounting screen using only filings available before each signal."""

from datetime import date, timedelta
import numpy as np
from .data import statement
from .research import block_interval


def signal(facts, signal_date):
    from .pipeline import financial_metrics

    cutoff = (date.fromisoformat(signal_date) - timedelta(days=1)).isoformat()
    s = statement(facts, cutoff)
    if (date.fromisoformat(cutoff) - date.fromisoformat(s["end"])).days > 200:
        raise ValueError("Financial period older than 200 days")
    m = financial_metrics(s)
    if m["revenueGrowth"] is None or m["cashMarginChange"] is None:
        raise ValueError("Comparable prior period missing")
    return dict(
        passes=m["revenueGrowth"] > 0
        and m["cashAfterInvestment"] > 0
        and m["cashMarginChange"] > 0,
        withoutGrowth=m["cashAfterInvestment"] > 0 and m["cashMarginChange"] > 0,
        metrics=m,
        periodEnd=s["end"],
        filedAt=s["filedAt"],
        cutoff=cutoff,
        evidence=[
            dict(
                tag=f["tag"],
                start=f["start"],
                end=f["end"],
                filedAt=f["filedAt"],
                sourceHash=f["sourceHash"],
                accession=f["accession"],
            )
            for block in [s["current"], s["previous"]]
            for f in block.values()
            if f
        ],
    )


def evaluate(companies, histories, price_experiment):
    market = price_experiment["market"]
    if price_experiment.get("status") != "exploratory":
        return dict(
            market=market, status="insufficient_data", reason="가격 비교 대상 미확보"
        )
    ids = price_experiment["members"]
    series = {
        c["id"]: {p["date"]: p["adjustedClose"] for p in c["prices"]}
        for c in companies
        if c["id"] in ids
    }
    windows = []
    missing = []
    returns = {
        p: []
        for p in ["equal_weight", "financial_screen", "without_growth", "oracle_one"]
    }
    for anchor in price_experiment["windows"]:
        available = {}
        issues = {}
        for id in ids:
            try:
                available[id] = signal(histories[id], anchor["signalDate"])
            except (ValueError, KeyError) as exc:
                issues[id] = str(exc)
        if issues:
            missing.append(dict(signalDate=anchor["signalDate"], issues=issues))
            continue
        future = {
            id: series[id][anchor["endDate"]] / series[id][anchor["entryDate"]] - 1
            for id in ids
        }
        qualified = [id for id in ids if available[id]["passes"]]
        ablation = [id for id in ids if available[id]["withoutGrowth"]]
        picks = {
            "equal_weight": ids,
            "financial_screen": qualified or ids,
            "without_growth": ablation or ids,
            "oracle_one": [max(ids, key=future.get)],
        }
        outcome = {
            key: float(np.mean([future[id] for id in selected]))
            for key, selected in picks.items()
        }
        assert outcome["oracle_one"] + 1e-12 >= max(outcome.values())
        for key, value in outcome.items():
            returns[key].append(value)
        windows.append(
            dict(
                signalDate=anchor["signalDate"],
                entryDate=anchor["entryDate"],
                endDate=anchor["endDate"],
                signals=available,
                picks=picks,
                returns=outcome,
                fallbackToEqualWeight=not qualified,
            )
        )
    if not windows:
        return dict(
            market=market,
            status="insufficient_data",
            reason="모든 종목의 당시 비교 공시가 갖춰진 구간 없음",
            unresolvedWindows=missing,
        )
    baseline = np.array(returns["equal_weight"])
    policies = []
    for key, values in returns.items():
        values = np.array(values)
        diff = values - baseline
        ci = block_interval(diff)
        policies.append(
            dict(
                id=key,
                cumulativeReturn=float(np.prod(1 + values) - 1),
                meanExcess=float(diff.mean()),
                interval=ci,
                status=(
                    "oracle_not_tradeable"
                    if key == "oracle_one"
                    else (
                        "baseline"
                        if key == "equal_weight"
                        else (
                            "exploratory_positive"
                            if ci and ci[0] > 0
                            else "inconclusive"
                        )
                    )
                ),
                path=(100 * np.cumprod(1 + values)).tolist(),
            )
        )
    return dict(
        market=market,
        status="exploratory",
        members=ids,
        start=windows[0]["entryDate"],
        end=windows[-1]["endDate"],
        windowCount=len(windows),
        unresolvedWindows=missing,
        windows=windows,
        policies=policies,
        contract={
            "information": "공시일이 신호일보다 이른 자료만 사용. 같은 날 제출은 제외.",
            "selection": "세 재무 조건을 모두 만족한 종목 동일가중. 0개면 전체 동일가중으로 복귀.",
            "ablation": "매출 성장 조건만 제거하고 나머지 두 조건은 유지.",
            "oracle": "1~전체 종목의 동일가중·전액투자 선택군에서 다음 구간 최고 수익 한 종목의 상한.",
            "missing": "한 종목이라도 당시 공시 또는 동일 길이 전년 비교가 없으면 모든 규칙에서 해당 구간 제외.",
            "limitations": "현재 생존 기업의 사후 개발 표본 · 비용 전 · 현지 통화 · 조건 사전 등록 전의 탐색. 통계적 독립·전체 시장 대표성·투자 성과 인증 없음.",
        },
    )
