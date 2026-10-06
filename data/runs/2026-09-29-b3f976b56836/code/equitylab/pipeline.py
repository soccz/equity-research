from __future__ import annotations
from datetime import date, datetime, timezone
import json
import os
from .data import (
    ROOT,
    UNIVERSE,
    canonical,
    digest,
    sec_facts,
    dart_facts,
    prices,
    statement,
    ensure_storage,
    read_verified,
)
from .research import price_summary, run_experiment
from . import ledger
from .company_analysis import build as company_analysis, investment_scope, peers


def financial_metrics(s: dict) -> dict:
    def values(key):
        return {m: f["value"] if f else None for m, f in s[key].items()}

    c, p = values("current"), values("previous")

    def ratio(a, b):
        return a / b if a is not None and b is not None and b > 0 else None

    surplus = c["cfo"] - c["capex"]
    previous_surplus = (
        p["cfo"] - p["capex"]
        if p["cfo"] is not None and p["capex"] is not None
        else None
    )
    investment_comparable = bool(s["previous"].get("capex")) and investment_scope(
        s["current"]["capex"]
    ) == investment_scope(s["previous"]["capex"])
    if not investment_comparable:
        previous_surplus = None
    margin, previous_margin = ratio(surplus, c["revenue"]), ratio(
        previous_surplus, p["revenue"]
    )
    growth = (
        c["revenue"] / p["revenue"] - 1 if p["revenue"] and p["revenue"] > 0 else None
    )
    return dict(
        investmentComparable=investment_comparable,
        revenueGrowth=growth,
        operatingMargin=ratio(c["operating_income"], c["revenue"]),
        cashConversion=ratio(c["cfo"], c["net_income"]),
        cashMargin=margin,
        priorCashMargin=previous_margin,
        cashMarginChange=(
            margin - previous_margin
            if margin is not None and previous_margin is not None
            else None
        ),
        cashAfterInvestment=surplus,
        capexIntensity=ratio(c["capex"], c["revenue"]),
        cfoMargin=ratio(c["cfo"], c["revenue"]),
        netMargin=ratio(c["net_income"], c["revenue"]),
    )


def assessment(c: dict, as_of: str) -> dict:
    m, p, f = c["metrics"], c["priceSummary"], c["financials"]
    gates = [
        dict(
            id="growth",
            label="전년 동기 매출 증가",
            passed=None if m["revenueGrowth"] is None else m["revenueGrowth"] > 0,
        ),
        dict(
            id="surplus",
            label="영업현금−공시 투자자산 취득 > 0",
            passed=m["cashAfterInvestment"] > 0,
        ),
        dict(
            id="margin",
            label="동 현금잉여 마진 전년 동기 개선",
            passed=(
                None if m["cashMarginChange"] is None else m["cashMarginChange"] > 0
            ),
        ),
    ]
    issues = []
    if (date.fromisoformat(as_of) - date.fromisoformat(p["lastDate"])).days > 7:
        issues.append("가격이 기준일보다 7일 이상 오래됨")
    if (date.fromisoformat(as_of) - date.fromisoformat(f["end"])).days > 200:
        issues.append("최근 재무기간 종료 후 200일 초과")
    if (date.fromisoformat(as_of) - date.fromisoformat(f["filedAt"])).days > 120:
        issues.append("확보한 공시 제출 후 120일 초과 · 최신 정기공시 추가 확인 필요")
    if not m.get("investmentComparable", True):
        issues.append("전년 동기와 투자지출 분류가 달라 마진 변화 비교 보류")
    if c["investmentScope"] == "기타 분류 유형자산 취득":
        issues.append("기타 분류 자산 취득만 연결됨 · 투자지출 전체 범위 확인 필요")
    if any(m[k] is None for k in ["revenueGrowth", "cashMarginChange"]):
        issues.append("비교 기간 미확보")
    candidate = all(g["passed"] for g in gates) and not issues
    risks = []
    if m["cashConversion"] is not None and m["cashConversion"] < 0.8:
        risks.append("순이익 대비 영업현금 유입이 낮아 비현금 손익·회수 시차 점검 필요")
    if p["volatility21"] > 0.5:
        risks.append("최근 21거래일 가격 변동성이 연율 50% 초과")
    if m["cashMarginChange"] is not None and m["cashMarginChange"] < 0:
        risks.append("설비 취득 후 현금잉여 마진이 전년 동기보다 감소")
    if m["capexIntensity"] > 0.2:
        risks.append("공시 투자자산 취득 현금이 매출의 20% 초과")
    return dict(
        priority=(
            "심층 조사 후보" if candidate else "자료 점검" if issues else "조건 관찰"
        ),
        gates=gates,
        issues=issues,
        risks=risks,
        businessView="현금·성장 조건 동반 충족" if candidate else "기업별 조건 재검토",
        investmentView="가격 판단 보류",
        valuationStatus="기업별 정상 현금흐름·전 증권가치·부채 조정 미검증",
        reason="세 조건은 조사 대상을 좁히는 공개 규칙이다. 가중 종합점수나 검증된 초과수익 확률이 아니다.",
        reviewStatus="원문 수치·기간 자동 검증 / 기업 해석 독립 검토 전",
    )


