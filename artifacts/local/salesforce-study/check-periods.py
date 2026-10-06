from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from equitylab.xbrl import select

P = Path(__file__).resolve().parent
annual = json.loads((P / "annual-rows.json").read_text())
current = json.loads((P / "current-rows.json").read_text())
for r in annual+current:
    r["dimensions"]=[tuple(d) for d in r["dimensions"]]
periods = [
    (1, annual, "2025-02-01", "2026-01-31"),
    (1, current, "2026-02-01", "2026-07-31"),
    (-1, current, "2025-02-01", "2025-07-31"),
]
cash = [
    ("NetIncomeLoss", 1), ("DepreciationAndAmortization", 1),
    ("CapitalizedContractCostAmortization", 1), ("ShareBasedCompensation", 1),
    ("GainLossOnInvestments", -1), ("IncreaseDecreaseInAccountsReceivable", -1),
    ("IncreaseDecreaseInCapitalizedContractCosts", -1),
    ("IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets", -1),
    ("IncreaseDecreaseInAccountsPayableAndAccruedLiabilities", 1),
    ("IncreaseDecreaseInOperatingLeaseLiability", 1),
    ("IncreaseDecreaseInContractWithCustomerLiability", 1),
]
out = []
for i,(coefficient,rows,start,end) in enumerate(periods):
    def exact(tag,dims=()):
        r=select([r for r in rows if r['decimals']=='-6'],tag,start,end,dims,'USD')
        if r is None:raise ValueError(f'Missing {tag} {start} {end}')
        return r
    parts=[dict(tag=tag,coefficient=sign,fact=exact(tag)) for tag,sign in cash]
    total=sum(p['coefficient']*p['fact']['value'] for p in parts)
    cfo=exact('NetCashProvidedByUsedInOperatingActivities')['value']
    segments=[]
    for member in ['SubscriptionandSupportMember','ProfessionalServicesandOtherMember']:
        dims=[('ProductOrServiceAxis',member)]
        sales=exact('RevenueFromContractWithCustomerExcludingAssessedTax',dims)
        cost=exact('CostOfGoodsAndServicesSold',dims)
        segments.append(dict(member=member,sales=sales,cost=cost,gross=sales['value']-cost['value']))
    revenue=exact('RevenueFromContractWithCustomerExcludingAssessedTax')['value']
    cost=exact('CostOfGoodsAndServicesSold')['value']
    expenses=[exact(tag) for tag in ['ResearchAndDevelopmentExpense','SellingAndMarketingExpense','GeneralAndAdministrativeExpense','RestructuringCharges']]
    income=revenue-cost-sum(f['value'] for f in expenses)
    lease=exact('PrincipalPaymentsFinanceLeasesAndFinanceObligations' if i==0 else 'FinanceLeasePrincipalPayments')
    checks=dict(cash=total-cfo,revenue=sum(s['sales']['value'] for s in segments)-revenue,cost=sum(s['cost']['value'] for s in segments)-cost,income=income-exact('OperatingIncomeLoss')['value'])
    if any(checks.values()):raise ValueError(checks)
    out.append(dict(coefficient=coefficient,start=start,end=end,parts=parts,reportedCfo=cfo,revenue=revenue,income=income,segments=segments,expenses=expenses,financeLease=lease,operatingLeaseCashAdjustment=exact('IncreaseDecreaseInOperatingLeaseLiability'),checks=checks))
(P/'candidate-periods.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps([dict(start=p['start'],end=p['end'],cfo=p['reportedCfo'],income=p['income'],checks=p['checks'],financeLease=p['financeLease']['value'],operatingLease=p['operatingLeaseCashAdjustment']['value']) for p in out]))
