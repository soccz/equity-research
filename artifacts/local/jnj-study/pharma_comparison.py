"""Source-bound product, profit and cash comparison; no relative valuation."""

from equitylab.data import canonical, digest
from equitylab.narrative import load
from equitylab.xbrl import company_filing, select

CURRENT = '0000200406-26-000153'
CORPUS = '57cd21cfb2c13891c8b2e7d49a6012eb89a7aba8a2d2d12f06bb0383ba701a6a'
SOURCE = '0dd82cf03dc273d1818ed17eea3a378dcb7204c8aee16a2593b2697274260871'
PRETAX = 'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest'
REVENUE = 'RevenueFromContractWithCustomerExcludingAssessedTax'
ROLES = [
    ('NetIncomeLoss', '당기순이익', 1, 'earnings'),
    ('DepreciationDepletionAndAmortization', '감가상각·상각', 1, 'noncash'),
    ('ShareBasedCompensation', '주식보상 되돌림', 1, 'noncash'),
    ('AssetImpairmentCharges', '자산 감액', 1, 'noncash'),
    ('InProcessResearchAndDevelopmentCharge', '취득 진행 중 연구개발 조정', 1, 'noncash'),
    ('GainLossOnSalesOfAssetsAndAssetImpairmentCharges', '자산·사업 매각손익 되돌림', -1, 'noncash'),
    ('DeferredIncomeTaxExpenseBenefit', '이연법인세 조정', 1, 'noncash'),
    ('ProvisionForDoubtfulAccounts', '신용손실·채권 충당금', 1, 'noncash'),
    ('IncreaseDecreaseInAccountsReceivable', '매출채권 현금 효과', -1, 'tradeAssets'),
    ('IncreaseDecreaseInInventories', '재고 현금 효과', -1, 'tradeAssets'),
    ('IncreaseDecreaseInAccountsPayableAndAccruedLiabilities', '매입·미지급부채 현금 효과', 1, 'payables'),
    ('IncreaseDecreaseInOtherOperatingAssets', '기타 영업자산 현금 효과', -1, 'otherAssets'),
    ('IncreaseDecreaseInOtherOperatingLiabilities', '기타 영업부채 현금 효과', 1, 'otherLiabilities'),
]
PASSAGES = [
    '4250186352f99d454006', 'c208f703085fe650dd86', '1710e48a81b4a53e9d49',
    'f10212711e6978e3f926', '3fc5990413bc8fe4e532', 'f8b6c7d3ac3437d974d0',
    '5f3cc8eafe91860981cd', '4e22ed56461e098489a2', 'fcac921abb3356e03efb',
    'df75a8a02af78c2b8cae', 'c6defb6cc8c18878c304', '5440199e5853f880961e',
]
CELL_PASSAGES = ['2d2038e88606370f4d55', '77c8686a03776ffeac52', 'e5f22a72ee3c8a009917']


