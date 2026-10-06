"""Local-model selection of explicit research designs, without generated causes."""

from datetime import datetime, timezone
import json
from .data import ROOT, canonical, digest
from .coverage_reasoning import observations, evidence

VERSION = "research-question-selection-v1"
SYSTEM = "You prioritize research questions using the supplied filing observations. All causes remain unknown. Return only the selected question IDs. Do not answer the research questions or generate company facts."
TASK = "Choose two different applicable research designs in priority order for this company. Focus on the unresolved issue with the greatest potential to change the cash or price interpretation. Use only IDs in candidates. Your selection is exploratory, not an investment recommendation."
CATALOG = {
    "cash_conversion": dict(
        title="이익의 변화와 수금·지급 시차를 구별하기",
        alternatives=[
            "이익 창출력의 변화가 현금 변화에 기여했을 가능성",
            "운전자본·세금 등의 수금·지급 시차가 기여했을 가능성",
        ],
        evidenceNeeded="순이익에서 영업현금으로 이어지는 조정표, 채권·재고·매입채무와 세금 지급의 변동을 함께 확보한다.",
        discriminator="운전자본 효과를 제외해도 이익과 현금 변화가 함께 지속되면 첫 설명을, 채권·재고·채무의 일시적 변동이 되돌아오며 현금 변화도 반전되면 두 번째 설명을 더 검토한다.",
        limitation="항등식 분해는 인과 증명이 아니다. 투자자산 취득·배당·차입 원금은 영업현금의 원인 항목으로 넣지 않는다.",
        keys=["revenue", "cfo"],
    ),
    "investment_cycle": dict(
        title="용량 확장과 설비 교체의 투자 부담을 구별하기",
        alternatives=[
            "생산능력·서비스 용량의 확장을 위한 지출일 가능성",
            "기존 설비의 유지·교체 일정이 집중된 지출일 가능성",
        ],
        evidenceNeeded="증설·교체별 투자 목적, 집행·가동 시점, 실제 생산능력·가동률과 해당 지출 범위를 확보한다.",
        discriminator="새 용량과 그 가동에 연결된 지출은 확장 설명을, 기존 용량을 유지하며 노후 설비를 교체한 지출은 유지·교체 설명을 각각 뒷받침할 수 있다. 지출 규모만으로 목적을 결정하지 않는다.",
        limitation="기간 중 취득 지출과 기말 자산 잔액을 구분한다. 취득 지출의 변화로 영업현금의 원인을 설명하지 않는다.",
        keys=["capex"],
    ),
    "revenue_mix": dict(
        title="매출의 가격·물량·제품 구성 효과를 나누기",
        alternatives=[
            "판매량·이용량의 변화가 매출에 기여했을 가능성",
            "가격·제품 구성·환율의 변화가 기여했을 가능성",
        ],
        evidenceNeeded="같은 범위의 제품별 판매량·이용량·평균 단가, 제품 구성과 환율 영향을 확보한다.",
        discriminator="가격과 환율을 고정해도 물량 변화가 남으면 첫 설명을, 물량이 비슷한데 단가·구성이 변하면 두 번째 설명을 더 검토한다. 전체 매출만으로 두 설명을 구별할 수 없다.",
        limitation="보고된 매출 변화를 신규 고객·시장 점유율 변화로 바꾸어 말하지 않는다.",
        keys=["revenue"],
    ),
    "segment_reconciliation": dict(
        title="사업부 성과와 연결 조정의 영향을 구별하기",
        alternatives=[
            "보고 사업부의 매출·수익성 변화가 연결 성과에 기여했을 가능성",
            "본사 비용·내부거래·배분 기준의 변화가 기여했을 가능성",
        ],
        evidenceNeeded="같은 구성의 전년 사업부 표와 연결 대사, 본사 비용·내부거래 조정, 배분 기준 변경을 확보한다.",
        discriminator="같은 기준으로 연결한 부문 변화가 연결 실적 차이를 설명하는지 대사한다. 남는 차이는 미확인 잔차로 두고 별도 조정 근거를 요구한다.",
        limitation="미대사 잔차를 주식보상·제거 거래 등 특정 원인으로 이름 붙이지 않는다.",
        keys=["revenue", "cfo"],
    ),
    "financial_scope": dict(
        title="제조 활동과 금융 자회사의 자금 요구를 분리하기",
        alternatives=[
            "제조·서비스 영업의 현금 창출 변화일 가능성",
            "금융채권의 취급·회수와 금융부문 자본요구 변화일 가능성",
        ],
        evidenceNeeded="제조·금융별 현금흐름과 자금조달, 금융채권 변동·손실·자본요구 및 연결 조정을 확보한다.",
        discriminator="금융채권 취급 증가에 대응한 현금 사용과 제조 영업의 현금 사용을 분리해 각각 비교한다. 연결 현금만으로 제조 경쟁력 악화를 판단하지 않는다.",
        limitation="금융 자회사 현금을 일반 제조 기업의 배분 가능 현금과 같은 방식으로 평가하지 않는다.",
        keys=["cfo"],
    ),
    "price_conditions": dict(
        title="현재 가격을 설명할 현금 지속 조건을 찾기",
        alternatives=[
            "과거 현금·재투자 비율이 유지되는 경우",
            "성장·재투자·보상 부담의 가정을 바꾸어야 하는 경우",
        ],
        evidenceNeeded="가정별 요구 현금·성장률과 실제 사업 투자 계획, 현금 전환, 희석·리스·비지배 배분 부담을 대조한다.",
        discriminator="같은 할인 가정에서 실제 공시가 요구 현금에 접근하는지 관측한다. 필요한 성장이나 낮은 부담의 근거가 약해지면 해당 가격 시나리오를 재검토한다.",
        limitation="가격 역산은 시장의 실제 기대를 관측한 값이나 목표가가 아니다. 과거 중앙값을 정상 현금 전망으로 확정하지 않는다.",
        keys=["revenue", "cfo", "capex"],
    ),
    "security_rights": dict(
        title="주당 계산 전 주식 종류와 배분 범위를 확인하기",
        alternatives=[
            "확인된 권리·주식수로 보통주 배분이 가능한 경우",
            "추가 증권 권리·수량 또는 금융 범위를 먼저 확인해야 하는 경우",
        ],
        evidenceNeeded="종류별 경제적 권리, 같은 기준일 발행·자기주식·유통 수량과 금융·비지배 배분 범위를 확인한다.",
        discriminator="같은 접수와 범위에서 수량을 대사하고 증권별 권리를 연결한 뒤에만 주당 계산을 재개한다. 충돌·미확인 상태를 낮은 가치의 증거로 사용하지 않는다.",
        limitation="자료 미확인은 회피 의견이나 영의 가치가 아니다.",
        keys=["cfo"],
    ),
    "peer_tradeoff": dict(
        title="동종 기업의 현금 구조 차이가 반복되는지 확인하기",
        alternatives=[
            "사업 구성·수익성 차이가 반복적으로 나타나는 경우",
            "기간·투자 주기·회계 분류 차이가 비교를 좌우하는 경우",
        ],
        evidenceNeeded="비교 기업의 같은 최근 일 년 기간·투자자산 범위·회계 분류와 사업 구성을 맞추어 확보한다.",
        discriminator="정의와 기간을 맞춘 뒤에도 현금 구조 차이가 여러 기간에 지속되는지 확인한다. 범위가 다르면 우열 비교를 보류한다.",
        limitation="서로 다른 통화의 금액을 합치거나 높은 현금 비율을 곧바로 투자 우위로 해석하지 않는다.",
        keys=["cfo", "capex"],
    ),
}


