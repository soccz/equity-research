"""Reconcile source periods while the integrated app inputs remain frozen."""
import importlib.util
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from equitylab.data import read_verified
from equitylab.xbrl import instance_rows, select

STAGE=Path(__file__).resolve().parent
ROOT=STAGE.parents[2]
spec=importlib.util.spec_from_file_location('pharma',STAGE/'pharma_comparison.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
c=json.loads((STAGE/'company-start.json').read_text())
a=json.loads((STAGE/'data/sources/filing-0000200406-26-000016-xbrl.manifest.json').read_text())
s=next(x for x in c['sources'] if x['file'].endswith('.xbrl'))
annual=instance_rows(read_verified(STAGE/a['file'],a['sha256']),c,a,a['accession'],'2026-02-11')
current=instance_rows(read_verified(ROOT/s['file'],s['sha256']),c,s,s['accession'],'2026-07-23')
periods=[(1,annual,'2024-12-30','2025-12-28'),(1,current,'2025-12-29','2026-06-28'),(-1,current,'2024-12-30','2025-06-29')]
checks=[]
for sign,rs,start,end in periods:
    def exact(tag,dims=()):
        if end=='2025-12-28':
            tag={'InProcessResearchAndDevelopmentCharge':'ResearchAndDevelopmentExpense',
                 'PaymentsToAcquireInProcessResearchAndDevelopmentAssets':'PaymentsToAcquiredInProcessResearchAndDevelopmentAssets'}.get(tag,tag)
        r=select([x for x in rs if x['decimals']=='-6'],tag,start,end,dims,'USD')
        if r is None:raise ValueError('Missing '+tag+' '+end)
        return r
    cf=[]
    for tag,label,effect,group in m.ROLES:
        f=exact(tag);cf.append(dict(label=label,tag=tag,effect=effect*f['value'],fact=f))
    cfo=exact('NetCashProvidedByUsedInOperatingActivities')
    residual=cfo['value']-sum(x['effect'] for x in cf)
    assert residual==0,(end,residual)
    segs=[]
    for member,label in [('InnovativeMedicineMember','Innovative Medicine'),('MedTechMember','MedTech')]:
        dims=[('ConsolidationItemsAxis','OperatingSegmentsMember'),('StatementBusinessSegmentsAxis',member)]
        segs.append(dict(label=label,revenue=exact(m.REVENUE,dims),pretax=exact(m.PRETAX,dims)))
    unallocated=exact('SegmentReportingOtherItemAmount');pretax=exact(m.PRETAX)
    assert sum(x['pretax']['value'] for x in segs)-unallocated['value']==pretax['value']
    cash_keys=['PaymentsToAcquirePropertyPlantAndEquipment','PaymentsToAcquireBusinessesNetOfCashAcquired',
        'PaymentsToAcquireInProcessResearchAndDevelopmentAssets','PaymentsForProceedsFromOtherInvestingActivities',
        'ProceedsPaymentsFromToCreditSupportAgreementsInvestingActivities','ProceedsPaymentsFromToCreditSupportAgreementsFinancingActivities']
    checks.append(dict(coefficient=sign,start=start,end=end,cfo=cfo,cashParts=cf,residual=residual,
                       segments=segs,unallocated=unallocated,pretax=pretax,
                       investmentCash={tag:exact(tag) for tag in cash_keys}))
ttm={key:sum(x['coefficient']*x[key]['value'] for x in checks) for key in ['cfo','pretax','unallocated']}
ttm['segments']=[dict(label=checks[0]['segments'][i]['label'],**{key:sum(x['coefficient']*x['segments'][i][key]['value'] for x in checks) for key in ['revenue','pretax']}) for i in range(2)]
ttm['investmentCash']={tag:sum(x['coefficient']*x['investmentCash'][tag]['value'] for x in checks) for tag in cash_keys}
result=dict(status='source_reconciled_not_normalized',company='JNJ',annualSource=a,
            currentSource=s,periods=checks,ttm=ttm,scope='Reported pretax and cash only; future costs, leases, licensing, acquisition replenishment, talc and other assets/liabilities need normalization. Annual source remains in isolated research directory.')
(STAGE/'annual-scope-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(ttm,ensure_ascii=False,indent=2))