def build(jnj, cell, as_of):
    meta = jnj.get('narrative') or {}
    cm = cell.get('operatingModel') or {}
    if (meta.get('accession') != CURRENT or meta.get('evidenceHash') != CORPUS
            or cm.get('version') != 'celltrion-cash-classification-v1'):
        return dict(status='source_review_required', reason='제품·이익·현금 비교의 공시 버전을 다시 대사해야 합니다.')
    source, rows = company_filing(jnj, as_of)
    if source['sha256'] != SOURCE:
        raise ValueError('JNJ comparison source changed')
    f = jnj['financials']
    periods = [(f['start'], f['end']), (f['priorStart'], f['priorEnd'])]
    if periods != [('2025-12-29', '2026-06-28'), ('2024-12-30', '2025-06-29')]:
        raise ValueError('JNJ half-year comparison periods changed')
    index = {x['id']:x for x in load(jnj)['passages']}
    cell_index = {x['id']:x for x in load(cell)['passages']}
    if any(x not in index for x in PASSAGES) or any(x not in cell_index for x in CELL_PASSAGES):
        raise ValueError('Pharma comparison passage missing')

    def fact(tag, period=0, dims=()):
        start, end = periods[period]
        result = select([r for r in rows if r['decimals']=='-6'], tag, start, end, dims, 'USD')
        if result is None:
            raise ValueError('JNJ comparison missing exact fact: '+tag)
        return result

    def pair(tag, dims=()):
        current, previous = fact(tag, 0, dims), fact(tag, 1, dims)
        return dict(current=current, previous=previous, change=current['value']-previous['value'])

    cash_rows = []
    for tag, label, sign, group in ROLES:
        r = pair(tag)
        cash_rows.append(dict(**r, tag=tag, label=label, sign=sign, group=group,
                              effectCurrent=sign*r['current']['value'],
                              effectPrevious=sign*r['previous']['value'], effectChange=sign*r['change']))
    cfo = pair('NetCashProvidedByUsedInOperatingActivities')
    residuals = {k:cfo[k]['value']-sum(r['effect'+k.title()] for r in cash_rows) for k in ('current','previous')}
    if any(v != 0 for v in residuals.values()):
        raise ValueError('JNJ half-year cash bridge does not reconcile')
    grouped = [dict(id=key,label=label,value=sum(r['effectChange'] for r in cash_rows if r['group']==key))
               for key,label in [('earnings','순이익 변화'),('noncash','비현금 조정 변화'),
                    ('tradeAssets','매출채권·재고'),('payables','매입·미지급부채'),
                    ('otherAssets','기타 영업자산'),('otherLiabilities','기타 영업부채')]]
    if sum(r['value'] for r in grouped) != cfo['change']:
        raise ValueError('JNJ cash-change bridge failed')

    segments = []
    for member,label in [('InnovativeMedicineMember','Innovative Medicine'),('MedTechMember','MedTech')]:
        dims=[('ConsolidationItemsAxis','OperatingSegmentsMember'),('StatementBusinessSegmentsAxis',member)]
        segments.append(dict(label=label,revenue=pair(REVENUE,dims),pretax=pair(PRETAX,dims)))
    total=pair(PRETAX,[('ConsolidationItemsAxis','OperatingSegmentsMember')])
    corporate=pair('SegmentReportingOtherItemAmount')
    consolidated=pair(PRETAX)
    revenue=pair(REVENUE)
    for k in ('current','previous'):
        if (sum(s['pretax'][k]['value'] for s in segments)!=total[k]['value']
                or sum(s['revenue'][k]['value'] for s in segments)!=revenue[k]['value']
                or total[k]['value']-corporate[k]['value'] != consolidated[k]['value']):
            raise ValueError('JNJ pretax segment reconciliation failed')

    products=[]
    for member,label,cell_label,cell_pid in [
        ('StelaraMember','STELARA','스테키마 (CT-P43)','2d2038e88606370f4d55'),
        ('RemicadeMember','REMICADE','램시마 IV·SC / 짐펜트라','e5f22a72ee3c8a009917')]:
        dims=[('ProductOrServiceAxis',member),('StatementBusinessSegmentsAxis','InnovativeMedicineMember'),('SubsegmentsAxis','ImmunologyMember')]
        worldwide=pair(REVENUE,dims)
        regions=[dict(label=label,pair=pair(REVENUE,dims+[('StatementGeographicalAxis',region)]))
                 for region,label in [('US','미국'),('NonUsMember','미국 외')]]
        if member=='RemicadeMember':
            regions.append(dict(label='미국발 수출',pair=pair(REVENUE,dims+[('StatementGeographicalAxis','UNITEDSTATESExportsMember')])))
        rounding={k:worldwide[k]['value']-sum(r['pair'][k]['value'] for r in regions) for k in ('current','previous')}
        bound=(len(regions)+1)*500000
        if any(abs(v)>bound for v in rounding.values()):
            raise ValueError('JNJ product geography does not reconcile within source precision')
        products.append(dict(label=label,worldwide=worldwide,regions=regions,rounding=rounding,
                             roundingBound=bound,changeRatio=worldwide['change']/worldwide['previous']['value'],
                             celltrion=dict(label=cell_label,matchedProductSales=None,matchedCash=None,
                                            source=cell_index[cell_pid],status='scope_unmatched')))
    investments=[dict(label=label,values=pair(tag)) for tag,label in [
        ('PaymentsToAcquirePropertyPlantAndEquipment','유형자산 현금 취득'),
        ('PaymentsToAcquireBusinessesNetOfCashAcquired','기업 인수 순현금'),
        ('PaymentsToAcquireInProcessResearchAndDevelopmentAssets','진행 중 연구개발 취득·마일스톤'),
        ('PaymentsForProceedsFromOtherInvestingActivities','기타 투자 (라이선스·마일스톤 포함)'),
    ]]
    result=dict(
        version='pharma-product-cash-comparison-v1',status='source_calculation',financialApproval=False,
        companies=['JNJ','068270'],periods=dict(JNJ=[list(p) for p in periods],
            celltrion=[[cell['financials']['start'],cell['financials']['end']],
                       [cell['financials']['priorStart'],cell['financials']['priorEnd']]]),
        products=products,
        pretax=dict(segments=segments,total=total,corporate=corporate,consolidated=consolidated,
                    changeComponents=[dict(label=s['label']+' 세전이익',value=s['pretax']['change']) for s in segments]+
                    [dict(label='미배분 순비용 변화',value=-corporate['change'])]),
        cash=dict(cfo=cfo,rows=cash_rows,changeComponents=grouped,residuals=residuals),
        investments=investments,
        legalReserve=dict(approximatePresentValue=3.7e9,approximateCurrentShare=.4,
                          maximumExposure=None,source=index['5f3cc8eafe91860981cd']),
        sources=[index[x] for x in PASSAGES]+[cell_index[x] for x in CELL_PASSAGES],
        decision=dict(
            statement='현재 근거는 JNJ 기존 제품의 경쟁 압력과 셀트리온 대응 제품의 존재를 연결한다. 셀트리온이 그 감소분을 같은 금액의 현금으로 가져갔는지는 확인되지 않았다.',
            countercase='JNJ 다른 제품·인수와 환율, 셀트리온의 판매 구성·리베이트·출시비·재고 및 개발비가 연결 실적에 함께 작용한다.',
            changeConditions=[
                '같은 성분·지역·반기의 순매출, 물량과 순가격을 양사 및 다른 경쟁사에서 확보한다.',
                '셀트리온 제품 매출 증가를 매출채권·재고·리베이트·상업화 비용 이후 현금과 연결한다.',
                'JNJ 미배분 소송·이자·본사 비용과 인수 영향을 부문 세전이익 변화와 분리한다.',
            ],
            relativePreference=None,
        ),
        scope='JNJ는 보고 부문 세전이익, 셀트리온은 영업이익이다. JNJ 반기 말은 6월28일, 셀트리온은 6월30일이며 통화·사업 범위도 다르다. 계산 대사와 투자 선호를 구분한다.',
    )
    result['evidenceHash']=digest(canonical(result))
    return result