def protocol_hash():
    return digest(
        canonical(dict(version=VERSION, system=SYSTEM, task=TASK, catalog=CATALOG))
    )


def packet(c):
    ids = ["cash_conversion", "investment_cycle", "revenue_mix"]
    if (c.get("business") or {}).get("status") == "ready":
        ids.append("segment_reconciliation")
    if c["id"] in ("GM", "F", "CAT", "005380"):
        ids.append("financial_scope")
    security = c.get("valuation", {}).get("security", {})
    ids.append(
        "price_conditions"
        if security.get("status") == "available"
        else "security_rights"
    )
    if c.get("researchCase", {}).get("peers"):
        ids.append("peer_tradeoff")
    return dict(
        company=c["id"],
        name=c["name"],
        period=[c["financials"]["start"], c["financials"]["end"]],
        currency=c["currency"],
        sourceIdentity=dict(
            filedAt=c["financials"]["filedAt"],
            accession=c["financials"]["current"]["cfo"]["accession"],
            standard=c["financials"]["standard"],
            factsHash=digest(canonical(evidence(c))),
        ),
        observations=observations(c),
        segmentChanges=[
            {
                k: s[k]
                for k in ("id", "label", "revenueGrowth", "margin", "marginChange")
            }
            for s in c.get("researchCase", {}).get("segments", [])
        ],
        priceState=c.get("researchCase", {}).get("pricing", {}),
        securityIssues=security.get("issues", []),
        peerDifferences=[
            {
                k: peer[k]
                for k in (
                    "id",
                    "investmentComparable",
                    "differences",
                    "cautions",
                    "evidenceHash",
                )
            }
            for peer in c.get("researchCase", {}).get("peers", [])
        ],
        candidates=[dict(id=i, **CATALOG[i]) for i in ids],
    )


def prompt_packet(p):
    return dict(
        p,
        candidates=[
            {k: c[k] for k in ("id", "title", "alternatives", "evidenceNeeded")}
            for c in p["candidates"]
        ],
    )


def schema(p):
    return dict(
        type="object",
        additionalProperties=False,
        required=["primary", "secondary"],
        properties={
            key: dict(type="string", enum=[c["id"] for c in p["candidates"]])
            for key in ("primary", "secondary")
        },
    )