def run(as_of: str, online=False) -> dict:
    if date.fromisoformat(as_of) >= datetime.now(timezone.utc).date():
        raise ValueError("Use a completed date strictly before today's UTC date")
    ensure_storage(ROOT)
    cohort_path = ROOT / "data/research-cohort.json"
    cohort = (
        json.loads(cohort_path.read_text())
        if cohort_path.exists()
        else dict(version="development-eight-v1", members=[c["id"] for c in UNIVERSE])
    )
    identity_path = ROOT / "data/coverage-identities.json"
    identity = json.loads(identity_path.read_text()) if identity_path.exists() else None
    registry_sources = identity["sources"] if identity else []
    retrieval_path = ROOT / "data/coverage-retrieval.json"
    retrieval = (
        json.loads(retrieval_path.read_text())
        if retrieval_path.exists()
        else {"results": []}
    )
    for src in registry_sources:
        read_verified(ROOT / src["file"], src["sha256"])
    companies, failures, histories = [], [], {}
    for spec in UNIVERSE:
        print(f"Collect {spec['id']}", flush=True)
        try:
            if spec["market"] == "KR" and online and os.environ.get("DART_API_KEY"):
                from .dart import sync

                sync(spec, as_of)
            facts, sources = (
                sec_facts(spec, online) if spec["market"] == "US" else dart_facts(spec)
            )
            histories[spec["id"]] = facts
            financials = statement(facts, as_of)
            history, price_source = prices(spec, as_of, online)
            c = dict(
                **spec,
                status="ready",
                investmentScope=investment_scope(financials["current"]["capex"]),
                financials=financials,
                metrics=financial_metrics(financials),
                prices=history,
                priceSummary=price_summary(history),
                sources=[*sources, price_source],
            )
            from .dossier import build as build_dossier

            c["dossier"] = build_dossier(c, as_of)
            c["analysis"] = company_analysis(c, facts, as_of)
            c["analysis"]["sourceGaps"] = next(
                (
                    r.get("historyIssues", [])
                    for r in retrieval["results"]
                    if r["ticker"] == c["id"]
                ),
                [],
            )
            c["assessment"] = assessment(c, as_of)
            companies.append(c)
        except Exception as exc:
            failures.append(dict(id=spec["id"], error=f"{type(exc).__name__}: {exc}"))
            companies.append(dict(**spec, status="unavailable", error=str(exc)))
    for c in companies:
        if c["status"] == "ready":
            c["analysis"]["peers"] = peers(c, companies)
    research_members = [c for c in companies if c["id"] in cohort["members"]]
    snapshot = dict(
        schemaVersion=1,
        asOf=as_of,
        generatedAt=datetime.now(timezone.utc).isoformat(),
        universeVersion="coverage-40-v1",
        universeRule=(
            identity["selectionRule"]
            if identity
            else "고정 개발 대상군; 시장 대표 표본 아님"
        ),
        registrySources=registry_sources,
        researchCohort=cohort,
        companies=companies,
        failures=failures,
        experiments=[
            run_experiment(research_members, market) for market in ["US", "KR"]
        ],
        boundaries=[
            "현재 재무 선별 규칙과 가격 기반 과거 실험은 별도다. 현재 재무를 과거에 소급하지 않는다.",
            "영업현금−공시 투자자산 취득은 FCFF나 기업 발표 조정 FCF가 아니다. 유형자산·유형무형 통합·기타 분류의 정의를 기업별로 표시한다. 인수·리스 및 회계 분류 차이가 남는다.",
            "연결 기준·현지 통화·동일 기업의 전년 동기를 사용한다. 시장 간 회계기간과 사업 구성은 다를 수 있다.",
            "기업별 적정 가격과 투자 의견의 독립 검토는 미완료다. 조사 우선순위를 매수 추천으로 바꾸지 않는다.",
            "공시 제출일·가격 관측일·원문 수집일을 각각 보존한다. 화면의 기준일은 분석에 사용한 자료 시점을 의미한다.",
        ],
    )
    snapshot["engineFiles"] = {
        str(p.relative_to(ROOT)): digest(p.read_bytes())
        for p in sorted((ROOT / "equitylab").glob("*.py"))
    }
    from .fundamental import evaluate

    snapshot["fundamentalExperiments"] = [
        evaluate(companies, histories, e) for e in snapshot["experiments"]
    ]
    snapshot["renderFiles"] = {
        str(p.relative_to(ROOT)): digest(p.read_bytes())
        for p in sorted(
            [*(ROOT / "app").glob("*"), *(ROOT / "prototype").glob("styles.css")]
        )
        if p.suffix in (".html", ".css", ".js") and p.name != "snapshot.js"
    }
    snapshot["universeHash"] = digest(canonical(UNIVERSE))
    input_files = [ROOT / "data/universe.json", ROOT / "data/dart-imports.json"]
    input_files.extend(
        ROOT / ("data/" + name + ".json")
        for name in (
            "research-cohort",
            "coverage-plan",
            "coverage-identities",
            "coverage-retrieval",
        )
    )
    input_files.extend(sorted((ROOT / "data/sources").glob("filing-*.manifest.json")))
    for c in UNIVERSE:
        input_files.append(ROOT / f"data/sources/price-{c['id']}.manifest.json")
        if c["market"] == "US":
            input_files.append(ROOT / f"data/sources/sec-{c['id']}.manifest.json")
        else:
            input_files.append(ROOT / f"data/sources/dart-sync-{c['id']}.json")
    snapshot["inputFiles"] = {
        str(p.relative_to(ROOT)): digest(p.read_bytes())
        for p in input_files
        if p.exists()
    }
    snapshot["koreanRetrieval"] = (
        "opendart_api" if online and os.environ.get("DART_API_KEY") else "archived_xbrl"
    )
    snapshot["researchProtocol"] = dict(
        version="price-exploration-v1",
        registeredBeforeResults=False,
        horizon=21,
        entryLag=1,
        momentumLookback=63,
        varianceLookbacks=[21, 126],
        selectionCount=2,
        benchmark="market-specific current-cohort equal weight",
        financialSignalBacktest=True,
    )
    snapshot["contentHash"] = digest(canonical(snapshot))
    folder = ROOT / "data/runs" / f"{as_of}-{snapshot['contentHash'][:12]}"
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "snapshot.json").write_bytes(canonical(snapshot))
    for relative in {**snapshot["engineFiles"], **snapshot["renderFiles"]}:
        destination = folder / "code" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    for relative in snapshot["inputFiles"]:
        destination = folder / "inputs" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    # A failed refresh is evidence, not a replacement for the last complete analysis.
    if not failures:
        pointer_temp = ROOT / "data/latest.json.tmp"
        pointer_temp.write_text(
            json.dumps(
                {
                    "snapshot": str((folder / "snapshot.json").relative_to(ROOT)),
                    "contentHash": snapshot["contentHash"],
                },
                indent=2,
            )
            + "\n"
        )
        export(snapshot)
        os.replace(pointer_temp, ROOT / "data/latest.json")
    print(
        f"Snapshot: {len(companies)-len(failures)}/{len(companies)} companies; {folder.name}",
        flush=True,
    )
    return snapshot


