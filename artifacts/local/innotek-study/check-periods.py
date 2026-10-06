from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from equitylab.xbrl import select
p=Path(__file__).resolve().parent
cur=json.loads((p/'current-rows.json').read_text());annual=json.loads((p/'annual-rows.json').read_text())
for r in cur+annual:r['dimensions']=[tuple(d) for d in r['dimensions']]
CON=[('ConsolidatedAndSeparateFinancialStatementsAxis','ConsolidatedMember')]
TAGS=dict(revenue='Revenue',operatingIncome='OperatingIncomeLoss',netIncome='ProfitLoss',generated='CashFlowsFromUsedInOperations',cfo='CashFlowsFromUsedInOperatingActivities',interestPaid='InterestPaidClassifiedAsOperatingActivities',interestReceived='InterestReceivedClassifiedAsOperatingActivities',tax='IncomeTaxesPaidRefundClassifiedAsOperatingActivities',capex='PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities',intangibles='PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities',lease='PaymentsOfFinanceLeaseLiabilitiesClassifiedAsFinancingActivities',depreciation='DepreciationExpense',amortization='AmortisationIntangibleAssetsOtherThanGoodwill',interestExpense='InterestExpenseFinanceExpense')
periods=[]
for rs,start,end in [(annual,'2025-01-01','2025-12-31'),(cur,'2026-01-01','2026-06-30'),(cur,'2025-01-01','2025-06-30')]:
 d={k:select(rs,t,start,end,CON,'KRW') for k,t in TAGS.items()}
 if start=='2025-01-01' and end=='2025-12-31':d['interestExpense']=select(rs,TAGS['interestExpense'],start,end,CON+[('CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis','ReportedAmountMember')],'KRW')
 missing=[k for k,v in d.items() if v is None];print(start,end,'missing',missing)
 if missing:continue
 v=lambda k:d[k]['value'];residual=v('generated')-v('interestPaid')+v('interestReceived')-v('tax')-v('cfo')
 print('CFO',v('cfo'),'bridge residual',residual,'PPE',v('capex'),'lease',v('lease'))
 segments=[]
 for member,label in [('OpticsSolutionSegmentsMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember','광학'),('SubstrateAndMaterialSegmentsMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember','패키지'),('AutomotiveComponentsSegmentsMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember','모빌리티')]:
  dims=CON+[('SegmentsAxis',member)]
  vals={k:select(rs,TAGS[k],start,end,dims,'KRW') for k in ['revenue','operatingIncome']}
  if any(x is None for x in vals.values()):print('missing segment',member)
  else:segments.append(dict(label=label,**vals))
 print('segment sums',[(key,sum(x[key]['value'] for x in segments)-v(key)) for key in ['revenue','operatingIncome']])
 periods.append(dict(start=start,end=end,facts=d,cashResidual=residual,segments=segments))
(p/'candidate-periods.json').write_text(json.dumps(periods,ensure_ascii=False,indent=2)+'\n')