def validate(choice, p):
    allowed = {c["id"] for c in p["candidates"]}
    if not isinstance(choice, dict) or set(choice) != {"primary", "secondary"}:
        raise ValueError("Exactly two question IDs are required")
    if (
        any(not isinstance(v, str) or v not in allowed for v in choice.values())
        or len(set(choice.values())) != 2
    ):
        raise ValueError("Question IDs must be distinct and applicable to this input")
    return choice


def select(c, snapshot_hash, client, model):
    p = packet(c)
    installed = client.model(model)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "data/question-selections" / c["id"] / stamp
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "input.json").write_bytes(canonical(p))
    r = dict(
        company=c["id"],
        createdAt=datetime.now(timezone.utc).isoformat(),
        snapshotHash=snapshot_hash,
        protocolVersion=VERSION,
        protocolHash=protocol_hash(),
        inputHash=digest(canonical(p)),
        model=model,
        modelDigest=installed["digest"],
        inferenceConfig=client.inference_config,
        status="failed",
        externalAIUsed=False,
        independentFinancialApproval=False,
        scope="모델이 명시된 연구 설계 중 조사 순서를 고른 기록. 원인·기업 사실을 생성하지 않으며 선택의 투자 성과·우선순위 타당성은 미검증.",
    )
    try:
        choice, timing, _ = client.generate(
            model,
            [
                dict(role="system", content=SYSTEM),
                dict(
                    role="user",
                    content=TASK
                    + "\n"
                    + json.dumps(prompt_packet(p), ensure_ascii=False),
                ),
            ],
            schema(p),
            archive=folder / "selection-raw.json",
        )
        validate(choice, p)
        r.update(
            status="selected",
            choice=choice,
            runtime=timing,
            loadedModels=client.call("ps").get("models", []),
        )
    except Exception as exc:
        r["error"] = type(exc).__name__ + ": " + str(exc)[:400]
    r["files"] = {
        str(f.relative_to(ROOT)): digest(f.read_bytes())
        for f in sorted(folder.iterdir())
        if f.is_file()
    }
    r["recordHash"] = digest(canonical(r))
    path = folder / "record.json"
    path.write_bytes(canonical(r))
    pointer = folder.parent / "latest.json"
    temp = pointer.with_suffix(".tmp")
    temp.write_bytes(
        canonical(dict(file=str(path.relative_to(ROOT)), hash=r["recordHash"]))
    )
    temp.replace(pointer)
    return r


def read(snapshot):
    results = {}
    for c in snapshot["companies"]:
        if c["status"] != "ready":
            continue
        path = ROOT / "data/question-selections" / c["id"] / "latest.json"
        if not path.is_file():
            continue
        pointer = json.loads(path.read_text())
        record_path = (ROOT / pointer["file"]).resolve()
        if not record_path.is_relative_to(
            (ROOT / "data/question-selections").resolve()
        ):
            raise ValueError("Question record outside its archive")
        r = json.loads(record_path.read_text())
        if (
            digest(canonical({k: v for k, v in r.items() if k != "recordHash"}))
            != pointer["hash"]
            or r["recordHash"] != pointer["hash"]
        ):
            raise ValueError("Question selection record integrity failure")
        for relative, sha in r["files"].items():
            f = (ROOT / relative).resolve()
            if (
                not f.is_relative_to(record_path.parent)
                or digest(f.read_bytes()) != sha
            ):
                raise ValueError("Question input or response archive changed")
        p = packet(c)
        if (
            r["inputHash"] != digest(canonical(p))
            or r["protocolHash"] != protocol_hash()
        ):
            results[c["id"]] = dict(
                status="stale",
                reason="입력·연구 설계가 바뀌어 질문 선택을 갱신해야 합니다.",
            )
            continue
        if r["status"] == "selected":
            validate(r["choice"], p)
            response = json.loads(
                (record_path.parent / "selection-raw.json").read_text()
            )
            request = json.loads(
                (record_path.parent / "selection-request.json").read_text()
            )
            if json.loads(response["message"]["content"]) != r["choice"]:
                raise ValueError(
                    "Question choices differ from the model's exact response"
                )
            expected_messages = [
                dict(role="system", content=SYSTEM),
                dict(
                    role="user",
                    content=TASK
                    + "\n"
                    + json.dumps(prompt_packet(p), ensure_ascii=False),
                ),
            ]
            if (
                request["messages"] != expected_messages
                or request["format"] != schema(p)
                or request["model"] != r["model"]
                or request["think"] != r["inferenceConfig"]["think"]
                or request["options"] != r["inferenceConfig"]["options"]
            ):
                raise ValueError(
                    "Question request differs from its recorded input or inference settings"
                )
            r["questions"] = [
                dict(id=r["choice"][k], **CATALOG[r["choice"][k]])
                for k in ("primary", "secondary")
            ]
            r["evidence"] = evidence(c)
            r["observations"] = observations(c)
        results[c["id"]] = r
    return results