def load_latest():
    pointer = json.loads((ROOT / "data/latest.json").read_text())
    obj = json.loads((ROOT / pointer["snapshot"]).read_text())
    if (
        digest(canonical({k: v for k, v in obj.items() if k != "contentHash"}))
        != pointer["contentHash"]
        or obj["contentHash"] != pointer["contentHash"]
    ):
        raise ValueError("Snapshot integrity failure")
    return obj


def export(snapshot):
    from .figures import render_figures

    render_figures(snapshot)
    records = ledger.read(ROOT / "data/ledger/conditions.jsonl")
    decorated = []
    for row in records:
        if row["type"] != "registration":
            continue
        c = next(
            (
                c
                for c in snapshot["companies"]
                if c["id"] == row["company"] and c["status"] == "ready"
            ),
            None,
        )
        first_observation = next(
            (
                r
                for r in records
                if r["type"] == "observation"
                and r.get("registrationHash") == row["hash"]
            ),
            None,
        )
        decorated.append(
            dict(
                registration=row,
                observation=first_observation
                or (
                    ledger.evaluate(row, c)
                    if c
                    else dict(
                        status="unresolved",
                        reason="기업 자료 미확인",
                        predictionCorrect=None,
                    )
                ),
                observationPersisted=first_observation is not None,
            )
        )
    from .local_ai import read_reviews

    payload = dict(
        snapshot=snapshot,
        ledger=decorated,
        ledgerEvents=records,
        localReviews=read_reviews(snapshot),
    )
    temp = ROOT / "app/snapshot.js.tmp"
    temp.write_text(
        "window.EQUITY_SNAPSHOT = "
        + json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
        + ";\n"
    )
    os.replace(temp, ROOT / "app/snapshot.js")


