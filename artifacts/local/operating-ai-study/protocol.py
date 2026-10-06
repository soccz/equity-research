"""Staged protocol: issuer cash assumptions and actual source paragraphs."""
import copy,json
from pathlib import Path
from equitylab import coverage_reasoning as base
from equitylab.data import canonical,digest
from equitylab.narrative import load
VERSION='operating-assumptions-pilot-v1'
SYSTEM=base.SYSTEM+'\nresearchAssumptions와calculatedScenario는 연구자가 정한 미래 가정의 계산이며 관측 실적·시장 기대·실제 확률이 아니다. 단위·기간·시장별 매출과 연결 이익을 구분한다. priceHoldReason이 있으면 양수 현금으로 주당 보류를 해제할 수 없다. suppliedOriginals는 선택된 원문이며 전체 공시를 심사한 것이 아니다. 연구자가 정한 비용·금리·투자 가정을 공시된 미래 실적으로 바꾸지 않는다.'
DRAFT_TASK='''Review one economically important assumption in researchAssumptions using suppliedOriginals, reportedCash and knownLimits. Write four complete Korean sentences; use financial item names, no numbers, prices or probabilities.
hypothesis: propose one possible business mechanism under which the selected assumption might remain reasonable. End with '가능성이 있다' or '일 수 있다'. This is a hypothesis, never a finding.
alternative: a distinct possible mechanism that would weaken that same assumption, with conditional wording. Do not invent a known cause.
distinguish: specify additional source evidence to collect and contrasting observations favoring each explanation. Merely comparing aggregate growth ratios cannot establish a cause.
missing: identify a relevant knownLimits item that cannot be established from the supplied input. Do not claim a supplied item is missing.
Tie the question to the actual business, accounting scope and assumption; do not repeat generic statements about collecting more data. Do not lift a scope warning as a causal explanation. Return exactly hypothesis, alternative, distinguish and missing as JSON strings.'''
REVIEW_TASK=base.REVIEW_TASK+'\n미래 연구 가정과 calculatedScenario를 이미 관측된 실적 또는 시장 요구의 확정으로 바꾸면 거부한다. 공시된 시장별 매출에서 독립 이익을 만들어도 거부한다.'
DRAFT_SCHEMA=copy.deepcopy(base.DRAFT_SCHEMA)
review_items=base.review_items
review_schema=base.review_schema
validate_assessments=base.validate_assessments
accepted=base.accepted
model_accepted=base.model_accepted
all_accepted=base.all_accepted
style_findings=base.style_findings

SELECTIONS={
 'TXN':['107be56513fff2ffbd06','20e572529ffe41399b6e','89dcf81f1470c20000c3'],
 'ADI':['33137871febd3e1f1625','745a45a28f2897c358ba','2b031a03c28385e94c60'],
 'ADBE':['52c9bf1b9b49257ad1ce','8db6695981f504610b20'],
 'CRM':['607f80f7312039c25400','d23dc3e2c9f3f15e7832','8017f3e76fadfb1f13ff'],
}

def packet(c):
 m=c.get('operatingModel') or {}
 if m.get('status')!='research_workspace' or c['id'] not in SELECTIONS:raise ValueError('Pilot needs a reviewed issuer-specific model and source selection')
 if digest(canonical({k:v for k,v in m.items() if k!='evidenceHash'}))!=m['evidenceHash']:raise ValueError('Issuer model content/hash changed')
 if m['accession']!=c['narrative']['accession'] or m['corpusHash']!=c['narrative']['evidenceHash']:raise ValueError('Current source/model binding changed')
 index={x['id']:x for x in load(c)['passages']}
 sources=[index[i] for i in SELECTIONS[c['id']]]
 if sum(len(x['text']) for x in sources)>6000:raise ValueError('Review a bounded source set before inference')
 a=copy.deepcopy(m['defaults']);scenario=m['initial']
 from equitylab.operating_model import calculate
 if canonical(calculate(m,a))!=canonical(scenario):raise ValueError('Stored scenario differs from selected assumptions')
 return dict(version=VERSION,company=c['name'],ticker=c['id'],currency=c['currency'],modelVersion=m['version'],modelHash=m['evidenceHash'],corpusHash=m['corpusHash'],sourcePeriod=m['sourcePeriod'],profitBasis=m.get('marginLabel','영업이익률'),businessGroups=[dict(name=s['label'],revenue=s['revenue'],reportedMargin=s['margin'],observedGrowth=s['observedGrowth']) for s in m['segments']],reportedCash=[dict(id='cash.'+str(i),period=[p['start'],p['end']],reportedCfo=p['reportedCfo'],residual=p['residual']) for i,p in enumerate(m['bridge']['periods'])],cashAnchors=m['cashAnchors'],researchAssumptions=a,assumptionConvention='수입은 netInterest 양수, 비용은 음수. 성장·세율·재투자·할인율은 연구 가정. 비용 제거가 같은 사업 성장을 보장하지 않는다.',calculatedScenario=dict(firstCash=scenario['years'][0]['cash'],terminalCash=scenario['terminal']['cash'],conditionalPrice=scenario['price'],requiredTerminalCash=scenario['requiredTerminalCash'],forecast=False),priceHoldReason=m.get('priceHoldReason'),securityIssues=m['security'].get('issues',[]),sourceScopeRules=m['rules'],knownLimits=m['remaining'],suppliedOriginals=sources,scope='선택 원문과 기업별 현금 가정에 관한 파일 기반 개발 실험. 기존 coverage/filing 평가를 재사용하지 않고 정식 화면·원장은 변경하지 않는다.')


def prompt_packet(p):
 q=copy.deepcopy(p)
 q['suppliedOriginals']=[{k:x[k] for k in ['id','text','sourceHash']} for x in p['suppliedOriginals']]
 q['cashAnchors']=[{k:v for k,v in x.items() if k!='sourceUrl'} for x in p['cashAnchors']]
 return q


def protocol_hash():
 return digest(canonical(dict(version=VERSION,implementationHash=digest(Path(__file__).read_bytes()),system=SYSTEM,draft=DRAFT_TASK,review=REVIEW_TASK,draftSchema=DRAFT_SCHEMA,reviewSchema=review_schema([dict(id='item',role='hypothesis',text='검토 문장')]),selections=SELECTIONS)))


def validate_notes(notes):
 if not isinstance(notes,dict) or set(notes)!=set(base.ROLES) or not all(base.short_text(notes[k]) for k in base.ROLES):raise ValueError('Draft must have four bounded, numeral-free roles')
 if notes['hypothesis']==notes['alternative']:raise ValueError('Competing explanation repeats hypothesis')
 return notes
