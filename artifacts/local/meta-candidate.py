"""Staged, source-bound Meta operating cash model. Not wired into production."""
import json
from bs4 import BeautifulSoup
from equitylab.data import ROOT, canonical, digest, read_verified
from equitylab.xbrl import company_filing, instance_rows, select
from equitylab.narrative import load, extract
from equitylab.business_drivers import table_numbers

CURRENT = "0001628280-26-050705"
ANNUAL = "0001628280-26-003942"
CORPUS = "ea74ad806e812f9704af046f523961f340bfcba599d53be414771930f44ed610"
ANNUAL_ROOT = ROOT / "artifacts/local/meta-preparation"
ROLES = [
    ("OperatingIncomeLoss", "연결 영업이익", 1),
    ("NonoperatingIncomeExpense", "보고 영업외 손익", 1),
    ("IncomeTaxExpenseBenefit", "보고 법인세 비용·환급", -1),
    ("DepreciationDepletionAndAmortization", "감가상각·상각", 1),
    ("ShareBasedCompensation", "주식보상 되돌림", 1),
    ("deferredCash", "현금흐름표 이연법인세 조정", 1),
    ("UnrealizedGainLossOnMarketableAndNonmarketableEquityInvestments", "지분투자 평가손익 되돌림", -1),
    ("OtherNoncashIncomeExpense", "기타 비현금 조정", -1),
    ("IncreaseDecreaseInAccountsReceivable", "매출채권 현금 효과", -1),
    ("IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets", "선급·기타 유동자산 현금 효과", -1),
    ("IncreaseDecreaseInOtherOperatingAssets", "기타 영업자산 현금 효과", -1),
    ("IncreaseDecreaseInAccountsPayableTrade", "매입채무 현금 효과", 1),
    ("IncreaseDecreaseInAccruedLiabilities", "미지급 부채 현금 효과", 1),
    ("IncreaseDecreaseInOtherNoncurrentLiabilities", "기타 비유동부채 현금 효과", 1),
]
TAGS = dict(
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    operatingIncome="OperatingIncomeLoss",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    netIncome="NetIncomeLoss",
    tax="IncomeTaxExpenseBenefit",
    nonoperating="NonoperatingIncomeExpense",
    pretax="IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    depreciation="Depreciation",
    totalAmortization="DepreciationDepletionAndAmortization",
    sbc="ShareBasedCompensation",
    capex="PaymentsToAcquirePropertyPlantAndEquipment",
    lease="FinanceLeasePrincipalPayments",
)


