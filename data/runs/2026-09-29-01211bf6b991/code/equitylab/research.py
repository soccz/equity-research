"""Exploratory, non-overlapping price experiments with explicit baselines."""

from __future__ import annotations
import math
import numpy as np


def price_summary(rows: list) -> dict:
    p = np.array([r["adjustedClose"] for r in rows], dtype=float)
    returns = np.diff(np.log(p))
    drawdown = p / np.maximum.accumulate(p) - 1
    trailing = p[-253:]
    return dict(
        lastDate=rows[-1]["date"],
        close=rows[-1]["close"],
        momentum63=float(p[-1] / p[-64] - 1),
        return252=float(p[-1] / p[-253] - 1),
        volatility21=float(np.std(returns[-21:], ddof=1) * math.sqrt(252)),
        volatility126=float(np.std(returns[-126:], ddof=1) * math.sqrt(252)),
        drawdown=float(drawdown[-1]),
        maxDrawdown252=float(np.min(trailing / np.maximum.accumulate(trailing) - 1)),
        observations=len(rows),
    )


def block_interval(values, seed=42) -> list:
    a = np.asarray(values, float)
    if len(a) < 8:
        return []
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(a), size=(2000, math.ceil(len(a) / 3)))
    indexes = (starts[:, :, None] + np.arange(3)) % len(a)
    samples = a[indexes.reshape(2000, -1)[:, : len(a)]].mean(axis=1)
    return np.quantile(samples, [0.025, 0.975]).tolist()


def run_experiment(companies: list, market: str) -> dict:
    members = [
        c for c in companies if c["market"] == market and c.get("status") == "ready"
    ]
    if len(members) < 3:
        return dict(
            market=market,
            status="insufficient_data",
            reason="같은 시장의 3개 이상 종목 필요",
        )
    by_id = {
        c["id"]: {r["date"]: r["adjustedClose"] for r in c["prices"]} for c in members
    }
    dates = sorted(set.intersection(*(set(d) for d in by_id.values())))
    if len(dates) < 400:
        return dict(
            market=market,
            status="insufficient_data",
            reason="공통 가격 관측 400일 미만",
        )
    ids = list(by_id)
    prices = np.array([[by_id[k][d] for k in ids] for d in dates])
    log_returns = np.diff(np.log(prices), axis=0)
    anchors = range(max(126, len(dates) - 525), len(dates) - 22, 21)
    policies = {
        key: [] for key in ["equal_weight", "momentum63", "momentum_risk", "oracle"]
    }
    losses = {key: [] for key in ["rv126", "rv21", "blend"]}
    windows = []
    for t in anchors:
        past = log_returns[t - 126 : t]
        rv126 = np.mean(past**2, axis=0)
        rv21 = np.mean(past[-21:] ** 2, axis=0)
        blend = 0.5 * rv126 + 0.5 * rv21
        # Signal at t, entry at next close, outcome over the following 21 sessions.
        future = prices[t + 22] / prices[t + 1] - 1
        realized = np.mean(log_returns[t + 1 : t + 22] ** 2, axis=0)
        momentum = prices[t] / prices[t - 63] - 1
        risk_score = momentum / np.sqrt(np.maximum(rv21, 1e-12))
        selected = {
            "momentum63": np.argsort(momentum, kind="stable")[-2:],
            "momentum_risk": np.argsort(risk_score, kind="stable")[-2:],
            "oracle": np.argsort(future, kind="stable")[-2:],
        }
        outcomes = {
            "equal_weight": float(np.mean(future)),
            **{
                key: float(np.mean(future[indexes]))
                for key, indexes in selected.items()
            },
        }
        assert outcomes["oracle"] + 1e-12 >= max(outcomes.values())
        for key, value in outcomes.items():
            policies[key].append(value)
        for key, forecast in [("rv126", rv126), ("rv21", rv21), ("blend", blend)]:
            ratio = np.maximum(realized, 1e-12) / np.maximum(forecast, 1e-12)
            losses[key].append(float(np.mean(ratio - np.log(ratio) - 1)))
        windows.append(
            dict(
                signalDate=dates[t],
                entryDate=dates[t + 1],
                endDate=dates[t + 22],
                picks={k: [ids[i] for i in ix] for k, ix in selected.items()},
                returns=outcomes,
            )
        )
    baseline = np.array(policies["equal_weight"])
    policy_results = []
    for key, outcomes in policies.items():
        a = np.array(outcomes)
        diff = a - baseline
        ci = block_interval(diff)
        policy_results.append(
            dict(
                id=key,
                cumulativeReturn=float(np.prod(1 + a) - 1),
                meanExcess=float(diff.mean()),
                excessInterval=ci,
                winRate=float(np.mean(diff > 0)) if key != "equal_weight" else None,
                status=(
                    "oracle_not_tradeable"
                    if key == "oracle"
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
                path=(np.cumprod(1 + a) * 100).tolist(),
            )
        )
    risk = []
    for key, outcomes in losses.items():
        differences = np.array(outcomes) - np.array(losses["rv126"])
        risk.append(
            dict(
                id=key,
                qlike=float(np.mean(outcomes)),
                difference=float(np.mean(differences)),
                interval=block_interval(differences),
            )
        )
    return dict(
        market=market,
        status="exploratory",
        members=ids,
        windows=windows,
        windowCount=len(windows),
        start=windows[0]["entryDate"],
        end=windows[-1]["endDate"],
        policies=policy_results,
        risk=risk,
        contract=dict(
            horizonSessions=21,
            entryLagSessions=1,
            signalLookback=63,
            riskLookbacks=[21, 126],
            weighting="상위 2개 동일가중; 기준선 전체 동일가중",
            currency="각 시장 현지 통화",
            costs="비용·세금 미반영, 체결 재현 아님",
            interval="시간창별 종목 평균 후 길이 3 순환 블록 부트스트랩 2,000회 · 탐색 구간 · 다중검정 미보정",
        ),
        limitations=[
            "현재 선택한 4개 생존 기업의 탐색 표본이다. 당시 전체 시장·업종 유니버스를 재현하지 않았다.",
            "현재 재무 수치를 과거 선별에 사용하지 않았다. 가격 기반 두 규칙만 비교한다.",
            "완전예지는 미래를 사용한 같은 제약 내 상한이다. 달성 가능한 투자 성과가 아니다.",
            "두 시장의 수익은 투자자의 공통 통화로 환산하지 않았으므로 합산 포트폴리오가 아니다.",
            "현재 공급자가 조정한 가격의 과거 시계열이며 당시 수집된 가격 버전은 아니다.",
            "혼합 위험 예측에서 21일 정보를 제거하면 RV126 기준선이 된다. 개선과 경제적 가치를 별도로 읽는다.",
        ],
    )
