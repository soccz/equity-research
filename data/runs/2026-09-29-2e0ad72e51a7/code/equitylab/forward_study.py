"""One frozen future coverage study; no retrospective extension of the old cohort."""

from datetime import datetime, timezone
import json
from zoneinfo import ZoneInfo
from .data import ROOT, canonical, digest

PATH = ROOT / "data/forward-study.json"


def freeze(snapshot, path=PATH, now=None):
    if path.exists():
        return read(path)
    now = now or datetime.now(timezone.utc)
    markets = {}
    for market in ["US", "KR"]:
        members = [c for c in snapshot["companies"] if c["market"] == market]
        if any(c["status"] != "ready" for c in members):
            raise ValueError(
                "Future study requires complete registered coverage at formation"
            )
        timezone_name = "America/New_York" if market == "US" else "Asia/Seoul"
        day = now.astimezone(ZoneInfo(timezone_name)).date().isoformat()
        if snapshot["asOf"] >= day:
            raise ValueError("Formation inputs must precede registration day")
        gates = {
            c["id"]: {g["id"]: g["passed"] for g in c["assessment"]["gates"]}
            for c in members
        }
        eligible = [
            c["id"] for c in members if c["assessment"]["priority"] == "심층 조사 후보"
        ]
        relaxed = [
            c["id"]
            for c in members
            if not c["assessment"]["issues"]
            and all(gates[c["id"]][k] is True for k in ["surplus", "margin"])
        ]
        momentum = [
            c["id"]
            for c in sorted(
                members, key=lambda c: (-c["priceSummary"]["momentum63"], c["id"])
            )[:5]
        ]
        markets[market] = dict(
            registrationDay=day,
            calendarCompany="MU" if market == "US" else "000660",
            members=[c["id"] for c in members],
            selection=dict(
                equal_weight=[c["id"] for c in members],
                cash_conditions=eligible,
                without_growth=relaxed,
                momentum63_top5=momentum,
            ),
            formation=[
                dict(
                    company=c["id"],
                    filedAt=c["financials"]["filedAt"],
                    priceDate=c["priceSummary"]["lastDate"],
                    gates=gates[c["id"]],
                    issues=c["assessment"]["issues"],
                    momentum63=c["priceSummary"]["momentum63"],
                )
                for c in members
            ],
        )
    protocol = dict(
        version="forward-coverage-v1",
        registeredAt=now.isoformat(),
        snapshotHash=snapshot["contentHash"],
        asOf=snapshot["asOf"],
        markets=markets,
        horizons=[21, 63],
        oneWayCost=0.001,
        cashReturn=0,
        entryRule="시장별 지정 달력 종목의 등록일 다음 거래일부터 관측 종가 진입. 진입일로부터 지정 거래일 수 뒤 종가까지 보유. 모든 기업에 정확히 같은 날짜 요구.",
        missingRule="진입·종료 가격이 없는 기업을 제거하거나 다음 날짜로 옮기지 않는다. 해당 시장 구간 전체를 자료 미확인으로 남긴다. 상장폐지·거래정지 자료는 수동 보완 후 같은 계약으로 재검사한다.",
        method="고정 대상의 동일가중 보유. 선택 공집합은 수익률 영의 현금. 왕복 거래비용은 투자시 편도 가정의 두 배를 단순 차감. 현지 통화, 공급자 배당·분할 조정 종가.",
        decisionRule="한 번의 전향 구간만으로 채택·초과수익 입증을 하지 않는다. 요소 제거와 단순 기준선, 완전예지 상한을 함께 보고한다. 기준선보다 못한 결과도 유지한다.",
        scope="등록 시점 이후의 새 관측. 기존 생존 팔종목 과거 실험과 별개이며 새 기업이 미사용 검증 표본이라는 뜻은 아니다.",
        timestampProof="로컬 해시 고정 · 외부 시점 인증 없음",
    )
    protocol["protocolHash"] = digest(canonical(protocol))
    path.write_bytes(canonical(protocol))
    return protocol


def read(path=PATH):
    if not path.exists():
        return None
    p = json.loads(path.read_text())
    if (
        digest(canonical({k: v for k, v in p.items() if k != "protocolHash"}))
        != p["protocolHash"]
    ):
        raise ValueError("Forward protocol integrity mismatch")
    return p


def evaluate(protocol, snapshot):
    by_id = {c["id"]: c for c in snapshot["companies"]}
    results = []
    for market, contract in protocol["markets"].items():
        anchor = by_id.get(contract["calendarCompany"], {})
        calendar = sorted(
            p["date"]
            for p in anchor.get("prices", [])
            if contract["registrationDay"] < p["date"] <= snapshot["asOf"]
        )
        for horizon in protocol["horizons"]:
            row = dict(
                market=market,
                horizon=horizon,
                status="pending",
                observedSessions=len(calendar),
                requiredSessions=horizon + 1,
            )
            if len(calendar) <= horizon:
                results.append(row)
                continue
            entry, end = calendar[0], calendar[horizon]
            returns = {}
            missing = []
            sources = []
            for id in contract["members"]:
                c = by_id.get(id, {})
                prices = {
                    p["date"]: p["adjustedClose"]
                    for p in c.get("prices", [])
                    if p["date"] <= snapshot["asOf"]
                }
                if not prices.get(entry) or not prices.get(end):
                    missing.append(id)
                    continue
                returns[id] = prices[end] / prices[entry] - 1
                sources.extend(
                    s for s in c.get("sources", []) if s["provider"] == "Yahoo Finance"
                )
            row.update(entry=entry, end=end)
            if missing:
                row.update(
                    status="unresolved",
                    missing=missing,
                    reason="공통 진입·종료 가격 미확인; 대상 제외 또는 날짜 변경 없음",
                )
            else:
                policies = {}
                for name, selected in contract["selection"].items():
                    gross = (
                        sum(returns[id] for id in selected) / len(selected)
                        if selected
                        else 0
                    )
                    policies[name] = dict(
                        selected=selected,
                        gross=gross,
                        net=gross - 2 * protocol["oneWayCost"] if selected else 0,
                    )
                winner = max(returns, key=lambda id: (returns[id], id))
                oracle_invests = returns[winner] > 2 * protocol["oneWayCost"]
                policies["oracle_upper_bound"] = dict(
                    selected=[winner] if oracle_invests else [],
                    gross=returns[winner] if oracle_invests else 0,
                    net=(
                        returns[winner] - 2 * protocol["oneWayCost"]
                        if oracle_invests
                        else 0
                    ),
                )
                baseline = policies["equal_weight"]["net"]
                for p in policies.values():
                    p["differenceFromBaseline"] = p["net"] - baseline
                row.update(
                    status="observed",
                    policies=policies,
                    companyReturns=returns,
                    priceSources=list({s["sha256"]: s for s in sources}.values()),
                    independentAlphaValidation=False,
                )
            results.append(row)
    return dict(
        protocol=protocol,
        asOf=snapshot["asOf"],
        snapshotHash=snapshot["contentHash"],
        results=results,
    )