def register():
    snapshot = load_latest()
    for c in snapshot["companies"]:
        if c["status"] != "ready":
            continue
        event = dict(
            eventId=f"cash-margin-v1:{c['id']}:{c['financials']['end']}",
            type="registration",
            company=c["id"],
            periodEnd=c["financials"]["end"],
            definition=f"다음 정기공시에서 동일 길이 전년 동기 대비 (영업현금−{c['investmentScope']})/매출이 증가",
            metric="cashMarginChange",
            operator=">",
            threshold=0,
            expected=None,
            investmentScope=c["investmentScope"],
            baseline="같은 길이 전년 동기 마진 유지",
            snapshotHash=snapshot["contentHash"],
            cutoff=snapshot["asOf"],
            predictionStatus="방향 예측 미등록 · 조건만 추적",
            timestampProof="로컬 해시 체인 · 외부 시점 인증 없음",
        )
        # A refresh may change the snapshot hash; an existing condition must remain exactly as recorded.
        old = ledger.read(ROOT / "data/ledger/conditions.jsonl")
        if not any(r["eventId"] == event["eventId"] for r in old):
            ledger.append(ROOT / "data/ledger/conditions.jsonl", event)
    export(snapshot)


def observe():
    snapshot = load_latest()
    records = ledger.read(ROOT / "data/ledger/conditions.jsonl")
    for row in records:
        if row["type"] != "registration":
            continue
        if any(
            r["type"] == "observation" and r.get("registrationHash") == row["hash"]
            for r in records
        ):
            continue
        company = next(
            (
                c
                for c in snapshot["companies"]
                if c["id"] == row["company"] and c["status"] == "ready"
            ),
            None,
        )
        if not company:
            continue
        result = ledger.evaluate(row, company)
        if result["status"] in ("met", "not_met"):
            ledger.append(
                ROOT / "data/ledger/conditions.jsonl",
                dict(
                    eventId=f"observation:{row['hash']}:{result['periodEnd']}:{result['filedAt']}",
                    type="observation",
                    registrationHash=row["hash"],
                    snapshotHash=snapshot["contentHash"],
                    **result,
                ),
            )
    export(snapshot)
