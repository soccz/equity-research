"""Reviewed statement-sign audit before adopting Tesla's business cash model."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from equitylab.xbrl import select
rows=json.loads((ROOT/'artifacts/local/tesla-current-annual-rows.json').read_text())
for rs in rows.values():
 for r in rs:r['dimensions']=[tuple(x) for x in r['dimensions']]
roles=[('ProfitLoss',1),('DepreciationAmortizationAndImpairment',1),('ShareBasedCompensation',1),('InventoryWriteDown',1),('ForeignCurrencyTransactionGainLossUnrealized',-1),('DeferredIncomeTaxExpenseBenefit',1),('NoncashInterestIncomeExpenseAndOtherOperatingActivities',-1),('GainLossOnDigitalAssets',-1),('IncreaseDecreaseInAccountsReceivable',-1),('IncreaseDecreaseInInventories',-1),('IncreaseDecreaseInOperatingLeaseVehicles',-1),('IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets',-1),('IncreaseDecreaseInAccountsPayableAndAccruedLiabilities',1),('IncreaseDecreaseInContractWithCustomerLiability',1)]
groups=['AutomotiveSalesMember','AutomotiveRegulatoryCreditsMember','AutomotiveLeasingMember','EnergyGenerationAndStorageMember','ServicesAndOtherMember']
periods=[]
for kind,start,end in [('annual','2025-01-01','2025-12-31'),('current','2026-01-01','2026-06-30'),('current','2025-01-01','2025-06-30')]:
 rs=[r for r in rows[kind] if r['decimals']=='-6']
 def fact(tag,dimensions=()):
  r=select(rs,tag,start,end,dimensions,'USD')
  if r is None:raise ValueError(tag+' missing '+start+' '+end)
  return r
 parts=[dict(coefficient=k,fact=fact(tag)) for tag,k in roles]
 if start=='2026-01-01':parts.append(dict(coefficient=-1,fact=fact('UnrealizedGainLossOnInvestments')))
 cfo=fact('NetCashProvidedByUsedInOperatingActivities')
 assert sum(p['coefficient']*p['fact']['value'] for p in parts)==cfo['value']
 products=[]
 for g in groups:
  dims=[('ProductOrServiceAxis',g)];revenue=fact('RevenueFromContractWithCustomerExcludingAssessedTax',dims)
  if g=='AutomotiveRegulatoryCreditsMember':
   items=[(1,'AutomotiveRevenuesMember'),(-1,'AutomotiveSalesMember'),(-1,'AutomotiveLeasingMember')]
   cs=[dict(coefficient=k,fact=fact('CostOfRevenue',[('ProductOrServiceAxis',member)])) for k,member in items]
   cost=dict(value=sum(x['coefficient']*x['fact']['value'] for x in cs),components=cs,scope='reported cost subtotal less sales and leasing allocation; not zero economic cost')
  else:cost=fact('CostOfRevenue',dims)
  products.append(dict(member=g,revenue=revenue,cost=cost,grossProfit=revenue['value']-cost['value']))
 total_sales=fact('RevenueFromContractWithCustomerExcludingAssessedTax');gp=fact('GrossProfit');op=fact('OperatingIncomeLoss')
 expense=[fact(t) for t in ['ResearchAndDevelopmentExpense','SellingGeneralAndAdministrativeExpense','RestructuringAndOtherExpenses']]
 assert sum(x['revenue']['value'] for x in products)==total_sales['value']
 assert sum(x['grossProfit'] for x in products)==gp['value']
 assert gp['value']-sum(x['value'] for x in expense)==op['value']
 periods.append(dict(start=start,end=end,cfo=cfo,cashParts=parts,cfoResidual=0,revenue=total_sales,grossProfit=gp,operatingIncome=op,products=products,operatingExpenses=expense))
 print(start,end,'revenue',total_sales['value']/1e9,'OP',op['value']/1e9,'CFO',cfo['value']/1e9)
record={'status':'source arithmetic audit; no adopted business cash model yet','periods':periods,'zeroInvestmentGainContract':'The current filing says the SpaceX equity investment was entered into in March 2026; prior annual and H1 do not include this investment gain. This is a filing-specific scope decision, not a missing-value zero fallback.','sources':['https://www.sec.gov/Archives/edgar/data/1318605/000162828026003952/tsla-20251231.htm','https://www.sec.gov/Archives/edgar/data/1318605/000162828026049270/tsla-20260630.htm']}
(ROOT/'artifacts/local/tesla-three-period-cash-audit.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
