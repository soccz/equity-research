"""Source-specific equal dividend/liquidation entitlement; not voting value."""
import json
from equitylab.data import ROOT, read_verified, digest, canonical
from equitylab.narrative import extract
from equitylab.xbrl import select

ACCESSION="0001628280-26-050705"
XBRL="6716e6b0f4978717e019177bc8275ac8ea17fea03b9db7c08a0c4818e7866ba8"
HTML="e5666644af7c69de3081f0747dd19ef52e7abf0593fbf6fc7fa2a94c907af330"


def meta_entitlement(c, available, members, preferred):
    if c['id']!='META' or c.get('cik')!=1326801 or preferred or set(members)!={'CommonClassAMember','CommonClassBMember'}:
        return None
    core=c['financials']['current']['cfo']
    if core['accession']!=ACCESSION or c['financials']['end']!='2026-06-30':return None
    facts=[]
    for member in ['CommonClassAMember','CommonClassBMember']:
        r=select(available,'EntityCommonStockSharesOutstanding',None,'2026-07-24',[('StatementClassOfStockAxis',member)],'shares')
        if not r or r['accession']!=ACCESSION or r['sourceHash']!=XBRL or r['decimals']!='INF':return None
        facts.append(r)
    if [r['value'] for r in facts]!=[2205128509,342377716]:return None
    manifest=json.loads((ROOT/f'data/sources/filing-{ACCESSION}.manifest.json').read_text())
    if manifest['sha256']!=HTML or manifest['accession']!=ACCESSION or manifest['cik']!=1326801:return None
    if core['filedAt']>c['priceSummary']['lastDate']:return None
    passages=extract(read_verified(ROOT/manifest['file'],HTML))
    selected=[p for p in passages if p['ordinal'] in [24,25,210,211,223]]
    by_ordinal={p['ordinal']:p for p in selected}
    if len(selected)!=5 or not all(s in by_ordinal[210]['text'] for s in ['identical liquidation and dividend rights','different voting rights']):return None
    if not all(s in by_ordinal[24]['text'] for s in ['2,205,128,509','July 24, 2026']) or not all(s in by_ordinal[25]['text'] for s in ['342,377,716','July 24, 2026']):return None
    if manifest['file'] not in {s['file'] for s in c['sources']}:c['sources'].append(manifest)
    quote=by_ordinal[210]['text']
    assumption='A·B주 배당·청산권이 동일하다는 공시 범위에서 합산 주식수당 현금을 A주 종가와 비교합니다. B주의 시장가격이나 의결권 가치를 같다고 평가한 것이 아니며, A주 가격×합산 수량은 비교용 대용치입니다.'
    evidence=dict(accession=ACCESSION,sourceUrl=manifest['url'],sourceHash=HTML,passages=selected,quote=quote,assumption=assumption,classes=[dict(label='Class A' if i==0 else 'Class B',fact=r) for i,r in enumerate(facts)])
    evidence['evidenceHash']=digest(canonical(evidence))
    shares=dict(value=sum(r['value'] for r in facts),end='2026-07-24',start=None,unit='shares',derived=True,tag='EqualDividendLiquidationShares',accession=ACCESSION,filedAt=core['filedAt'],sourceUrl=manifest['url'],sourceFile=manifest['file'],sourceHash=HTML,components=[dict(coefficient=1,fact=r) for r in facts],scope=assumption)
    return dict(shares=shares,evidence=evidence,assumption=assumption)