def build(c, as_of):
    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(status="source_review_required", reason="Meta의 두 사업부·법인세·재투자 범위를 새 공시에서 다시 확인해야 합니다.")
    source, current = company_filing(c, as_of)
    annual_source = json.loads((ANNUAL_ROOT / f"data/sources/filing-{ANNUAL}-xbrl.manifest.json").read_text())
    annual_source["file"] = str((ANNUAL_ROOT / annual_source["file"]).relative_to(ROOT))
    annual_source["indexSource"]["file"] = str((ANNUAL_ROOT / annual_source["indexSource"]["file"]).relative_to(ROOT))
    if source["sha256"] != "6716e6b0f4978717e019177bc8275ac8ea17fea03b9db7c08a0c4818e7866ba8" or annual_source["sha256"] != "6ad129780910ee26dfa4edcc98d33b0929f2365f5e3d64d1fc120014924aebfe":
        raise ValueError("Meta reviewed cash source identity changed")
    if annual_source["accession"] != ANNUAL or annual_source["cik"] != c["cik"] or as_of < "2026-07-30":
        raise ValueError("Meta source identity or availability changed")
    annual = instance_rows(read_verified(ROOT / annual_source["file"], annual_source["sha256"]), c, annual_source, ANNUAL, "2026-01-29")
    annual_html = json.loads((ANNUAL_ROOT / "annual.manifest.json").read_text())
    if annual_html["sha256"] != "e1a24dbe2dad1ead7cce9a61debc398162543efe8ef4e02e32d890322e415597":
        raise ValueError("Meta reviewed annual narrative changed")
    annual_blob = read_verified(ROOT / annual_html["file"], annual_html["sha256"])
    for item in [annual_source, annual_source["indexSource"], annual_html]:
        item = dict(item, provider="SEC")
        item.setdefault("retrievedAt", annual_source["retrievedAt"])
        read_verified(ROOT / item["file"], item["sha256"])
        if item["file"] not in {s["file"] for s in c["sources"]}:
            c["sources"].append(item)
    f = c["financials"]
    if (f["start"],f["end"],f["priorStart"],f["priorEnd"]) != ("2026-01-01","2026-06-30","2025-01-01","2025-06-30"):
        raise ValueError("Meta reviewed cash periods changed")
    periods = [(1,annual,"2025-01-01","2025-12-31"),(1,current,f["start"],f["end"]),(-1,current,f["priorStart"],f["priorEnd"])]

    def exact(rows, tag, start, end, dimensions=()):
        if tag == "deferredCash":
            tag = "DeferredIncomeTaxesAndTaxCredits" if end == "2025-12-31" else "DeferredIncomeTaxExpenseBenefit"
        precision = "-7" if tag == "Depreciation" else "-6"
        fact = select([r for r in rows if r["decimals"] == precision], tag, start, end, dimensions, "USD")
        if fact is None:
            raise ValueError("Meta missing exact source fact: " + tag)
        return fact

    def combine(tag, dimensions=()):
        components = [dict(coefficient=sign,fact=exact(rows,tag,start,end,dimensions)) for sign,rows,start,end in periods]
        return dict(value=sum(p["coefficient"]*p["fact"]["value"] for p in components),components=components,sourceUrl=source["primaryUrl"],start="2025-07-01",end="2026-06-30",unit="USD",derived=True)

    facts = {k:combine(v) for k,v in TAGS.items()}
    v = lambda k: facts[k]["value"]
    checks=[]
    for sign,rows,start,end in periods:
        parts=[dict(label=label,tag=tag,value=coefficient*exact(rows,tag,start,end)["value"],fact=exact(rows,tag,start,end)) for tag,label,coefficient in ROLES]
        cfo=exact(rows,TAGS["cfo"],start,end)["value"]
        income=sum(p["value"] for p in parts[:3])-exact(rows,TAGS["netIncome"],start,end)["value"]
        residual=cfo-sum(p["value"] for p in parts)
        if income or residual:raise ValueError("Meta period cash or income reconciliation failed")
        checks.append(dict(start=start,end=end,reportedCfo=cfo,residual=residual,incomeResidual=income,parts=parts))
    parts=[dict(label=label,value=sign*combine(tag)["value"],fact=combine(tag)) for tag,label,sign in ROLES]
    if sum(p["value"] for p in parts)!=v("cfo"):raise ValueError("Meta trailing cash does not reconcile")

    segments=[]
    for member,label in [("FamilyOfAppsMember","Family of Apps · 광고·앱"),("RealityLabsMember","Reality Labs · 기기·콘텐츠")]:
        dims=[("StatementBusinessSegmentsAxis",member)]
        sales=combine(TAGS["revenue"],dims);profit=combine(TAGS["operatingIncome"],dims)
        observed=exact(current,TAGS["revenue"],f["start"],f["end"],dims)["value"]/exact(current,TAGS["revenue"],f["priorStart"],f["priorEnd"],dims)["value"]-1
        segments.append(dict(id=member,label=label,revenue=sales["value"],margin=profit["value"]/sales["value"],minMargin=-20 if member=="RealityLabsMember" else -.5,observedGrowth=observed,evidence=[p["fact"] for p in sales["components"]+profit["components"]]))
    for i,(_,rows,start,end) in enumerate(periods):
        for tag in [TAGS["revenue"],TAGS["operatingIncome"]]:
            total=sum(exact(rows,tag,start,end,[("StatementBusinessSegmentsAxis",s["id"])])["value"] for s in segments)
            if total != exact(rows,tag,start,end)["value"]:raise ValueError("Meta original-period segments do not reconcile")
    if sum(s["revenue"] for s in segments)!=v("revenue") or v("revenue")!=c["trailingYear"]["values"]["revenue"]["value"]:
        raise ValueError("Meta trailing segment revenue does not reconcile")

    # Interest detail is an untagged MD&A table. Check its periods and units,
    # preserving all columns before selecting the half-year values.
    corpus=load(c);index={p["ordinal"]:p for p in corpus["passages"]}
    current_html=read_verified(ROOT/index[524]["sourceFile"],index[524]["sourceHash"])
    interest=[]
    for blob,markers,count in [(annual_blob,["Interest income","Interest expense","2025 vs 2024","2024","2023","in millions, except percentages"],5),(current_html,["Interest income","Interest expense","Six Months Ended June 30","2026","2025","in millions, except percentages"],6)]:
        tables=[t for t in BeautifulSoup(blob,"html.parser").find_all("table") if all(m in t.get_text(" ",strip=True) for m in markers)]
        if len(tables)!=1:raise ValueError("Meta interest period table changed")
        interest.append(dict(income=table_numbers(tables[0],"Interest income",count),expense=table_numbers(tables[0],"Interest expense",count),tableHash=digest(str(tables[0]).encode())))
    annual_i,half_i=interest
    net_interest=(annual_i["income"][0]+annual_i["expense"][0]+half_i["income"][3]+half_i["expense"][3]-half_i["income"][4]-half_i["expense"][4])*1e6
    if net_interest != 558_000_000:raise ValueError("Meta reviewed interest amounts changed")
    facts["netInterest"]=dict(value=net_interest,sourceUrl=index[524]["sourceUrl"],tables=interest,scope="연간2025 + 당기반기2026 − 전년반기2025 · 이자수익+비용만, 투자·환율 손익 제외")
    if not all(t in index[381]["text"] for t in ["statutory rate of 21%","$8.03 billion","$15.93 billion"]) or "between 15-17%" not in index[539]["text"]:
        raise ValueError("Meta reviewed tax scope changed")
    revenue=v("revenue")
    working=sum(p["value"] for p in checks[1]["parts"] if p["tag"].startswith("IncreaseDecrease"))
    growth=exact(current,TAGS["revenue"],f["start"],f["end"])["value"]-exact(current,TAGS["revenue"],f["priorStart"],f["priorEnd"])["value"]
    if growth<=0:raise ValueError("Review Meta capital driver when sales contract")
    defaults=dict(segments=[dict(growthStart=0,growthEnd=0,marginEnd=s["margin"]) for s in segments],tax=.21,netInterest=net_interest/revenue,depreciation=v("depreciation")/revenue,workingCapital=-working/growth,capexStart=v("capex")/revenue,capexEnd=v("capex")/revenue,leaseStart=v("lease")/revenue,leaseEnd=v("lease")/revenue,discount=.11,terminal=.02)
    selected=[166,199,321,326,379,381,387,411,490,515,524,525,528,535,536,538,539,543,772]
    m=dict(status="research_workspace",version="meta-segment-cash-path-v1",sourcePeriod=["2025-07-01","2026-06-30"],accession=CURRENT,corpusHash=CORPUS,basisLabel="최근1년 두 사업부·현금 연결",growthLabel="최근 반기 전년 대비",currency="USD",displayScale=1e9,displayUnit="십억 달러",intro="Family of Apps의 수익과 Reality Labs의 손실을 별도로 유지하고, 설비 투자·리스·법인세 가정을 현금으로 연결합니다. 반기 세금 환급을 영구 세율로 사용하지 않습니다.",businessCaption="두 부문 매출·영업이익은 연간·당기 반기·전년 반기마다 연결 총액과 대사합니다. Reality Labs의 손실률을 잘라내지 않으며 광고 가격·노출의 분기 설명을 반기 전체 성장으로 바꾸지 않습니다.",capexLabel="설비 현금 취득",leaseLabel="금융리스 원금",passages=[index[i] for i in selected],segments=segments,facts=facts,defaults=defaults,security=c["valuation"]["security"],bridge=dict(parts=parts,reportedCfo=v("cfo"),residual=0,periods=checks,cashAfterInvestmentLeaseSbc=v("cfo")-v("capex")-v("lease")-v("sbc")),anchors=dict(workingCashEffect=working,revenueIncrease=growth,reportedTaxRate=v("tax")/v("pretax"),currentReportedTaxRate=exact(current,TAGS["tax"],f["start"],f["end"])["value"]/exact(current,TAGS["pretax"],f["start"],f["end"])["value"],taxAssumption=.21,interestTables=interest),anchorSummary="영업자금은 최근 반기 현금표의 영업자산·부채 조정 합계 / 동일 반기 매출 증가입니다. 감가상각은 설비만 되돌리고 무형자산 상각 등은 비용 대용으로 남깁니다. 순이자는 원문 표의 연간+반기−전년반기로 계산합니다.",rules=[
        "성장0%·현재 부문 마진·투입비율 유지는 연구 시작 가정이며 전망·목표가가 아닙니다.",
        "반기 법인세는 CAMT 전환 구제 이익80.3억달러를 포함합니다. 연간 현금표 이연세187.38억달러와 세금주석 비용187.55억달러를 섞지 않습니다.",
        "기본 세율21%는 공시의 미국 연방 법정세율을 이용한 연구자 가정입니다. 다국가 장기 현금세율 승인이 아니며 회사의 잔여2026분기 예상15–17%와 구분합니다.",
        "주식보상은 미래 현금에 되돌리지 않습니다. 투자 평가손익·환율손익·이연세 조정은 보고 현금 대사에 남기고 미래에는 순이자만 반복합니다.",
        "설비 감가상각은 1천만달러 단위 공시입니다. 무형자산·영업리스 비용은 대체 지출의 대용으로 유지하므로 실제 정상 재투자와 다를 수 있습니다.",
        "회사 표시 자본지출에는 금융리스 원금이 포함되지만 이 모델은 현금표 설비 취득과 원금을 따로 더합니다. 미개시 미래 리스 계약잔액을 현재 현금 지출로 차감하지 않습니다.",
        "여러 주식 종류와 권리 배분이 미확정이므로 현금이 양수여도 주당 가치와 현재가격 요구액은 보류합니다.",
    ],remaining=["AI 인프라 유지·확장 투자와 미개시 리스 의무의 미래 지출 경로","Reality Labs 제품 구성·비용의 회수와 사업별 현금 귀속","법인세·세무불확실성의 현금 시점과 정상 영업자금","투자자산·초과현금과 복수 주식 종류의 경제적 권리 배분"])
    from equitylab.operating_model import calculate
    m["initial"]=calculate(m,defaults)
    m["evidenceHash"]=digest(canonical(m))
    return m


if __name__ == "__main__":
    from equitylab.pipeline import load_latest
    snapshot=load_latest();c=next(c for c in snapshot["companies"] if c["id"]=="META")
    m=build(c,snapshot["asOf"])
    (ROOT/"artifacts/local/meta-model-candidate.json").write_bytes(canonical(m))
    print("Candidate only",m["bridge"]["reportedCfo"],m["facts"]["lease"]["value"],m["initial"]["years"][0]["cash"])
