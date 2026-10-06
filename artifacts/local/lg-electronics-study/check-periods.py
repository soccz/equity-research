from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from equitylab.xbrl import select
P=Path(__file__).resolve().parent
CON=[('ConsolidatedAndSeparateFinancialStatementsAxis','ConsolidatedMember')]
REPORTED=CON+[('CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis','ReportedAmountMember')]
DISCON=CON+[('ContinuingAndDiscontinuedOperationsAxis','DiscontinuedOperationsMember')]
current=json.loads((P/'current-rows.json').read_text());annual=json.loads((P/'annual-rows.json').read_text())
for r in current+annual:r['dimensions']=[tuple(d) for d in r['dimensions']]
TAGS=dict(ni='ProfitLoss',adjustments='AdjustmentsForReconcileProfitLoss',working='AdjustmentsForAssetsLiabilitiesOfOperatingActivities',generated='CashFlowsFromUsedInOperations',received='InterestReceivedClassifiedAsOperatingActivities',paid='InterestPaidClassifiedAsOperatingActivities',dividends='DividendsReceivedClassifiedAsOperatingActivities',tax='IncomeTaxesPaidRefundClassifiedAsOperatingActivities',cfo='CashFlowsFromUsedInOperatingActivities',ppe='PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities',intangible='PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities',lease='PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities',depreciation='AdjustmentsForDepreciationExpense',amortization='AdjustmentsForAmortisationExpense')
output=[]
for coeff,rows,start,end,table in [(1,annual,'2025-01-01','2025-12-31',1249),(1,current,'2026-01-01','2026-06-30',770),(-1,current,'2025-01-01','2025-06-30',773)]:
 facts={}
 for k,tag in TAGS.items():
  fs=[f for dims in [CON,REPORTED] if (f:=select(rows,tag,start,end,dims,'KRW'))]
  if len({f['value'] for f in fs})!=1:raise ValueError((k,start,[(f['value'],f['dimensions']) for f in fs]))
  facts[k]=fs[0]
 v=lambda k:facts[k]['value']
 assert v('ni')+v('adjustments')+v('working')==v('generated')
 assert v('generated')+v('received')+v('dividends')-v('paid')-v('tax')==v('cfo')
 discontinued={k:select(rows,'CashFlowsFromUsedIn'+t+'ActivitiesDiscontinuedOperations',start,end,DISCON,'KRW') for k,t in [('cfo','Operating'),('cfi','Investing'),('cff','Financing')]}
 name='annual' if end=='2025-12-31' else 'current'
 narrative=next(x for x in json.loads((P/(name+'-discontinued-tables.json')).read_text()) if x['index']==table)
 output.append(dict(coefficient=coeff,start=start,end=end,facts=facts,discontinued=discontinued,narrative=narrative,residual=0))
 print(start,end,'CFO',v('cfo'),'capex',v('ppe')+v('intangible'),'cash bridge residual',0)
(P/'cash-periods.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
